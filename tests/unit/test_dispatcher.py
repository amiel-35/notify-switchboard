"""Tests for the side-effecting half of the router."""

from __future__ import annotations

from datetime import datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import homeassistant.helpers.device_registry as dr
import homeassistant.helpers.entity_registry as er
import homeassistant.helpers.issue_registry as ir
import homeassistant.util.dt as dt_util
import pytest
from homeassistant.const import EVENT_HOMEASSISTANT_STOP
from homeassistant.core import Context, HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
    async_mock_service,
)

from custom_components.notify_switchboard import async_migrate_entry
from custom_components.notify_switchboard.const import DOMAIN
from custom_components.notify_switchboard.diagnostics import (
    async_get_config_entry_diagnostics,
)
from custom_components.notify_switchboard.dispatcher import (
    OUTPUT_TIMEOUT_SECONDS,
    companion_service_name,
    next_wake_time,
)
from custom_components.notify_switchboard.store import DeferredMessage


def make_person(entity_id: str, outputs: list[str], **overrides: Any) -> dict:
    """Build one `entry.options["persons"]` row."""
    row = {
        "entity_id": entity_id,
        "outputs": outputs,
        "silence_entities": [],
        "wake_time": None,
    }
    row.update(overrides)
    return row


def make_target(slug: str, **overrides: Any) -> dict:
    """Build one `entry.options["targets"]` row."""
    row = {
        "slug": slug,
        "name": slug.title(),
        "class": "test",
        "default_priority": "normal",
        "alert_entity": None,
        "audience": ["person.alice"],
        "presence_rule": "always",
        "allow_acknowledge": False,
        "snooze_minutes": [],
        "default_data": {},
        "observer_mode": False,
    }
    row.update(overrides)
    return row


async def install(
    hass: HomeAssistant, persons: list[dict], targets: list[dict], default: str
) -> MockConfigEntry:
    """Create and set up a config entry."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id="ns_unit_entry",
        title="Notify Switchboard",
        version=1,
        minor_version=1,
        options={
            "persons": persons,
            "targets": targets,
            "default_target": default,
        },
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


# ---------------------------------------------------------------------------
# next_wake_time
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("local_now", "expected"),
    [
        # Later the same day.
        ("2026-09-10T05:00:00+02:00", "2026-09-10T07:00:00+02:00"),
        # Already past: tomorrow.
        ("2026-09-10T23:30:00+02:00", "2026-09-11T07:00:00+02:00"),
        # Exactly on the hour counts as past.
        ("2026-09-10T07:00:00+02:00", "2026-09-11T07:00:00+02:00"),
        # Across the Europe/Paris fall-back: 07:00 is CET (UTC+1), not UTC+2.
        ("2026-10-24T23:30:00+02:00", "2026-10-25T07:00:00+01:00"),
    ],
)
def test_next_wake_time(local_now: str, expected: str) -> None:
    """The next wake time is built from a date, never by adding 24 hours."""
    paris = ZoneInfo("Europe/Paris")
    now = datetime.fromisoformat(local_now).astimezone(paris)
    result = next_wake_time(now, time(7, 0))
    assert result == datetime.fromisoformat(expected)
    assert result.utcoffset() == datetime.fromisoformat(expected).utcoffset()


# ---------------------------------------------------------------------------
# Robustness
# ---------------------------------------------------------------------------


async def test_missing_output_is_tolerated_then_repaired(hass: HomeAssistant) -> None:
    """An absent output is retried; after three misses a repair is raised."""
    hass.states.async_set("person.alice", "home")
    entry = await install(
        hass,
        [make_person("person.alice", ["mobile_app_ghost"])],
        [make_target("leak")],
        "leak",
    )
    registry = ir.async_get(hass)

    for _ in range(3):
        await hass.services.async_call(
            "notify", "switchboard_leak", {"message": "m"}, blocking=True
        )
        await hass.async_block_till_done()
    assert (DOMAIN, "missing_output_mobile_app_ghost") not in registry.issues

    await hass.services.async_call(
        "notify", "switchboard_leak", {"message": "m"}, blocking=True
    )
    await hass.async_block_till_done()
    assert (DOMAIN, "missing_output_mobile_app_ghost") in registry.issues

    # Nothing was ever delivered, so nothing is counted as routed: the four
    # calls are four `delivery_failed` drops.
    assert hass.states.get("sensor.switchboard_routed_today").state == "0"
    dropped = hass.states.get("sensor.switchboard_dropped_today")
    assert dropped.state == "4"
    assert dropped.attributes["reasons"] == {"delivery_failed": 4}
    assert entry.runtime_data.switchboard.failing_outputs["mobile_app_ghost"] == 4


async def test_output_reappearing_clears_the_miss_counter(
    hass: HomeAssistant,
) -> None:
    """A service registered late is picked up on the next call."""
    hass.states.async_set("person.alice", "home")
    entry = await install(
        hass,
        [make_person("person.alice", ["mobile_app_late"])],
        [make_target("leak")],
        "leak",
    )
    await hass.services.async_call(
        "notify", "switchboard_leak", {"message": "m"}, blocking=True
    )
    await hass.async_block_till_done()
    assert entry.runtime_data.switchboard.failing_outputs == {"mobile_app_late": 1}

    calls = async_mock_service(hass, "notify", "mobile_app_late")
    await hass.services.async_call(
        "notify", "switchboard_leak", {"message": "m"}, blocking=True
    )
    await hass.async_block_till_done()
    assert len(calls) == 1
    assert entry.runtime_data.switchboard.failing_outputs == {}


async def test_output_written_with_the_notify_prefix_is_equivalent(
    hass: HomeAssistant,
) -> None:
    """`notify.mobile_app_alice` delivers and gets buttons like `mobile_app_alice`."""
    calls = async_mock_service(hass, "notify", "mobile_app_alice")
    hass.states.async_set("person.alice", "home")
    entry = await install(
        hass,
        [make_person("person.alice", ["notify.mobile_app_alice"])],
        [
            make_target(
                "leak",
                alert_entity="alert.leak",
                allow_acknowledge=True,
                snooze_minutes=[15],
                default_priority="high",
            )
        ],
        "leak",
    )
    await hass.services.async_call(
        "notify", "switchboard_leak", {"message": "m"}, blocking=True
    )
    await hass.async_block_till_done()

    assert len(calls) == 1
    data = calls[0].data["data"]
    assert [action["action"] for action in data["actions"]] == [
        "switchboard:ack:leak",
        "switchboard:snooze:leak:15",
    ]
    assert data["authenticationRequired"] is True
    # The table stores the bare service name, so person resolution matches it.
    switchboard = entry.runtime_data.switchboard
    assert switchboard.table.persons["person.alice"].outputs == ("mobile_app_alice",)
    owner = switchboard.table.person_for_output("mobile_app_alice")
    assert owner is not None and owner.entity_id == "person.alice"


async def test_prefixed_recursive_output_is_still_rejected(
    hass: HomeAssistant,
) -> None:
    """`notify.switchboard_loop` recurses just as much as `switchboard_loop`."""
    hass.states.async_set("person.eve", "home")
    await install(
        hass,
        [make_person("person.eve", ["notify.switchboard_loop"])],
        [make_target("loop", audience=["person.eve"])],
        "loop",
    )
    await hass.services.async_call(
        "notify", "switchboard_loop", {"message": "m"}, blocking=True
    )
    await hass.async_block_till_done()

    dropped = hass.states.get("sensor.switchboard_dropped_today")
    assert dropped.attributes["reasons"]["recursion"] == 1


async def test_audience_member_absent_from_persons_is_a_counted_drop(
    hass: HomeAssistant,
) -> None:
    """A row naming somebody the table does not know is `unknown_person`."""
    async_mock_service(hass, "notify", "mobile_app_alice")
    hass.states.async_set("person.alice", "home")
    await install(
        hass,
        [make_person("person.alice", ["mobile_app_alice"])],
        [make_target("leak", audience=["person.alice", "person.ghost"])],
        "leak",
    )
    await hass.services.async_call(
        "notify", "switchboard_leak", {"message": "m"}, blocking=True
    )
    await hass.async_block_till_done()

    dropped = hass.states.get("sensor.switchboard_dropped_today")
    assert dropped.state == "1"
    assert dropped.attributes["reasons"] == {"unknown_person": 1}


async def test_non_companion_output_gets_no_buttons(hass: HomeAssistant) -> None:
    """Only `mobile_app_*` outputs receive Companion actions."""
    calls = async_mock_service(hass, "notify", "telegram_family")
    hass.states.async_set("person.alice", "home")
    await install(
        hass,
        [make_person("person.alice", ["telegram_family"])],
        [
            make_target(
                "leak",
                alert_entity="alert.leak",
                allow_acknowledge=True,
                snooze_minutes=[15],
                default_priority="critical",
            )
        ],
        "leak",
    )
    await hass.services.async_call(
        "notify", "switchboard_leak", {"message": "m"}, blocking=True
    )
    await hass.async_block_till_done()

    data = calls[0].data.get("data", {})
    assert "actions" not in data
    assert "authenticationRequired" not in data


# ---------------------------------------------------------------------------
# Degraded NotifyEntity path
# ---------------------------------------------------------------------------


async def test_notify_entity_routes_to_the_default_target(
    hass: HomeAssistant,
) -> None:
    """`notify.send_message` carries message and title to the default row."""
    calls = async_mock_service(hass, "notify", "mobile_app_alice")
    hass.states.async_set("person.alice", "home")
    await install(
        hass,
        [make_person("person.alice", ["mobile_app_alice"])],
        [make_target("leak"), make_target("garage")],
        "garage",
    )

    await hass.services.async_call(
        "notify",
        "send_message",
        {"entity_id": "notify.switchboard", "message": "hello", "title": "hi"},
        blocking=True,
    )
    await hass.async_block_till_done()

    assert len(calls) == 1
    assert calls[0].data["message"] == "hello"
    assert calls[0].data["title"] == "hi"
    assert calls[0].data["data"]["priority"] == "normal"


# ---------------------------------------------------------------------------
# Translations
# ---------------------------------------------------------------------------


async def test_observer_back_to_normal_uses_the_home_assistant_language(
    hass: HomeAssistant,
) -> None:
    """The router-added text follows `hass.config.language` (doctrine §3.6)."""
    hass.config.language = "fr"
    calls = async_mock_service(hass, "notify", "mobile_app_alice")
    hass.states.async_set("person.alice", "home")
    await install(
        hass,
        [make_person("person.alice", ["mobile_app_alice"])],
        [make_target("observed", alert_entity="alert.observed", observer_mode=True)],
        "observed",
    )

    hass.states.async_set("alert.observed", "idle")
    await hass.async_block_till_done()
    hass.states.async_set("alert.observed", "on")
    await hass.async_block_till_done()
    hass.states.async_set("alert.observed", "idle")  # no done_message attribute
    await hass.async_block_till_done()

    assert [call.data["message"] for call in calls] == [
        "Observed",
        "Tout est revenu à la normale",
    ]


async def test_companion_button_labels_are_translated(hass: HomeAssistant) -> None:
    """Acknowledge and Snooze labels come from `common.*`."""
    hass.config.language = "fr"
    calls = async_mock_service(hass, "notify", "mobile_app_alice")
    hass.states.async_set("person.alice", "home")
    await install(
        hass,
        [make_person("person.alice", ["mobile_app_alice"])],
        [
            make_target(
                "leak",
                alert_entity="alert.leak",
                allow_acknowledge=True,
                snooze_minutes=[15],
            )
        ],
        "leak",
    )
    await hass.services.async_call(
        "notify", "switchboard_leak", {"message": "m"}, blocking=True
    )
    await hass.async_block_till_done()

    titles = [action["title"] for action in calls[0].data["data"]["actions"]]
    assert titles == ["J'ai vu", "Reporter 15 min"]


# ---------------------------------------------------------------------------
# Counters
# ---------------------------------------------------------------------------


async def test_counters_reset_at_local_midnight(
    hass: HomeAssistant, freezer: Any
) -> None:
    """`routed_today` and `dropped_today` restart every local day."""
    await hass.config.async_set_time_zone("Europe/Paris")
    freezer.move_to(datetime(2026, 9, 10, 20, 0, tzinfo=dt_util.UTC))  # 22:00 Paris

    async_mock_service(hass, "notify", "mobile_app_alice")
    hass.states.async_set("person.alice", "home")
    await install(
        hass,
        [make_person("person.alice", ["mobile_app_alice"])],
        [make_target("leak")],
        "leak",
    )

    await hass.services.async_call(
        "notify", "switchboard_leak", {"message": "m"}, blocking=True
    )
    await hass.async_block_till_done()
    assert hass.states.get("sensor.switchboard_routed_today").state == "1"

    freezer.move_to(datetime(2026, 9, 10, 22, 5, tzinfo=dt_util.UTC))  # 00:05 Paris
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done()
    assert hass.states.get("sensor.switchboard_routed_today").state == "0"


async def test_dropped_reasons_do_not_count_people_outside_the_audience(
    hass: HomeAssistant,
) -> None:
    """Somebody the row does not name is "not considered", not dropped."""
    async_mock_service(hass, "notify", "mobile_app_alice")
    async_mock_service(hass, "notify", "mobile_app_bob")
    hass.states.async_set("person.alice", "home")
    hass.states.async_set("person.bob", "home")
    await install(
        hass,
        [
            make_person("person.alice", ["mobile_app_alice"]),
            make_person("person.bob", ["mobile_app_bob"]),
        ],
        [make_target("leak", audience=["person.alice"])],
        "leak",
    )
    await hass.services.async_call(
        "notify", "switchboard_leak", {"message": "m"}, blocking=True
    )
    await hass.async_block_till_done()

    dropped = hass.states.get("sensor.switchboard_dropped_today")
    assert dropped.state == "0"
    assert dropped.attributes["reasons"] == {}


# ---------------------------------------------------------------------------
# Persistence and diagnostics
# ---------------------------------------------------------------------------


async def test_deferred_message_survives_a_reload(
    hass: HomeAssistant, hass_storage: dict, freezer: Any
) -> None:
    """A queued night message is still delivered after a restart."""
    await hass.config.async_set_time_zone("Europe/Paris")
    freezer.move_to(datetime(2026, 9, 10, 21, 30, tzinfo=dt_util.UTC))  # 23:30 Paris

    calls = async_mock_service(hass, "notify", "mobile_app_alice")
    hass.states.async_set("person.alice", "home")
    hass.states.async_set("input_boolean.night", "on")
    entry = await install(
        hass,
        [
            make_person(
                "person.alice",
                ["mobile_app_alice"],
                silence_entities=["input_boolean.night"],
                wake_time="07:00:00",
            )
        ],
        [make_target("leak")],
        "leak",
    )

    await hass.services.async_call(
        "notify",
        "switchboard_leak",
        {"message": "night", "data": {"tag": "t"}},
        blocking=True,
    )
    await hass.async_block_till_done()
    assert calls == []

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    freezer.move_to(datetime(2026, 9, 11, 5, 5, tzinfo=dt_util.UTC))  # 07:05 Paris
    hass.states.async_set("input_boolean.night", "off")
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done()

    assert [call.data["message"] for call in calls] == ["night"]


async def test_deferral_whose_wake_time_passed_is_delivered_at_the_next_setup(
    hass: HomeAssistant, hass_storage: dict, freezer: Any
) -> None:
    """Queued at 23:30, reloaded at 09:00 the next day: delivered at reload."""
    await hass.config.async_set_time_zone("Europe/Paris")
    freezer.move_to(datetime(2026, 9, 10, 21, 30, tzinfo=dt_util.UTC))  # 23:30 Paris

    calls = async_mock_service(hass, "notify", "mobile_app_alice")
    hass.states.async_set("person.alice", "home")
    hass.states.async_set("input_boolean.night", "on")
    entry = await install(
        hass,
        [
            make_person(
                "person.alice",
                ["mobile_app_alice"],
                silence_entities=["input_boolean.night"],
                wake_time="07:00:00",
            )
        ],
        [make_target("leak")],
        "leak",
    )
    await hass.services.async_call(
        "notify",
        "switchboard_leak",
        {"message": "night", "data": {"tag": "t"}},
        blocking=True,
    )
    await hass.async_block_till_done()
    assert calls == []
    assert hass.states.get("sensor.switchboard_deferred_today").state == "1"

    # Home Assistant is down across 07:00 and comes back at 09:00.
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    freezer.move_to(datetime(2026, 9, 11, 7, 0, tzinfo=dt_util.UTC))  # 09:00 Paris
    hass.states.async_set("input_boolean.night", "off")
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    # Delivered at the reload, not a day later, and exactly once.
    assert [call.data["message"] for call in calls] == ["night"]
    assert entry.runtime_data.switchboard.store.deferrals == {}


async def test_a_deferral_still_within_the_night_is_not_delivered_early(
    hass: HomeAssistant, hass_storage: dict, freezer: Any
) -> None:
    """A reload before the wake time keeps the message queued."""
    await hass.config.async_set_time_zone("Europe/Paris")
    freezer.move_to(datetime(2026, 9, 10, 21, 30, tzinfo=dt_util.UTC))  # 23:30 Paris

    calls = async_mock_service(hass, "notify", "mobile_app_alice")
    hass.states.async_set("person.alice", "home")
    hass.states.async_set("input_boolean.night", "on")
    entry = await install(
        hass,
        [
            make_person(
                "person.alice",
                ["mobile_app_alice"],
                silence_entities=["input_boolean.night"],
                wake_time="07:00:00",
            )
        ],
        [make_target("leak")],
        "leak",
    )
    await hass.services.async_call(
        "notify", "switchboard_leak", {"message": "night"}, blocking=True
    )
    await hass.async_block_till_done()

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    freezer.move_to(datetime(2026, 9, 10, 23, 0, tzinfo=dt_util.UTC))  # 01:00 Paris
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert calls == []
    assert len(entry.runtime_data.switchboard.store.deferrals) == 1


async def test_a_deferral_stored_before_queued_at_existed_is_migrated(
    hass: HomeAssistant, hass_storage: dict, freezer: Any
) -> None:
    """Minor version 1 rows get a `queued_at` and keep waiting, not fire."""
    await hass.config.async_set_time_zone("Europe/Paris")
    freezer.move_to(datetime(2026, 9, 11, 7, 0, tzinfo=dt_util.UTC))  # 09:00 Paris

    hass_storage["notify_switchboard.data"] = {
        "version": 1,
        "minor_version": 1,
        "key": "notify_switchboard.data",
        "data": {
            "snoozes": [],
            "deferrals": [
                {
                    "person": "person.alice",
                    "slug": "leak",
                    "tag": "t",
                    "message": "old",
                    "title": None,
                    "priority": "normal",
                    "data": {},
                }
            ],
        },
    }

    calls = async_mock_service(hass, "notify", "mobile_app_alice")
    hass.states.async_set("person.alice", "home")
    entry = await install(
        hass,
        [make_person("person.alice", ["mobile_app_alice"], wake_time="07:00:00")],
        [make_target("leak")],
        "leak",
    )

    # No `queued_at` means "assume it was queued now": it waits for 07:00
    # tomorrow instead of firing on the upgrade.
    assert calls == []
    stored = entry.runtime_data.switchboard.store.deferrals[
        ("person.alice", "leak", "t")
    ]
    assert stored.queued_at == dt_util.utcnow()
    # Re-saved at the current minor version: the same load also ran the
    # minor 3 step, which only adds an empty `silences` list.
    assert hass_storage["notify_switchboard.data"]["minor_version"] == 3
    assert hass_storage["notify_switchboard.data"]["data"]["silences"] == []


async def test_daily_counters_reset_at_local_midnight(
    hass: HomeAssistant, freezer: Any
) -> None:
    """`TOTAL` + `last_reset` = local midnight, not `TOTAL_INCREASING`."""
    await hass.config.async_set_time_zone("Europe/Paris")
    freezer.move_to(datetime(2026, 9, 10, 12, 0, tzinfo=dt_util.UTC))  # 14:00 Paris

    async_mock_service(hass, "notify", "mobile_app_alice")
    hass.states.async_set("person.alice", "home")
    await install(
        hass,
        [make_person("person.alice", ["mobile_app_alice"])],
        [make_target("leak")],
        "leak",
    )

    midnight = datetime(2026, 9, 9, 22, 0, tzinfo=dt_util.UTC)  # 2026-09-10 00:00 Paris
    for entity_id in (
        "sensor.switchboard_routed_today",
        "sensor.switchboard_dropped_today",
        "sensor.switchboard_deferred_today",
    ):
        state = hass.states.get(entity_id)
        assert state.attributes["state_class"] == "total"
        assert dt_util.parse_datetime(state.attributes["last_reset"]) == midnight


async def test_the_pre_0_1_0_notify_entity_orphan_is_removed(
    hass: HomeAssistant,
) -> None:
    """Upgrading from 0.0.1 must not leave `notify.switchboard` unavailable.

    0.0.1 gave the `NotifyEntity` the unique_id `<entry_id>_notify_entity`;
    0.1.0 gives it `<entry_id>:entity`. Without cleanup the registry keeps the
    old row, holds on to `notify.switchboard`, and the working entity lands on
    `notify.switchboard_2`.
    """
    async_mock_service(hass, "notify", "mobile_app_alice")
    hass.states.async_set("person.alice", "home")

    entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id="ns_unit_entry",
        title="Notify Switchboard",
        version=1,
        minor_version=1,
        options={
            "persons": [make_person("person.alice", ["mobile_app_alice"])],
            "targets": [make_target("leak")],
            "default_target": "leak",
        },
    )
    entry.add_to_hass(hass)

    registry = er.async_get(hass)
    orphan = registry.async_get_or_create(
        "notify",
        DOMAIN,
        "ns_unit_entry_notify_entity",
        suggested_object_id="switchboard",
        config_entry=entry,
    )
    assert orphan.entity_id == "notify.switchboard"

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    remaining = {
        item.unique_id: item.entity_id
        for item in er.async_entries_for_config_entry(registry, entry.entry_id)
    }
    assert "ns_unit_entry_notify_entity" not in remaining
    assert remaining["ns_unit_entry:entity"] == "notify.switchboard"
    assert hass.states.get("notify.switchboard_2") is None


async def test_removing_the_entry_deletes_the_stored_document(
    hass: HomeAssistant, hass_storage: dict
) -> None:
    """`async_remove_entry` drops `.storage/notify_switchboard.data`."""
    async_mock_service(hass, "notify", "mobile_app_alice")
    hass.states.async_set("person.alice", "home")
    hass.states.async_set("input_boolean.night", "on")
    entry = await install(
        hass,
        [
            make_person(
                "person.alice",
                ["mobile_app_alice"],
                silence_entities=["input_boolean.night"],
                wake_time="07:00:00",
            )
        ],
        [make_target("leak")],
        "leak",
    )
    await hass.services.async_call(
        "notify", "switchboard_leak", {"message": "queued"}, blocking=True
    )
    await hass.async_block_till_done()
    assert "notify_switchboard.data" in hass_storage

    assert await hass.config_entries.async_remove(entry.entry_id) == {
        "require_restart": False
    }
    await hass.async_block_till_done()
    assert "notify_switchboard.data" not in hass_storage


async def test_diagnostics_redacts_message_bodies(hass: HomeAssistant) -> None:
    """Message bodies never leave the house in a diagnostics dump."""
    async_mock_service(hass, "notify", "mobile_app_alice")
    hass.states.async_set("person.alice", "home")
    entry = await install(
        hass,
        [make_person("person.alice", ["mobile_app_alice"])],
        [make_target("leak")],
        "leak",
    )
    await hass.services.async_call(
        "notify", "switchboard_leak", {"message": "secret address"}, blocking=True
    )
    await hass.async_block_till_done()

    diagnostics = await async_get_config_entry_diagnostics(hass, entry)
    assert diagnostics["entry"]["version"] == 1
    assert diagnostics["counters"]["routed_today"] == 1
    assert diagnostics["last_decisions"][0]["message"] == "**REDACTED**"


async def test_diagnostics_redacts_default_data_values_but_keeps_the_keys(
    hass: HomeAssistant,
) -> None:
    """`default_data` is user content; its shape stays, its values do not."""
    async_mock_service(hass, "notify", "mobile_app_alice")
    hass.states.async_set("person.alice", "home")
    entry = await install(
        hass,
        [make_person("person.alice", ["mobile_app_alice"])],
        [
            make_target(
                "leak",
                default_data={"channel": "Alarms", "url": "/lovelace/water"},
            ),
            make_target("garage", default_data={}),
        ],
        "leak",
    )

    diagnostics = await async_get_config_entry_diagnostics(hass, entry)
    rows = {row["slug"]: row for row in diagnostics["entry"]["options"]["targets"]}
    assert rows["leak"]["default_data"] == {
        "channel": "**REDACTED**",
        "url": "**REDACTED**",
    }
    assert rows["garage"]["default_data"] == {}
    # The rest of the row is untouched: a dump has to stay readable.
    assert rows["leak"]["audience"] == ["person.alice"]
    # And the live options are not mutated by the dump.
    assert entry.options["targets"][0]["default_data"]["channel"] == "Alarms"


async def test_snoozes_expire_and_feed_the_person_sensor(
    hass: HomeAssistant, freezer: Any
) -> None:
    """`sensor.<person>_active_snoozes` follows the stored snoozes."""
    async_mock_service(hass, "notify", "mobile_app_alice")
    hass.states.async_set("person.alice", "home")
    await install(
        hass,
        [make_person("person.alice", ["mobile_app_alice"])],
        [make_target("leak", snooze_minutes=[30])],
        "leak",
    )

    hass.bus.async_fire(
        "mobile_app_notification_action",
        {"action": "switchboard:snooze:leak:30"},
    )
    await hass.async_block_till_done()
    assert hass.states.get("sensor.alice_active_snoozes").state == "1"

    freezer.tick(timedelta(minutes=31))
    await hass.services.async_call(
        "notify", "switchboard_leak", {"message": "m"}, blocking=True
    )
    await hass.async_block_till_done()
    assert hass.states.get("sensor.alice_active_snoozes").state == "0"


async def test_forged_action_is_ignored(hass: HomeAssistant) -> None:
    """An action id that is not ours never reaches the routing table."""
    async_mock_service(hass, "notify", "mobile_app_alice")
    hass.states.async_set("person.alice", "home")
    entry = await install(
        hass,
        [make_person("person.alice", ["mobile_app_alice"])],
        [make_target("leak", snooze_minutes=[30])],
        "leak",
    )
    for action in ("something_else", "switchboard:snooze:leak", "switchboard:ack"):
        hass.bus.async_fire("mobile_app_notification_action", {"action": action})
    await hass.async_block_till_done()
    assert entry.runtime_data.switchboard.store.snoozes == {}


async def test_silence_binary_sensor_follows_its_sources(
    hass: HomeAssistant,
) -> None:
    """`binary_sensor.<person>_silenced` recomputes when a source moves."""
    async_mock_service(hass, "notify", "mobile_app_alice")
    hass.states.async_set("person.alice", "home")
    hass.states.async_set("input_boolean.night", "off")
    await install(
        hass,
        [
            make_person(
                "person.alice",
                ["mobile_app_alice"],
                silence_entities=["input_boolean.night"],
            )
        ],
        [make_target("leak")],
        "leak",
    )
    assert hass.states.get("binary_sensor.alice_silenced").state == "off"

    hass.states.async_set("input_boolean.night", "on")
    await hass.async_block_till_done()
    assert hass.states.get("binary_sensor.alice_silenced").state == "on"


async def test_migration_is_a_no_op_at_version_1(hass: HomeAssistant) -> None:
    """`async_migrate_entry` exists and accepts the current schema."""
    entry = MockConfigEntry(domain=DOMAIN, version=1, minor_version=1, options={})
    entry.add_to_hass(hass)
    assert await async_migrate_entry(hass, entry) is True

    future = MockConfigEntry(domain=DOMAIN, version=2, minor_version=1, options={})
    future.add_to_hass(hass)
    assert await async_migrate_entry(hass, future) is False


@pytest.mark.parametrize(
    ("device_name", "expected"),
    [
        ("Alice Phone", "mobile_app_alice_phone"),
        # The whole string is slugified, exactly as core does it: a trailing
        # separator does not survive as `mobile_app_` + "".
        ("Alice's iPhone", "mobile_app_alice_s_iphone"),
        ("-", "mobile_app"),
        ("Téléphone d'Alice", "mobile_app_telephone_d_alice"),
    ],
)
def test_companion_service_name_matches_core(device_name: str, expected: str) -> None:
    """`slugify(f"mobile_app_{name}")`, like notify/legacy.py line 275."""
    assert companion_service_name(device_name) == expected


async def test_snooze_resolves_the_acting_person_from_the_context_user_id(
    hass: HomeAssistant,
) -> None:
    """`context.user_id` beats every other clue: only that person is snoozed.

    `mobile_app` re-fires the Companion action with
    `context=registration_context(config_entry.data)`
    (`homeassistant/components/mobile_app/webhook.py`), and a person exposes
    the user it is linked to as a `user_id` attribute
    (`homeassistant/components/person/const.py`).
    """
    async_mock_service(hass, "notify", "mobile_app_alice")
    async_mock_service(hass, "notify", "mobile_app_bob")
    hass.states.async_set("person.alice", "home", {"user_id": "user-alice"})
    hass.states.async_set("person.bob", "home", {"user_id": "user-bob"})

    entry = await install(
        hass,
        [
            make_person("person.alice", ["mobile_app_alice"]),
            make_person("person.bob", ["mobile_app_bob"]),
        ],
        [
            make_target(
                "leak", audience=["person.alice", "person.bob"], snooze_minutes=[30]
            )
        ],
        "leak",
    )

    hass.bus.async_fire(
        "mobile_app_notification_action",
        # No device_id at all: the user id is enough.
        {"action": "switchboard:snooze:leak:30"},
        context=Context(user_id="user-bob"),
    )
    await hass.async_block_till_done()

    assert list(entry.runtime_data.switchboard.store.snoozes) == [
        ("person.bob", "leak")
    ]


async def test_snooze_falls_back_when_no_person_matches_the_user_id(
    hass: HomeAssistant,
) -> None:
    """An unlinked user id resolves nothing and the audience is snoozed."""
    async_mock_service(hass, "notify", "mobile_app_alice")
    async_mock_service(hass, "notify", "mobile_app_bob")
    hass.states.async_set("person.alice", "home", {"user_id": "user-alice"})
    hass.states.async_set("person.bob", "home")

    entry = await install(
        hass,
        [
            make_person("person.alice", ["mobile_app_alice"]),
            make_person("person.bob", ["mobile_app_bob"]),
        ],
        [
            make_target(
                "leak", audience=["person.alice", "person.bob"], snooze_minutes=[30]
            )
        ],
        "leak",
    )

    hass.bus.async_fire(
        "mobile_app_notification_action",
        {"action": "switchboard:snooze:leak:30"},
        context=Context(user_id="nobody-here"),
    )
    await hass.async_block_till_done()

    assert sorted(entry.runtime_data.switchboard.store.snoozes) == [
        ("person.alice", "leak"),
        ("person.bob", "leak"),
    ]


async def test_snooze_resolves_the_acting_person_from_the_device_registry(
    hass: HomeAssistant,
) -> None:
    """A Companion `device_id` that resolves snoozes only that person."""
    async_mock_service(hass, "notify", "mobile_app_alice_phone")
    async_mock_service(hass, "notify", "mobile_app_bob")
    hass.states.async_set("person.alice", "home")
    hass.states.async_set("person.bob", "home")

    companion = MockConfigEntry(
        domain="mobile_app",
        entry_id="mobile_app_entry",
        data={"device_name": "Alice Phone", "device_id": "dev-1"},
    )
    companion.add_to_hass(hass)
    dr.async_get(hass).async_get_or_create(
        config_entry_id=companion.entry_id,
        identifiers={("mobile_app", "dev-1")},
        name="Alice Phone",
    )

    entry = await install(
        hass,
        [
            make_person("person.alice", ["mobile_app_alice_phone"]),
            make_person("person.bob", ["mobile_app_bob"]),
        ],
        [
            make_target(
                "leak", audience=["person.alice", "person.bob"], snooze_minutes=[30]
            )
        ],
        "leak",
    )

    hass.bus.async_fire(
        "mobile_app_notification_action",
        {"action": "switchboard:snooze:leak:30", "device_id": "dev-1"},
    )
    await hass.async_block_till_done()

    assert list(entry.runtime_data.switchboard.store.snoozes) == [
        ("person.alice", "leak")
    ]


async def test_snooze_falls_back_to_the_audience_for_an_unknown_device(
    hass: HomeAssistant,
) -> None:
    """The documented ambiguous case snoozes everybody the row names."""
    async_mock_service(hass, "notify", "mobile_app_alice")
    async_mock_service(hass, "notify", "mobile_app_bob")
    hass.states.async_set("person.alice", "home")
    hass.states.async_set("person.bob", "home")
    entry = await install(
        hass,
        [
            make_person("person.alice", ["mobile_app_alice"]),
            make_person("person.bob", ["mobile_app_bob"]),
        ],
        [
            make_target(
                "leak", audience=["person.alice", "person.bob"], snooze_minutes=[30]
            )
        ],
        "leak",
    )

    hass.bus.async_fire(
        "mobile_app_notification_action",
        {"action": "switchboard:snooze:leak:30", "device_id": "never-registered"},
    )
    await hass.async_block_till_done()

    assert sorted(entry.runtime_data.switchboard.store.snoozes) == [
        ("person.alice", "leak"),
        ("person.bob", "leak"),
    ]


async def test_snooze_on_a_row_nobody_listens_to_is_ignored(
    hass: HomeAssistant,
) -> None:
    """With no known person in the audience there is nothing to snooze."""
    async_mock_service(hass, "notify", "mobile_app_alice")
    entry = await install(
        hass,
        [make_person("person.alice", ["mobile_app_alice"])],
        [make_target("leak", audience=["person.ghost"], snooze_minutes=[30])],
        "leak",
    )
    hass.bus.async_fire(
        "mobile_app_notification_action",
        {"action": "switchboard:snooze:leak:30"},
    )
    await hass.async_block_till_done()
    assert entry.runtime_data.switchboard.store.snoozes == {}


async def test_unknown_target_repair_is_raised_once(hass: HomeAssistant) -> None:
    """Two calls to the same ghost target raise one issue, and count twice."""
    async_mock_service(hass, "notify", "mobile_app_alice")
    hass.states.async_set("person.alice", "home")
    await install(
        hass,
        [make_person("person.alice", ["mobile_app_alice"])],
        [make_target("leak")],
        "leak",
    )
    for _ in range(2):
        await hass.services.async_call(
            "notify",
            "switchboard",
            {"message": "ghost", "target": ["nope"]},
            blocking=True,
        )
        await hass.async_block_till_done()

    issues = [
        issue for issue in ir.async_get(hass).issues.values() if issue.domain == DOMAIN
    ]
    assert len(issues) == 1
    dropped = hass.states.get("sensor.switchboard_dropped_today")
    assert dropped.state == "2"
    assert dropped.attributes["reasons"] == {"unknown_target": 2}


async def test_a_failing_output_is_logged_and_counted_as_a_drop(
    hass: HomeAssistant,
) -> None:
    """An unexpected exception from an output cannot break the router.

    It is also not a delivery: nobody received anything, so it is a
    `delivery_failed` drop rather than a routed notification.
    """
    async_mock_service(
        hass, "notify", "mobile_app_alice", raise_exception=RuntimeError("boom")
    )
    hass.states.async_set("person.alice", "home")
    entry = await install(
        hass,
        [make_person("person.alice", ["mobile_app_alice"])],
        [make_target("leak")],
        "leak",
    )
    await hass.services.async_call(
        "notify", "switchboard_leak", {"message": "m"}, blocking=True
    )
    await hass.async_block_till_done()

    assert hass.states.get("sensor.switchboard_routed_today").state == "0"
    dropped = hass.states.get("sensor.switchboard_dropped_today")
    assert dropped.state == "1"
    assert dropped.attributes["reasons"] == {"delivery_failed": 1}
    assert entry.runtime_data.switchboard.failing_outputs == {"mobile_app_alice": 1}


async def test_an_output_that_keeps_raising_raises_the_repair(
    hass: HomeAssistant,
) -> None:
    """An output that exists but always fails is repaired like a missing one."""
    async_mock_service(
        hass,
        "notify",
        "mobile_app_alice",
        raise_exception=HomeAssistantError("push refused"),
    )
    hass.states.async_set("person.alice", "home")
    entry = await install(
        hass,
        [make_person("person.alice", ["mobile_app_alice"])],
        [make_target("leak")],
        "leak",
    )
    registry = ir.async_get(hass)

    for _ in range(3):
        await hass.services.async_call(
            "notify", "switchboard_leak", {"message": "m"}, blocking=True
        )
        await hass.async_block_till_done()
    assert (DOMAIN, "missing_output_mobile_app_alice") not in registry.issues

    await hass.services.async_call(
        "notify", "switchboard_leak", {"message": "m"}, blocking=True
    )
    await hass.async_block_till_done()
    assert (DOMAIN, "missing_output_mobile_app_alice") in registry.issues
    assert entry.runtime_data.switchboard.failing_outputs["mobile_app_alice"] == 4


async def test_a_successful_call_clears_the_failure_counter(
    hass: HomeAssistant,
) -> None:
    """One delivery that works resets the consecutive-failure count."""
    hass.states.async_set("person.alice", "home")
    entry = await install(
        hass,
        [make_person("person.alice", ["mobile_app_flaky"])],
        [make_target("leak")],
        "leak",
    )
    await hass.services.async_call(
        "notify", "switchboard_leak", {"message": "m"}, blocking=True
    )
    await hass.async_block_till_done()
    assert entry.runtime_data.switchboard.failing_outputs == {"mobile_app_flaky": 1}

    async_mock_service(hass, "notify", "mobile_app_flaky")
    await hass.services.async_call(
        "notify", "switchboard_leak", {"message": "m"}, blocking=True
    )
    await hass.async_block_till_done()
    assert entry.runtime_data.switchboard.failing_outputs == {}


async def test_one_working_output_out_of_two_is_still_a_delivery(
    hass: HomeAssistant,
) -> None:
    """`delivered` is False only when *every* output of a person failed."""
    async_mock_service(
        hass, "notify", "mobile_app_alice", raise_exception=HomeAssistantError("boom")
    )
    ok = async_mock_service(hass, "notify", "telegram_family")
    hass.states.async_set("person.alice", "home")
    await install(
        hass,
        [make_person("person.alice", ["mobile_app_alice", "telegram_family"])],
        [make_target("leak")],
        "leak",
    )
    await hass.services.async_call(
        "notify", "switchboard_leak", {"message": "m"}, blocking=True
    )
    await hass.async_block_till_done()

    assert len(ok) == 1
    assert hass.states.get("sensor.switchboard_routed_today").state == "1"
    assert hass.states.get("sensor.switchboard_dropped_today").state == "0"


# ---------------------------------------------------------------------------
# M8: the wake time is a prediction, not a promise
# ---------------------------------------------------------------------------


async def test_a_deferral_is_kept_when_the_person_is_still_silenced_at_wake_time(
    hass: HomeAssistant, hass_storage: dict, freezer: Any
) -> None:
    """The night schedule ran late: the queue must not be pushed at a sleeper.

    Before this, `_async_flush_deferrals` trusted the timer: whatever was queued
    went out at `wake_time` even if the person's own silence entity was still
    `on`, which is exactly the notification the deferral existed to avoid.
    """
    await hass.config.async_set_time_zone("Europe/Paris")
    freezer.move_to(datetime(2026, 9, 10, 21, 30, tzinfo=dt_util.UTC))  # 23:30 Paris

    calls = async_mock_service(hass, "notify", "mobile_app_alice")
    hass.states.async_set("person.alice", "home")
    hass.states.async_set("input_boolean.night", "on")
    entry = await install(
        hass,
        [
            make_person(
                "person.alice",
                ["mobile_app_alice"],
                silence_entities=["input_boolean.night"],
                wake_time="07:00:00",
            )
        ],
        [make_target("leak")],
        "leak",
    )
    await hass.services.async_call(
        "notify", "switchboard_leak", {"message": "night"}, blocking=True
    )
    await hass.async_block_till_done()
    assert len(entry.runtime_data.switchboard.store.deferrals) == 1

    # 07:05 Paris, and `input_boolean.night` is *still* on.
    freezer.move_to(datetime(2026, 9, 11, 5, 5, tzinfo=dt_util.UTC))
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done()

    assert calls == []
    assert len(entry.runtime_data.switchboard.store.deferrals) == 1

    # The silence lifts; the re-armed timer delivers at the next wake time.
    hass.states.async_set("input_boolean.night", "off")
    freezer.move_to(datetime(2026, 9, 12, 5, 5, tzinfo=dt_util.UTC))  # 07:05, next day
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done()

    assert [call.data["message"] for call in calls] == ["night"]
    assert entry.runtime_data.switchboard.store.deferrals == {}


async def test_a_deferral_held_by_a_temporary_silence_is_re_armed_at_its_end(
    hass: HomeAssistant, hass_storage: dict, freezer: Any
) -> None:
    """ "The next end" is the temporary silence's, when that is sooner."""
    await hass.config.async_set_time_zone("Europe/Paris")
    freezer.move_to(datetime(2026, 9, 10, 21, 30, tzinfo=dt_util.UTC))  # 23:30 Paris

    calls = async_mock_service(hass, "notify", "mobile_app_alice")
    hass.states.async_set("person.alice", "home")
    hass.states.async_set("input_boolean.night", "on")
    entry = await install(
        hass,
        [
            make_person(
                "person.alice",
                ["mobile_app_alice"],
                silence_entities=["input_boolean.night"],
                wake_time="07:00:00",
            )
        ],
        [make_target("leak")],
        "leak",
    )
    await hass.services.async_call(
        "notify", "switchboard_leak", {"message": "night"}, blocking=True
    )
    await hass.async_block_till_done()

    # At 07:05 the schedule is over but a 30-minute silence, asked for in the
    # small hours, still runs. The flush keeps the message and re-arms for the
    # end of that silence rather than for tomorrow morning.
    freezer.move_to(datetime(2026, 9, 11, 5, 0, tzinfo=dt_util.UTC))  # 07:00 Paris
    await hass.services.async_call(
        DOMAIN, "silence", {"person": "person.alice", "minutes": 30}, blocking=True
    )
    hass.states.async_set("input_boolean.night", "off")
    freezer.move_to(datetime(2026, 9, 11, 5, 5, tzinfo=dt_util.UTC))  # 07:05 Paris
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done()

    assert calls == []
    assert len(entry.runtime_data.switchboard.store.deferrals) == 1

    # 07:31 Paris: the temporary silence has lifted, well before the next 07:00.
    freezer.move_to(datetime(2026, 9, 11, 5, 31, tzinfo=dt_util.UTC))
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done()

    assert [call.data["message"] for call in calls] == ["night"]


async def test_a_critical_deferral_is_delivered_even_if_the_silence_holds(
    hass: HomeAssistant, hass_storage: dict, freezer: Any
) -> None:
    """`critical` bypasses silence everywhere else, so it bypasses the hold too."""
    await hass.config.async_set_time_zone("Europe/Paris")
    freezer.move_to(datetime(2026, 9, 10, 21, 30, tzinfo=dt_util.UTC))  # 23:30 Paris

    calls = async_mock_service(hass, "notify", "mobile_app_alice")
    hass.states.async_set("person.alice", "home")
    hass.states.async_set("input_boolean.night", "on")
    entry = await install(
        hass,
        [
            make_person(
                "person.alice",
                ["mobile_app_alice"],
                silence_entities=["input_boolean.night"],
                wake_time="07:00:00",
            )
        ],
        [make_target("leak")],
        "leak",
    )
    # A `critical` message is never silenced in the first place, so the
    # deferral is planted directly: this pins the flush rule, not the router's.
    switchboard = entry.runtime_data.switchboard
    switchboard.store.deferrals[("person.alice", "leak", "")] = DeferredMessage(
        person="person.alice",
        slug="leak",
        tag="",
        message="critical",
        priority="critical",
        queued_at=dt_util.utcnow(),
    )

    freezer.move_to(datetime(2026, 9, 11, 5, 5, tzinfo=dt_util.UTC))  # 07:05 Paris
    await switchboard._async_flush_deferrals("person.alice")
    await hass.async_block_till_done()

    assert [call.data["message"] for call in calls] == ["critical"]
    assert switchboard.store.deferrals == {}


# ---------------------------------------------------------------------------
# Sprint 3: shutdown, fan-out and the person_without_user_id repair
# ---------------------------------------------------------------------------


async def test_stopping_home_assistant_detaches_every_listener(
    hass: HomeAssistant,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Regression: a config entry is not unloaded when Home Assistant stops.

    Nothing else runs `async_shutdown`, so a `_async_stop_event` that only
    cancelled the deferral timers left the midnight counter reset armed by
    `async_track_time_change` (and the bus/state listeners) attached to a loop
    that is about to go away. Under load that surfaced as an intermittent
    "Lingering timer after test ... Switchboard._async_reset_counters" in the
    config-flow tests, whose options steps reload the entry.

    Second regression, on the same path: the `async_listen_once` unsub must
    not be detached twice. Core's `_OneTimeListener.__call__`
    (`homeassistant/core.py`, lines 1470-1478) removes the listener before it
    runs the callback, so a `_stop_unsub` still held in `_unsubs` is called a
    second time by `async_shutdown` and `EventBus._async_remove_listener`
    (`homeassistant/core.py`, lines 1823-1843) logs "Unable to remove unknown
    job listener" with a `ValueError` traceback -- an ERROR on *every* real
    Home Assistant shutdown.
    """
    entry = await install(
        hass,
        [make_person("person.alice", ["mobile_app_alice"], wake_time="07:00:00")],
        [make_target("leak")],
        "leak",
    )
    switchboard = entry.runtime_data.switchboard
    assert switchboard._unsubs

    caplog.clear()
    hass.bus.async_fire(EVENT_HOMEASSISTANT_STOP)
    await hass.async_block_till_done()

    assert "Unable to remove unknown job listener" not in caplog.text
    assert switchboard._unsubs == []
    assert switchboard._deferral_unsubs == {}
    assert switchboard._silence_unsubs == {}
    assert switchboard._stop_unsub is None


async def test_unloading_the_entry_detaches_the_stop_listener_once(
    hass: HomeAssistant,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The other order: unload first, then shut Home Assistant down.

    `async_shutdown` runs on the unload path, so it is the one that has to
    detach the stop listener; firing `EVENT_HOMEASSISTANT_STOP` afterwards
    must then reach nothing at all.
    """
    entry = await install(
        hass,
        [make_person("person.alice", ["mobile_app_alice"], wake_time="07:00:00")],
        [make_target("leak")],
        "leak",
    )
    switchboard = entry.runtime_data.switchboard

    caplog.clear()
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()

    hass.bus.async_fire(EVENT_HOMEASSISTANT_STOP)
    await hass.async_block_till_done()

    assert "Unable to remove unknown job listener" not in caplog.text
    assert switchboard._stop_unsub is None


async def test_the_output_timeout_is_thirty_seconds(hass: HomeAssistant) -> None:
    """ADR-0017 §3 fixes the value, not only the name."""
    assert OUTPUT_TIMEOUT_SECONDS == 30


async def test_a_recursive_output_is_refused_at_runtime(hass: HomeAssistant) -> None:
    """Contract §"Output": an output pointing back at the router never runs.

    The config flow refuses it too, but a hand-edited options file reaches the
    dispatcher, and there the refusal has to be synchronous -- calling it would
    recurse rather than fail.
    """
    entry = await install(
        hass,
        [make_person("person.alice", ["mobile_app_alice"])],
        [make_target("leak")],
        "leak",
    )
    switchboard = entry.runtime_data.switchboard

    assert (
        await switchboard._async_call_output(
            "switchboard_leak", "Water", None, {}, "leak"
        )
        is False
    )


async def test_the_repair_is_deleted_for_a_person_who_left_the_table(
    hass: HomeAssistant,
) -> None:
    """A `repairs` issue outlives its process; a person removed from the table
    would otherwise keep a warning nobody can act on.
    """
    async_mock_service(hass, "notify", "mobile_app_alice")
    async_mock_service(hass, "notify", "mobile_app_bob")
    hass.states.async_set("person.alice", "home")
    hass.states.async_set("person.bob", "home")

    entry = await install(
        hass,
        [
            make_person("person.alice", ["mobile_app_alice"]),
            make_person("person.bob", ["mobile_app_bob"]),
        ],
        [
            make_target(
                "leak", audience=["person.alice", "person.bob"], snooze_minutes=[15]
            )
        ],
        "leak",
    )
    registry = ir.async_get(hass)
    raised = {
        issue_id
        for (domain, issue_id), issue in registry.issues.items()
        if domain == DOMAIN and issue.translation_key == "person_without_user_id"
    }
    assert raised == {
        "person_without_user_id_person.alice",
        "person_without_user_id_person.bob",
    }

    hass.config_entries.async_update_entry(
        entry,
        options={
            "persons": [make_person("person.alice", ["mobile_app_alice"])],
            "targets": [
                make_target("leak", audience=["person.alice"], snooze_minutes=[15])
            ],
            "default_target": "leak",
        },
    )
    await hass.async_block_till_done()

    remaining = {
        issue_id
        for (domain, issue_id), issue in registry.issues.items()
        if domain == DOMAIN and issue.translation_key == "person_without_user_id"
    }
    assert remaining == {"person_without_user_id_person.alice"}


async def test_a_person_with_no_state_at_all_counts_as_unlinked(
    hass: HomeAssistant,
) -> None:
    """`person.*` missing entirely: there is no `user_id` to resolve either."""
    entry = await install(
        hass,
        [make_person("person.ghost", ["mobile_app_ghost"])],
        [make_target("leak", audience=["person.ghost"], allow_acknowledge=True)],
        "leak",
    )
    switchboard = entry.runtime_data.switchboard

    assert switchboard._person_user_id("person.ghost") is None
    assert switchboard._persons_needing_a_user_id() == ["person.ghost"]
