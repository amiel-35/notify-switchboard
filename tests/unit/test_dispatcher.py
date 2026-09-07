"""Tests for the side-effecting half of the router."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, time, timedelta
from typing import Any
from unittest.mock import patch
from zoneinfo import ZoneInfo

import homeassistant.helpers.device_registry as dr
import homeassistant.helpers.entity_registry as er
import homeassistant.helpers.issue_registry as ir
import homeassistant.util.dt as dt_util
import pytest
from homeassistant.const import EVENT_HOMEASSISTANT_STOP
from homeassistant.core import Context, HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
    async_mock_service,
)

from custom_components.notify_switchboard import async_migrate_entry
from custom_components.notify_switchboard.const import DOMAIN, STORAGE_KEY
from custom_components.notify_switchboard.diagnostics import (
    _redact_options,
    async_get_config_entry_diagnostics,
)
from custom_components.notify_switchboard.dispatcher import (
    OUTPUT_TIMEOUT_SECONDS,
    Switchboard,
    companion_service_name,
    next_wake_time,
)
from custom_components.notify_switchboard.store import DeferredMessage, Episode


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


async def test_non_companion_output_gets_no_router_keys(hass: HomeAssistant) -> None:
    """Only `mobile_app_*` outputs receive the keys the router adds itself."""
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
    # ADR-0019 §6, amendment 2026-09-07 (2): the default tag is a router key
    # like the other two, so it stops at the outputs that read a tag.
    assert "tag" not in data


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

    # The `→ idle` transition also pushes a `clear_notification` to the
    # Companion output the episode reached (ADR-0019 §6, amendment (a)): it is
    # not a message, so it is filtered out here.
    assert [
        call.data["message"]
        for call in calls
        if call.data["message"] != "clear_notification"
    ] == [
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
    # Re-saved at the current minor version: the same load also ran the minor
    # 3 step, which only adds an empty `silences` list, and the minor 4 step,
    # which only adds an empty `episodes` list -- an upgrade must not invent
    # an episode (ADR-0019 §5).
    assert hass_storage["notify_switchboard.data"]["minor_version"] == 4
    assert entry.runtime_data.switchboard.store.episodes == {}
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


def test_diagnostics_redaction_survives_options_without_a_target_list() -> None:
    """A dump must never raise on the shape of what it is dumping.

    `_redact_options` walks `options["targets"]`; a migration in flight, or an
    entry whose options were hand-written, can leave that key absent or not a
    list. The dump returns the options unchanged instead of failing.
    """
    assert _redact_options({"default_target": "leak"}) == {"default_target": "leak"}
    assert _redact_options({"targets": None}) == {"targets": None}
    # Non-dict rows in an otherwise valid list are passed through as-is.
    assert _redact_options({"targets": ["nope"]}) == {"targets": ["nope"]}


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


async def test_a_delivery_that_raises_is_counted_as_a_failed_delivery(
    hass: HomeAssistant,
) -> None:
    """The fan-out guard must account for the person it just lost.

    `_async_deliver_all` gathers with `return_exceptions=True`, so an
    unexpected error in one person's delivery does not abort the others -- but
    logging it and moving on made that person vanish from the counters
    entirely: neither routed nor dropped, with `sensor.switchboard_*` silently
    disagreeing with what actually went out.
    """
    async_mock_service(hass, "notify", "mobile_app_alice")
    ok = async_mock_service(hass, "notify", "mobile_app_bob")
    hass.states.async_set("person.alice", "home")
    hass.states.async_set("person.bob", "home")
    await install(
        hass,
        [
            make_person("person.alice", ["mobile_app_alice"]),
            make_person("person.bob", ["mobile_app_bob"]),
        ],
        [make_target("leak", audience=["person.alice", "person.bob"])],
        "leak",
    )

    original = Switchboard._async_deliver

    async def _boom(self, routed, message, title):
        if routed.person == "person.alice":
            raise RuntimeError("boom")
        # `_async_deliver` answers with the outputs it reached (v0.5,
        # ADR-0019 §5), so the stand-in has to hand that answer back.
        return await original(self, routed, message, title)

    with patch.object(Switchboard, "_async_deliver", _boom):
        await hass.services.async_call(
            "notify", "switchboard_leak", {"message": "m"}, blocking=True
        )
        await hass.async_block_till_done()

    # Bob still got his notification: one failure never aborts the fan-out.
    assert len(ok) == 1
    assert hass.states.get("sensor.switchboard_routed_today").state == "1"
    dropped = hass.states.get("sensor.switchboard_dropped_today")
    assert dropped.state == "1"
    assert dropped.attributes["reasons"] == {"delivery_failed": 1}


async def test_the_unknown_target_repair_is_cleared_once_the_row_exists(
    hass: HomeAssistant,
) -> None:
    """Adding the missing row is the fix; the warning has to go with it.

    The issue registry is persisted, so without this the `unknown_target`
    repair stayed on the user's dashboard forever after they created the row
    it asked for.
    """
    async_mock_service(hass, "notify", "mobile_app_alice")
    hass.states.async_set("person.alice", "home")
    entry = await install(
        hass,
        [make_person("person.alice", ["mobile_app_alice"])],
        [make_target("leak")],
        "leak",
    )
    await hass.services.async_call(
        "notify",
        "switchboard",
        {"message": "m", "target": ["fontaine"]},
        blocking=True,
    )
    await hass.async_block_till_done()

    registry = ir.async_get(hass)
    assert (DOMAIN, "unknown_target_fontaine") in registry.issues

    hass.config_entries.async_update_entry(
        entry,
        options={
            "persons": [make_person("person.alice", ["mobile_app_alice"])],
            "targets": [make_target("leak"), make_target("fontaine")],
            "default_target": "leak",
        },
    )
    await hass.async_block_till_done()

    assert (DOMAIN, "unknown_target_fontaine") not in registry.issues


async def test_an_unknown_target_still_unknown_keeps_its_repair(
    hass: HomeAssistant,
) -> None:
    """A reload that changed something else must not silence the warning."""
    async_mock_service(hass, "notify", "mobile_app_alice")
    hass.states.async_set("person.alice", "home")
    entry = await install(
        hass,
        [make_person("person.alice", ["mobile_app_alice"])],
        [make_target("leak")],
        "leak",
    )
    await hass.services.async_call(
        "notify",
        "switchboard",
        {"message": "m", "target": ["fontaine"]},
        blocking=True,
    )
    await hass.async_block_till_done()

    hass.config_entries.async_update_entry(
        entry,
        options={
            "persons": [make_person("person.alice", ["mobile_app_alice"])],
            "targets": [make_target("leak"), make_target("porte")],
            "default_target": "leak",
        },
    )
    await hass.async_block_till_done()

    assert (DOMAIN, "unknown_target_fontaine") in ir.async_get(hass).issues


async def test_the_missing_output_repair_is_cleared_when_it_answers(
    hass: HomeAssistant,
) -> None:
    """An output that delivers again is not missing any more."""
    hass.states.async_set("person.alice", "home")
    await install(
        hass,
        [make_person("person.alice", ["mobile_app_ghost"])],
        [make_target("leak")],
        "leak",
    )
    registry = ir.async_get(hass)
    for _ in range(4):
        await hass.services.async_call(
            "notify", "switchboard_leak", {"message": "m"}, blocking=True
        )
        await hass.async_block_till_done()
    assert (DOMAIN, "missing_output_mobile_app_ghost") in registry.issues

    async_mock_service(hass, "notify", "mobile_app_ghost")
    await hass.services.async_call(
        "notify", "switchboard_leak", {"message": "m"}, blocking=True
    )
    await hass.async_block_till_done()

    assert (DOMAIN, "missing_output_mobile_app_ghost") not in registry.issues


async def test_the_missing_output_repair_is_cleared_after_a_reload(
    hass: HomeAssistant,
) -> None:
    """The repair outlives the process that raised it; the fix must too.

    The issue registry is persisted (`issue_registry.async_schedule_save`)
    while `failing_outputs` is in-memory. After a restart -- a reload here --
    the counter is empty, so a success that only deletes the issue when the
    counter had crossed the threshold leaves the repair on screen for good,
    for an output that works.
    """
    hass.states.async_set("person.alice", "home")
    entry = await install(
        hass,
        [make_person("person.alice", ["mobile_app_ghost"])],
        [make_target("leak")],
        "leak",
    )
    registry = ir.async_get(hass)
    for _ in range(4):
        await hass.services.async_call(
            "notify", "switchboard_leak", {"message": "m"}, blocking=True
        )
        await hass.async_block_till_done()
    assert (DOMAIN, "missing_output_mobile_app_ghost") in registry.issues

    # The output is still configured, so setup does not clear the repair: only
    # a successful call can say it is wrong.
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert (DOMAIN, "missing_output_mobile_app_ghost") in registry.issues
    assert entry.runtime_data.switchboard.failing_outputs == {}

    async_mock_service(hass, "notify", "mobile_app_ghost")
    await hass.services.async_call(
        "notify", "switchboard_leak", {"message": "m"}, blocking=True
    )
    await hass.async_block_till_done()

    assert (DOMAIN, "missing_output_mobile_app_ghost") not in registry.issues


async def test_the_missing_output_repair_is_cleared_when_it_is_removed(
    hass: HomeAssistant,
) -> None:
    """Dropping the dead output from the person's row also fixes the cause."""
    async_mock_service(hass, "notify", "mobile_app_alice")
    hass.states.async_set("person.alice", "home")
    entry = await install(
        hass,
        [make_person("person.alice", ["mobile_app_ghost"])],
        [make_target("leak")],
        "leak",
    )
    registry = ir.async_get(hass)
    for _ in range(4):
        await hass.services.async_call(
            "notify", "switchboard_leak", {"message": "m"}, blocking=True
        )
        await hass.async_block_till_done()
    assert (DOMAIN, "missing_output_mobile_app_ghost") in registry.issues

    hass.config_entries.async_update_entry(
        entry,
        options={
            "persons": [make_person("person.alice", ["mobile_app_alice"])],
            "targets": [make_target("leak")],
            "default_target": "leak",
        },
    )
    await hass.async_block_till_done()

    assert (DOMAIN, "missing_output_mobile_app_ghost") not in registry.issues


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
    # `high` has no time-to-live (v0.5, ADR-0019 §1), so what this test
    # observes two days later is the silence rule of ADR-0016 and not the
    # 720 min a `normal` message would have run out of in between.
    await hass.services.async_call(
        "notify",
        "switchboard_leak",
        {"message": "night", "data": {"priority": "high"}},
        blocking=True,
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


async def test_unsilence_flushes_the_queue_that_silence_alone_was_holding(
    hass: HomeAssistant, hass_storage: dict, freezer: Any
) -> None:
    """Lifting the silence early must release the queue early too.

    The sibling above leaves the deferral armed on the temporary silence's own
    end. `unsilence` cancels that silence but used to leave the timer where it
    was, so a message whose only remaining holder had just been lifted still
    waited for an expiry that no longer meant anything -- the very wait
    ADR-0019 §4 removed for a configured silence going `off` early.
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

    # 07:00 Paris: the night is over but half an hour of quiet, asked for in
    # the small hours, holds the message on its own.
    freezer.move_to(datetime(2026, 9, 11, 5, 0, tzinfo=dt_util.UTC))
    await hass.services.async_call(
        DOMAIN, "silence", {"person": "person.alice", "minutes": 30}, blocking=True
    )
    hass.states.async_set("input_boolean.night", "off")
    freezer.move_to(datetime(2026, 9, 11, 5, 5, tzinfo=dt_util.UTC))  # 07:05 Paris
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done()

    switchboard = entry.runtime_data.switchboard
    assert calls == []
    assert len(switchboard.store.deferrals) == 1
    assert "person.alice" in switchboard._deferral_unsubs

    # 07:10 Paris: the quiet is lifted by hand, twenty minutes before its end.
    freezer.move_to(datetime(2026, 9, 11, 5, 10, tzinfo=dt_util.UTC))
    await hass.services.async_call(
        DOMAIN, "unsilence", {"person": "person.alice"}, blocking=True
    )
    await hass.async_block_till_done()

    assert [call.data["message"] for call in calls] == ["night"]
    assert switchboard.store.deferrals == {}
    assert switchboard._deferral_unsubs == {}


async def test_unsilence_keeps_a_queue_the_night_is_still_holding(
    hass: HomeAssistant, hass_storage: dict, freezer: Any
) -> None:
    """The other half of the symmetry: lifting one of two holders releases nothing.

    `_async_silence_changed` flushes only when the **last** silence lifts, and
    `unsilence` owes the queue the same reading: the night is still on, so the
    message stays queued and the timer goes back on what is left of the two
    candidates rather than on the expiry that has just been cancelled.
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

    freezer.move_to(datetime(2026, 9, 10, 21, 35, tzinfo=dt_util.UTC))  # 23:35 Paris
    await hass.services.async_call(
        DOMAIN, "silence", {"person": "person.alice", "minutes": 30}, blocking=True
    )
    freezer.move_to(datetime(2026, 9, 10, 21, 40, tzinfo=dt_util.UTC))  # 23:40 Paris
    await hass.services.async_call(
        DOMAIN, "unsilence", {"person": "person.alice"}, blocking=True
    )
    await hass.async_block_till_done()

    switchboard = entry.runtime_data.switchboard
    assert calls == []
    assert len(switchboard.store.deferrals) == 1
    assert "person.alice" in switchboard._deferral_unsubs

    # 00:10 Paris, past the end of the silence that was lifted: no timer of
    # that vintage is left to fire, and the night still holds the message.
    freezer.move_to(datetime(2026, 9, 10, 22, 10, tzinfo=dt_util.UTC))
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done()

    assert calls == []
    assert len(switchboard.store.deferrals) == 1

    # The night ends: the message is still there to be delivered.
    freezer.move_to(datetime(2026, 9, 11, 4, 0, tzinfo=dt_util.UTC))  # 06:00 Paris
    hass.states.async_set("input_boolean.night", "off")
    await hass.async_block_till_done()

    assert [call.data["message"] for call in calls] == ["night"]


async def test_a_silence_asked_for_after_the_deferral_was_armed_moves_the_timer(
    hass: HomeAssistant, hass_storage: dict, freezer: Any
) -> None:
    """`silence` owes the queue the re-arm `unsilence` already does.

    The deferral timer is armed on the earliest of the wake time and the end of
    a running temporary silence, but `notify_switchboard.silence` wrote the
    silence and armed nothing but its own expiry. A silence asked for *after*
    the deferral was armed therefore never became a candidate:

    * 23:30, the message is queued behind the night; the timer goes on 07:00;
    * 04:30, ninety minutes of quiet are asked for, ending at 06:00;
    * 05:00, the night ends -- the early flush of ADR-0019 §4 stands down,
      because the quiet still holds the message;
    * 06:00, that quiet expires, and nobody was waiting for it.

    The message then waited until 07:00, a full hour after the last thing that
    held it had gone.
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
    switchboard = entry.runtime_data.switchboard
    assert len(switchboard.store.deferrals) == 1

    # 04:30 Paris: ninety minutes of quiet, ending at 06:00 -- an hour before
    # the wake time the timer is currently armed on.
    freezer.move_to(datetime(2026, 9, 11, 2, 30, tzinfo=dt_util.UTC))
    await hass.services.async_call(
        DOMAIN, "silence", {"person": "person.alice", "minutes": 90}, blocking=True
    )
    await hass.async_block_till_done()

    # 05:00 Paris: the night ends, and the quiet is what keeps the message.
    freezer.move_to(datetime(2026, 9, 11, 3, 0, tzinfo=dt_util.UTC))
    hass.states.async_set("input_boolean.night", "off")
    await hass.async_block_till_done()
    assert calls == []
    assert len(switchboard.store.deferrals) == 1

    # 06:00 Paris: the quiet expires, and nothing else is holding the message.
    freezer.move_to(datetime(2026, 9, 11, 4, 0, tzinfo=dt_util.UTC))
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done()

    assert [call.data["message"] for call in calls] == ["night"]
    assert switchboard.store.deferrals == {}


async def test_a_silence_entity_that_disappears_releases_the_queue(
    hass: HomeAssistant, hass_storage: dict, freezer: Any
) -> None:
    """A renamed or deleted silence entity is a silence that has lifted.

    `_async_silence_changed` read a `new_state` of `None` as "nothing to say"
    and returned, which is the one reading that cannot be right: the entity the
    message waits behind has gone, so `has_configured_silence` will never see
    it `on` again and the early flush of ADR-0019 §4 will never be offered
    another chance to run. The queue waited for the wake time with nothing left
    holding it -- the same wait §4 exists to remove.
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
    switchboard = entry.runtime_data.switchboard
    assert calls == []
    assert len(switchboard.store.deferrals) == 1

    # 00:30 Paris: the helper is renamed, so the entity the queue waits behind
    # simply stops existing.
    freezer.move_to(datetime(2026, 9, 10, 22, 30, tzinfo=dt_util.UTC))
    hass.states.async_remove("input_boolean.night")
    await hass.async_block_till_done()

    assert [call.data["message"] for call in calls] == ["night"]
    assert switchboard.store.deferrals == {}


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


async def test_a_person_device_is_named_after_the_person(hass: HomeAssistant) -> None:
    """The virtual device carries the person's friendly name, not their slug.

    A `person.*` entity is renamed in the UI without its entity id following,
    so `person.alice` may well be "Alice Martin". Titling the object_id gave
    "Alice", which is a different person's name as far as the user is
    concerned -- and `has_entity_name` puts that word in front of every
    entity of the device.
    """
    hass.states.async_set("person.alice", "home", {"friendly_name": "Alice Martin"})
    entry = await install(
        hass,
        [make_person("person.alice", ["mobile_app_alice"])],
        [make_target("leak")],
        "leak",
    )

    device = dr.async_get(hass).async_get_device_by_identifier(
        (DOMAIN, f"{entry.entry_id}:person.alice"), entry.entry_id
    )
    assert device is not None
    assert device.name == "Alice Martin"


async def test_a_person_device_falls_back_to_the_object_id(
    hass: HomeAssistant,
) -> None:
    """No state yet (a restart races person setup): keep the old form."""
    entry = await install(
        hass,
        [make_person("person.jean_luc", ["mobile_app_jl"])],
        [make_target("leak", audience=["person.jean_luc"])],
        "leak",
    )

    device = dr.async_get(hass).async_get_device_by_identifier(
        (DOMAIN, f"{entry.entry_id}:person.jean_luc"), entry.entry_id
    )
    assert device is not None
    assert device.name == "Jean Luc"


async def test_a_person_device_ignores_a_state_without_a_friendly_name(
    hass: HomeAssistant,
) -> None:
    """`State.name` does not title the object_id; the fallback has to.

    `State.name` is `friendly_name or object_id.replace("_", " ")`
    (`homeassistant/core.py`, `State.name`) -- lower case. A person whose
    entity carries no friendly name must still be named "Jean Luc", not
    "jean luc", since `has_entity_name` prefixes every entity with it.
    """
    hass.states.async_set("person.jean_luc", "home")
    entry = await install(
        hass,
        [make_person("person.jean_luc", ["mobile_app_jl"])],
        [make_target("leak", audience=["person.jean_luc"])],
        "leak",
    )

    device = dr.async_get(hass).async_get_device_by_identifier(
        (DOMAIN, f"{entry.entry_id}:person.jean_luc"), entry.entry_id
    )
    assert device is not None
    assert device.name == "Jean Luc"


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
            "switchboard_leak", "Water", None, {}, "leak", router_tag=True
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


# ---------------------------------------------------------------------------
# v0.4 (ADR-0018): `explain`, the test message and the row that reaches somebody
# ---------------------------------------------------------------------------


async def test_target_for_person_prefers_the_default_target(
    hass: HomeAssistant,
) -> None:
    """ADR-0018 §6: the default target first, when it reaches that person."""
    async_mock_service(hass, "notify", "mobile_app_alice")
    hass.states.async_set("person.alice", "home")
    entry = await install(
        hass,
        [make_person("person.alice", ["mobile_app_alice"])],
        [
            make_target("garage", audience=["person.alice"]),
            make_target("leak", audience=["person.alice"]),
        ],
        "leak",
    )
    switchboard = entry.runtime_data.switchboard

    assert switchboard.target_for_person("person.alice") == "leak"
    assert switchboard.target_for_person("person.nobody") is None


async def test_explain_names_a_temporary_silence_rather_than_a_switch(
    hass: HomeAssistant,
) -> None:
    """Nothing is `on`, so the sentence has to say when the quiet hour lifts.

    Sending somebody to look for a silence entity that is `off` is exactly the
    failure `detail` exists to avoid (ADR-0018 §1).
    """
    async_mock_service(hass, "notify", "mobile_app_alice")
    hass.states.async_set("person.alice", "home")
    hass.states.async_set("input_boolean.night", "off")
    entry = await install(
        hass,
        [
            make_person(
                "person.alice",
                ["mobile_app_alice"],
                silence_entities=["input_boolean.night"],
            )
        ],
        [make_target("leak", audience=["person.alice"])],
        "leak",
    )
    await hass.services.async_call(
        DOMAIN,
        "silence",
        {"person": "person.alice", "minutes": 60},
        blocking=True,
    )
    await hass.async_block_till_done()

    answer = (await entry.runtime_data.switchboard.async_explain("leak"))["persons"][
        "person.alice"
    ]

    assert answer["decision"] == "dropped"
    assert answer["reason"] == "silenced"
    assert "input_boolean.night" not in answer["detail"], (
        "the configured switch is off; naming it would send the user to the wrong place"
    )
    assert "notify_switchboard.silence" in answer["detail"]


async def test_explain_answers_for_a_person_the_row_names_but_the_table_lacks(
    hass: HomeAssistant,
) -> None:
    """A hand-edited audience: the answer is `unknown_person`, not a crash."""
    async_mock_service(hass, "notify", "mobile_app_alice")
    hass.states.async_set("person.alice", "home")
    entry = await install(
        hass,
        [make_person("person.alice", ["mobile_app_alice"])],
        [make_target("leak", audience=["person.alice", "person.ghost"])],
        "leak",
    )

    answer = (await entry.runtime_data.switchboard.async_explain("leak"))["persons"][
        "person.ghost"
    ]

    assert answer["decision"] == "dropped"
    assert answer["reason"] == "unknown_person"
    assert answer["outputs"] == []
    assert answer["missing_outputs"] == []
    # `detail_unknown_person` is "The target {target} names {person}, who is
    # not in the table": a sentence that names nobody is the one thing it
    # exists to say, so assert the person it is about is actually in it.
    assert "person.ghost" in answer["detail"], (
        f"the sentence must name whom it is about; got {answer['detail']!r}"
    )
    assert "leak" in answer["detail"]


async def test_a_test_message_carries_the_public_tag_and_the_rows_title(
    hass: HomeAssistant,
) -> None:
    """The tag is contract v0.4; the title is the row's, like any caller's."""
    calls = async_mock_service(hass, "notify", "mobile_app_alice")
    hass.states.async_set("person.alice", "home")
    entry = await install(
        hass,
        [make_person("person.alice", ["mobile_app_alice"])],
        [make_target("leak", audience=["person.alice"], default_title="Switchboard")],
        "leak",
    )

    await entry.runtime_data.switchboard.async_send_test_message("leak")
    await hass.async_block_till_done()

    assert len(calls) == 1
    assert calls[0].data["title"] == "Switchboard"
    assert calls[0].data["data"]["tag"] == "switchboard-test"
    assert calls[0].data["message"]


async def test_the_alert_grace_timer_is_cancelled_when_the_entry_unloads(
    hass: HomeAssistant,
) -> None:
    """ADR-0018 §5: the `async_call_later` handle joins `_unsubs`.

    A config entry that leaves a live timer behind is exactly the class of bug
    the shutdown handling of ADR-0017 is about, and the acceptance suite's
    lingering-timer check would only catch it by accident.
    """
    async_mock_service(hass, "notify", "mobile_app_alice")
    hass.states.async_set("person.alice", "home")
    entry = await install(
        hass,
        [make_person("person.alice", ["mobile_app_alice"])],
        [make_target("leak", audience=["person.alice"], alert_entity="alert.gone")],
        "leak",
    )

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()

    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=90))
    await hass.async_block_till_done()

    assert not [
        issue
        for (domain, _issue_id), issue in ir.async_get(hass).issues.items()
        if domain == DOMAIN and issue.translation_key == "alert_entity_missing"
    ], "a cancelled grace check must not fire after the entry is gone"


# ---------------------------------------------------------------------------
# v0.5: episodes, the wake-time summary and the clears (ADR-0019)
# ---------------------------------------------------------------------------


def test_an_episode_survives_a_round_trip_through_the_store() -> None:
    """Sets are written as sorted lists and read back as sets."""
    episode = Episode(
        slug="leak",
        persons={"person.bob", "person.alice"},
        outputs={"persistent_notification", "mobile_app_alice"},
        tags={"switchboard-leak"},
        is_open=True,
    )
    raw = episode.as_dict()

    assert raw == {
        "slug": "leak",
        "persons": ["person.alice", "person.bob"],
        "outputs": ["mobile_app_alice", "persistent_notification"],
        "tags": ["switchboard-leak"],
        "open": True,
    }
    assert Episode.from_dict(raw) == episode


def test_an_episode_row_without_a_slug_is_dropped() -> None:
    """A hand-edited `.storage` file must not stop the entry from loading."""
    assert Episode.from_dict({"persons": ["person.alice"]}) is None
    assert Episode.from_dict({"slug": ""}) is None


async def test_an_unusable_episode_row_is_skipped_at_load(
    hass: HomeAssistant, hass_storage: dict
) -> None:
    """The same tolerance the snoozes and the deferrals already have."""
    hass_storage["notify_switchboard.data"] = {
        "version": 1,
        "minor_version": 4,
        "key": "notify_switchboard.data",
        "data": {
            "snoozes": [],
            "deferrals": [],
            "silences": [],
            "episodes": [{"persons": ["person.alice"]}, {"slug": "leak"}],
        },
    }
    async_mock_service(hass, "notify", "mobile_app_alice")
    hass.states.async_set("person.alice", "home")
    entry = await install(
        hass,
        [make_person("person.alice", ["mobile_app_alice"])],
        [make_target("leak")],
        "leak",
    )

    assert list(entry.runtime_data.switchboard.store.episodes) == ["leak"]


async def test_a_summary_whose_every_output_failed_is_a_drop_per_line(
    hass: HomeAssistant, hass_storage: dict, freezer: Any
) -> None:
    """A digest that reached nobody loses nothing: each line is accounted for.

    The single-message path already turns "every output failed" into a
    `delivery_failed` drop; a summary has to do the same once per line, or the
    figures would say two messages went out when none did.
    """
    await hass.config.async_set_time_zone("Europe/Paris")
    freezer.move_to(datetime(2026, 9, 10, 21, 30, tzinfo=dt_util.UTC))  # 23:30 Paris

    async_mock_service(
        hass, "notify", "mobile_app_alice", raise_exception=HomeAssistantError("nope")
    )
    hass.states.async_set("person.alice", "home")
    hass.states.async_set("input_boolean.night", "on")
    await install(
        hass,
        [
            make_person(
                "person.alice",
                ["mobile_app_alice"],
                silence_entities=["input_boolean.night"],
                wake_time="07:00:00",
            )
        ],
        [make_target("a"), make_target("b")],
        "a",
    )

    for slug in ("a", "b"):
        await hass.services.async_call(
            "notify", f"switchboard_{slug}", {"message": slug}, blocking=True
        )
        await hass.async_block_till_done()

    freezer.move_to(datetime(2026, 9, 11, 5, 5, tzinfo=dt_util.UTC))  # 07:05 Paris
    hass.states.async_set("input_boolean.night", "off")
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done()

    assert hass.states.get("sensor.switchboard_routed_today").state == "0"
    assert hass.states.get("sensor.switchboard_dropped_today").state == "2"


async def test_a_summary_records_the_episodes_that_contributed_a_line(
    hass: HomeAssistant, hass_storage: dict, freezer: Any
) -> None:
    """A digest is a delivery, so §5 records it into the episodes it summarises.

    ADR-0019 §6, amendment (b). Bob is silenced while the leak fires, so his
    message is deferred; at his wake time it goes out as one of two lines of a
    digest tagged `switchboard-summary`. He *was* told about the leak, so the
    `done` message must reach him (the `not_notified` filter of §5 must not
    drop him) and the digest's own tag must be among the tags cleared when the
    episode closes.
    """
    await hass.config.async_set_time_zone("Europe/Paris")
    freezer.move_to(datetime(2026, 9, 10, 21, 30, tzinfo=dt_util.UTC))  # 23:30 Paris

    calls = async_mock_service(hass, "notify", "mobile_app_bob")
    hass.states.async_set("person.bob", "home")
    hass.states.async_set("input_boolean.night", "on")
    await install(
        hass,
        [
            make_person(
                "person.bob",
                ["mobile_app_bob"],
                silence_entities=["input_boolean.night"],
                wake_time="07:00:00",
                summary=True,
            )
        ],
        [
            make_target(
                "leak",
                alert_entity="alert.leak",
                observer_mode=True,
                audience=["person.bob"],
            ),
            make_target("post", audience=["person.bob"]),
        ],
        "leak",
    )

    hass.states.async_set("alert.leak", "idle")
    await hass.async_block_till_done()
    hass.states.async_set("alert.leak", "on")  # opens the episode
    await hass.async_block_till_done()
    for slug in ("leak", "post"):
        await hass.services.async_call(
            "notify", f"switchboard_{slug}", {"message": slug}, blocking=True
        )
        await hass.async_block_till_done()
    assert calls == [], "silenced: nothing left yet"

    freezer.move_to(datetime(2026, 9, 11, 5, 5, tzinfo=dt_util.UTC))  # 07:05 Paris
    hass.states.async_set("input_boolean.night", "off")
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done()

    assert len(calls) == 1, "one digest, two lines"
    assert calls[0].data["data"]["tag"] == "switchboard-summary"

    hass.states.async_set("alert.leak", "idle")
    await hass.async_block_till_done()

    messages = [call.data["message"] for call in calls]
    assert "clear_notification" in messages, (
        "the summary's tag belongs to the episode, so it is cleared with it"
    )
    clears = [call for call in calls if call.data["message"] == "clear_notification"]
    assert {call.data["data"]["tag"] for call in clears} == {"switchboard-summary"}
    assert messages[1] != "clear_notification", (
        "Bob was told about the leak by the digest, so the done message "
        "reaches him before the clear"
    )


async def test_a_flush_pending_at_unload_neither_delivers_nor_re_arms(
    hass: HomeAssistant, hass_storage: dict, caplog: pytest.LogCaptureFixture
) -> None:
    """Unloading does not cancel a pending flush -- the flush stands down.

    `ConfigEntry.async_create_task` puts the task in `_tasks`, and
    `_async_process_on_unload` (`homeassistant/config_entries.py`) *awaits*
    those for up to ten seconds; only `_background_tasks` are cancelled. So a
    flush scheduled a moment before the entry unloads runs after
    `async_shutdown` has already detached every listener. It must not deliver
    on a dead entry, and above all it must not re-arm a deferral timer that
    `async_cancel_timers` can no longer cancel.
    """
    calls = async_mock_service(hass, "notify", "mobile_app_bob")
    hass.states.async_set("person.bob", "home")
    hass.states.async_set("input_boolean.night", "on")
    entry = await install(
        hass,
        [
            make_person(
                "person.bob",
                ["mobile_app_bob"],
                silence_entities=["input_boolean.night"],
                wake_time="07:00:00",
            )
        ],
        [make_target("leak", audience=["person.bob"])],
        "leak",
    )
    await hass.services.async_call(
        "notify", "switchboard_leak", {"message": "drip"}, blocking=True
    )
    await hass.async_block_till_done()
    assert calls == []

    switchboard = entry.runtime_data.switchboard
    # The early flush of §4 is scheduled synchronously by the state write, with
    # `eager_start=False`: the task exists but has not run when unload starts.
    hass.states.async_set("input_boolean.night", "off")
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()

    assert calls == [], "a dead entry delivers nothing"
    assert switchboard._deferral_unsubs == {}, (
        "re-arming here would leak a timer async_cancel_timers can never reach"
    )
    assert "Traceback" not in caplog.text

    # The same flag guards the two schedulers, for the other case core creates:
    # a flush that had *already begun* when the unload started, and that runs
    # its tail -- the re-arm and, through it, another flush -- afterwards.
    switchboard._async_schedule_deferral("person.bob")
    switchboard._async_schedule_flush("person.bob")
    await hass.async_block_till_done()
    assert switchboard._deferral_unsubs == {}
    assert calls == []


async def test_a_flush_running_at_unload_saves_before_the_outputs_not_after(
    hass: HomeAssistant, hass_storage: dict, caplog: pytest.LogCaptureFixture
) -> None:
    """A flush that outlives its entry writes the store *before* delivering.

    `OUTPUT_TIMEOUT_SECONDS` is thirty seconds and `_async_process_on_unload`
    (`homeassistant/config_entries.py`) gives an entry task ten: a flush stuck
    on one hanging output outlives the unload that waited for it. Its tail then
    runs on a released `Switchboard`, whose store a reloaded entry -- an
    options edit during a slow flush -- may already have replaced over the same
    file. `await self.store.async_save()` there writes a dead instance's state
    over the live one.

    The `_shutdown` flag covers the flush that has *not* begun and the re-arm;
    it did not cover this tail. So the durable half of a flush -- the deferrals
    leaving the queue -- is written as soon as they are popped, before the
    first output is awaited, and the tail stands down like the two schedulers
    already do.
    """
    began = asyncio.Event()
    release = asyncio.Event()
    delivered: list[ServiceCall] = []

    async def _hanging_output(call: ServiceCall) -> None:
        began.set()
        await release.wait()
        delivered.append(call)

    hass.services.async_register("notify", "mobile_app_bob", _hanging_output)
    hass.states.async_set("person.bob", "home")
    hass.states.async_set("input_boolean.night", "on")
    entry = await install(
        hass,
        [
            make_person(
                "person.bob",
                ["mobile_app_bob"],
                silence_entities=["input_boolean.night"],
                wake_time="07:00:00",
            )
        ],
        [make_target("leak", audience=["person.bob"])],
        "leak",
    )
    await hass.services.async_call(
        "notify", "switchboard_leak", {"message": "drip"}, blocking=True
    )
    await hass.async_block_till_done()
    assert delivered == []

    switchboard = entry.runtime_data.switchboard
    assert switchboard.store.deferrals != {}

    saves: list[None] = []
    original_save = switchboard.store.async_save

    async def _counting_save() -> None:
        saves.append(None)
        await original_save()

    switchboard.store.async_save = _counting_save  # type: ignore[method-assign]

    # The early flush of ADR-0019 §4 begins on the entry's own task, pops the
    # queue, and hangs on the output.
    hass.states.async_set("input_boolean.night", "off")
    async with asyncio.timeout(5):
        await began.wait()

    assert switchboard.store.deferrals == {}, "the flush has taken the queue"
    assert len(saves) == 1, (
        "the deferrals left the queue before the first output was awaited, so "
        "the store has to be written there -- not only after a delivery that "
        "may outlive the entry"
    )
    assert hass_storage[STORAGE_KEY]["data"]["deferrals"] == [], (
        "the file still queues a message this flush has already taken"
    )

    # Unload while the output hangs, then let it answer: the tail runs with
    # `_shutdown` set, which is exactly the window core leaves open.
    unloading = hass.async_create_task(hass.config_entries.async_unload(entry.entry_id))
    async with asyncio.timeout(5):
        while not switchboard._shutdown:
            await asyncio.sleep(0)

    saves.clear()
    release.set()
    assert await unloading
    await hass.async_block_till_done()

    assert delivered != [], "the output did answer; this is the tail, not a timeout"
    assert saves == [], (
        "the tail of a flush that outlived its entry must not write the store: "
        "a reloaded entry may already own the file"
    )
    assert switchboard._deferral_unsubs == {}
    assert [
        record for record in caplog.records if record.levelno >= logging.ERROR
    ] == []
    assert "Traceback" not in caplog.text


async def test_a_flush_writes_its_outcomes_to_the_decision_log(
    hass: HomeAssistant, hass_storage: dict, freezer: Any
) -> None:
    """A flush is a decision, so it shows up in the diagnostics like one.

    A message queued at 23:30 and delivered at 07:00 was decided twice: once
    when it was deferred, once when it was flushed. Only the first used to
    reach `decision_log`, so the dump a household reads to answer "why did
    this arrive / why did it not" stopped at the moment the night began.
    """
    await hass.config.async_set_time_zone("Europe/Paris")
    freezer.move_to(datetime(2026, 9, 10, 21, 30, tzinfo=dt_util.UTC))  # 23:30 Paris

    async_mock_service(hass, "notify", "mobile_app_bob")
    hass.states.async_set("person.bob", "home")
    hass.states.async_set("input_boolean.night", "on")
    entry = await install(
        hass,
        [
            make_person(
                "person.bob",
                ["mobile_app_bob"],
                silence_entities=["input_boolean.night"],
                wake_time="07:00:00",
            )
        ],
        [make_target("leak", audience=["person.bob"])],
        "leak",
    )
    await hass.services.async_call(
        "notify", "switchboard_leak", {"message": "drip"}, blocking=True
    )
    await hass.async_block_till_done()

    switchboard = entry.runtime_data.switchboard
    assert len(switchboard.decision_log) == 1, "the deferral itself"

    freezer.move_to(datetime(2026, 9, 11, 5, 5, tzinfo=dt_util.UTC))  # 07:05 Paris
    hass.states.async_set("input_boolean.night", "off")
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done()

    assert len(switchboard.decision_log) == 2
    flushed = switchboard.decision_log[-1]
    assert flushed["targets"] == ["leak"]
    assert flushed["message"] == "drip"
    assert flushed["routed"] == [{"person": "person.bob", "slug": "leak"}]
    assert flushed["dropped"] == []
    assert flushed["flush"] is True


async def test_a_flush_logs_and_counts_a_recursion_refusal_beside_a_delivery(
    hass: HomeAssistant, hass_storage: dict, freezer: Any
) -> None:
    """A person can be routed *and* refused, and the flush must say so.

    `route_person` returns a `recursion` refusal alongside the usable outputs
    when one of a person's outputs is a `notify.switchboard*` service. The live
    path counts both; the flush used to return on the first routed item and
    throw the refusal away, so a loop configured into the table was invisible
    exactly on the path that runs while nobody is watching.
    """
    await hass.config.async_set_time_zone("Europe/Paris")
    freezer.move_to(datetime(2026, 9, 10, 21, 30, tzinfo=dt_util.UTC))  # 23:30 Paris

    async_mock_service(hass, "notify", "mobile_app_bob")
    hass.states.async_set("person.bob", "home")
    hass.states.async_set("input_boolean.night", "on")
    entry = await install(
        hass,
        [
            make_person(
                "person.bob",
                ["mobile_app_bob", "switchboard_leak"],
                silence_entities=["input_boolean.night"],
                wake_time="07:00:00",
            )
        ],
        [make_target("leak", audience=["person.bob"])],
        "leak",
    )
    await hass.services.async_call(
        "notify", "switchboard_leak", {"message": "drip"}, blocking=True
    )
    await hass.async_block_till_done()

    switchboard = entry.runtime_data.switchboard
    before = switchboard.drop_reasons.get("recursion", 0)

    freezer.move_to(datetime(2026, 9, 11, 5, 5, tzinfo=dt_util.UTC))  # 07:05 Paris
    hass.states.async_set("input_boolean.night", "off")
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done()

    assert switchboard.drop_reasons.get("recursion", 0) == before + 1
    flushed = switchboard.decision_log[-1]
    assert flushed["routed"] == [{"person": "person.bob", "slug": "leak"}]
    assert flushed["dropped"] == [
        {"person": "person.bob", "slug": "leak", "reason": "recursion"}
    ]
    assert hass.states.get("sensor.switchboard_routed_today").state == "1"


async def test_a_failing_clear_is_logged_and_swallowed(
    hass: HomeAssistant, hass_storage: dict, caplog: pytest.LogCaptureFixture
) -> None:
    """Failing to tidy up is never worth raising at whoever ended the alert."""
    entry = await install(
        hass,
        [make_person("person.alice", ["mobile_app_alice"])],
        [make_target("leak")],
        "leak",
    )
    switchboard = entry.runtime_data.switchboard

    # Nothing registered: the clear is a no-op, not an error.
    await switchboard._async_clear_notification("mobile_app_alice", "switchboard-leak")
    assert "not registered" in caplog.text

    async_mock_service(
        hass, "notify", "mobile_app_alice", raise_exception=HomeAssistantError("gone")
    )
    await switchboard._async_clear_notification("mobile_app_alice", "switchboard-leak")
    assert "Could not clear" in caplog.text


async def test_the_clear_does_not_depend_on_what_backs_the_alert_state(
    hass: HomeAssistant, hass_storage: dict
) -> None:
    """Any observer row with an `alert_entity` is tidied up after.

    ADR-0019 §6, amendment (a): the closing sequence is narrowed to observer
    mode and to nothing else. In particular it does not ask what wrote the
    `alert.*` state -- the `alert` integration, a template, or, here, a test.
    The router observed that state and notified on the strength of it; refusing
    to tidy up on the same evidence would be incoherent.
    """
    calls = async_mock_service(hass, "notify", "mobile_app_alice")
    hass.states.async_set("person.alice", "home")
    await install(
        hass,
        [make_person("person.alice", ["mobile_app_alice"])],
        [make_target("observed", alert_entity="alert.observed", observer_mode=True)],
        "observed",
    )
    assert "alert" not in hass.config.components, (
        "the point of this test: the state below is synthetic"
    )

    hass.states.async_set("alert.observed", "idle")
    await hass.async_block_till_done()
    hass.states.async_set("alert.observed", "on")
    await hass.async_block_till_done()
    hass.states.async_set("alert.observed", "idle")
    await hass.async_block_till_done()

    clears = [call for call in calls if call.data["message"] == "clear_notification"]
    assert len(clears) == 1
    assert clears[0].data["data"]["tag"] == "switchboard-observed"


async def test_a_deferral_whose_person_left_the_table_is_dropped_not_delivered(
    hass: HomeAssistant, hass_storage: dict
) -> None:
    """The re-decision's last resort: nobody claims this message any more.

    `_redecide` reads the outcome `router.decide` produced for this person. A
    person the table no longer knows appears in neither list, so the message is
    dropped rather than delivered on the strength of a decision made hours ago.
    """
    entry = await install(
        hass,
        [make_person("person.alice", ["mobile_app_alice"])],
        [make_target("leak")],
        "leak",
    )
    switchboard = entry.runtime_data.switchboard
    deferral = DeferredMessage(
        person="person.mallory",
        slug="leak",
        tag="switchboard-leak",
        message="orphan",
    )

    routed, reason, refusals = switchboard._redecide(
        deferral, "person.mallory", switchboard.build_context()
    )

    assert routed is None
    assert reason is None
    assert refusals == ()


# ---------------------------------------------------------------------------
# v0.6 (ADR-0020 §3): an absent wake time means "until the silence ends"
# ---------------------------------------------------------------------------

NIGHT_UTC = datetime(2026, 9, 10, 21, 30, tzinfo=dt_util.UTC)  # 23:30 Paris
SEVEN_UTC = datetime(2026, 9, 11, 5, 0, tzinfo=dt_util.UTC)  # 07:00 Paris
SIX_UTC = datetime(2026, 9, 11, 4, 0, tzinfo=dt_util.UTC)  # 06:00 Paris
EIGHT_UTC = datetime(2026, 9, 11, 6, 0, tzinfo=dt_util.UTC)  # 08:00 Paris


async def _install_without_a_wake_time(
    hass: HomeAssistant, *silence_entities: str
) -> MockConfigEntry:
    """One person, no wake time, silenced by the given entities."""
    hass.states.async_set("person.alice", "home")
    return await install(
        hass,
        [
            make_person(
                "person.alice",
                ["mobile_app_alice"],
                silence_entities=list(silence_entities),
            )
        ],
        [make_target("leak")],
        "leak",
    )


async def test_a_silence_that_publishes_no_end_still_drops_without_a_wake_time(
    hass: HomeAssistant, hass_storage: dict
) -> None:
    """The boundary of §3: an `input_boolean` has no end to wait for."""
    calls = async_mock_service(hass, "notify", "mobile_app_alice")
    hass.states.async_set("input_boolean.night", "on")
    entry = await _install_without_a_wake_time(hass, "input_boolean.night")

    await hass.services.async_call(
        "notify", "switchboard_leak", {"message": "water"}, blocking=True
    )
    await hass.async_block_till_done()

    assert calls == []
    assert entry.runtime_data.switchboard.store.deferrals == {}
    assert "silenced" in entry.runtime_data.switchboard.drop_reasons


async def test_an_end_published_by_a_silence_that_is_off_does_not_count(
    hass: HomeAssistant, hass_storage: dict
) -> None:
    """A schedule that is `off` publishes the end of somebody else's night.

    Its `next_event` is then the *start* of the next block, which is exactly
    the instant a message must not be held until. Only an active silence has
    an end worth waiting for.
    """
    async_mock_service(hass, "notify", "mobile_app_alice")
    hass.states.async_set("input_boolean.night", "on")
    hass.states.async_set(
        "schedule.night", "off", {"next_event": SEVEN_UTC.isoformat()}
    )
    entry = await _install_without_a_wake_time(
        hass, "input_boolean.night", "schedule.night"
    )

    await hass.services.async_call(
        "notify", "switchboard_leak", {"message": "water"}, blocking=True
    )
    await hass.async_block_till_done()

    assert entry.runtime_data.switchboard.store.deferrals == {}


async def test_the_earliest_published_end_is_the_one_that_bounds_the_deferral(
    hass: HomeAssistant, hass_storage: dict, freezer: Any
) -> None:
    """Two schedules, and the fallback timer is armed on the sooner of them."""
    await hass.config.async_set_time_zone("Europe/Paris")
    freezer.move_to(NIGHT_UTC)
    calls = async_mock_service(hass, "notify", "mobile_app_alice")
    hass.states.async_set("schedule.night", "on", {"next_event": SEVEN_UTC.isoformat()})
    hass.states.async_set("schedule.quiet", "on", {"next_event": SIX_UTC.isoformat()})
    entry = await _install_without_a_wake_time(hass, "schedule.night", "schedule.quiet")

    await hass.services.async_call(
        "notify", "switchboard_leak", {"message": "night"}, blocking=True
    )
    await hass.async_block_till_done()
    assert len(entry.runtime_data.switchboard.store.deferrals) == 1

    # 06:00: the earlier schedule is what the timer was armed on. Both silences
    # are lifted here, so the flush that timer triggers delivers rather than
    # holding -- which is what proves the instant it fired at.
    freezer.move_to(SIX_UTC)
    hass.states.async_set("schedule.quiet", "off", {})
    hass.states.async_set("schedule.night", "off", {})
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done()

    assert [call.data["message"] for call in calls] == ["night"]


async def test_explain_reports_the_published_end_as_until(
    hass: HomeAssistant, hass_storage: dict, freezer: Any
) -> None:
    """`until` keeps its frozen meaning: a real instant, and this is the one."""
    await hass.config.async_set_time_zone("Europe/Paris")
    freezer.move_to(NIGHT_UTC)
    async_mock_service(hass, "notify", "mobile_app_alice")
    hass.states.async_set("schedule.night", "on", {"next_event": SEVEN_UTC.isoformat()})
    await _install_without_a_wake_time(hass, "schedule.night")

    response = await hass.services.async_call(
        DOMAIN,
        "explain",
        {"target": "leak"},
        blocking=True,
        return_response=True,
    )

    answer = response["persons"]["person.alice"]
    assert answer["decision"] == "deferred"
    assert dt_util.parse_datetime(answer["until"]) == SEVEN_UTC


async def test_a_queue_whose_silence_ended_while_ha_was_down_is_caught_up(
    hass: HomeAssistant, hass_storage: dict, freezer: Any
) -> None:
    """The setup catch-up covers a person with no wake time too (ADR-0020 §3).

    A message queued at 23:30 behind a schedule that has since gone `off` has
    nothing left holding it, and no wake-time timer will ever come round for
    it: without the catch-up it would sit in the store for good.
    """
    await hass.config.async_set_time_zone("Europe/Paris")
    freezer.move_to(SEVEN_UTC)
    calls = async_mock_service(hass, "notify", "mobile_app_alice")
    hass_storage[STORAGE_KEY] = {
        "version": 1,
        "minor_version": 4,
        "key": STORAGE_KEY,
        "data": {
            "snoozes": [],
            "silences": [],
            "episodes": [],
            "deferrals": [
                {
                    "person": "person.alice",
                    "slug": "leak",
                    "tag": "switchboard-leak",
                    "message": "queued at 23:30",
                    "priority": "normal",
                    "queued_at": NIGHT_UTC.isoformat(),
                }
            ],
        },
    }
    hass.states.async_set("schedule.night", "off", {})
    entry = await _install_without_a_wake_time(hass, "schedule.night")

    assert [call.data["message"] for call in calls] == ["queued at 23:30"]
    assert entry.runtime_data.switchboard.store.deferrals == {}


async def test_a_queue_whose_silence_is_still_running_is_not_caught_up(
    hass: HomeAssistant, hass_storage: dict, freezer: Any
) -> None:
    """The other half of the same rule: a night still running holds its queue."""
    await hass.config.async_set_time_zone("Europe/Paris")
    freezer.move_to(datetime(2026, 9, 11, 3, 0, tzinfo=dt_util.UTC))  # 05:00 Paris
    calls = async_mock_service(hass, "notify", "mobile_app_alice")
    hass_storage[STORAGE_KEY] = {
        "version": 1,
        "minor_version": 4,
        "key": STORAGE_KEY,
        "data": {
            "snoozes": [],
            "silences": [],
            "episodes": [],
            "deferrals": [
                {
                    "person": "person.alice",
                    "slug": "leak",
                    "tag": "switchboard-leak",
                    "message": "queued at 23:30",
                    "priority": "normal",
                    "queued_at": NIGHT_UTC.isoformat(),
                }
            ],
        },
    }
    hass.states.async_set("schedule.night", "on", {"next_event": SEVEN_UTC.isoformat()})
    entry = await _install_without_a_wake_time(hass, "schedule.night")

    assert calls == []
    assert len(entry.runtime_data.switchboard.store.deferrals) == 1


async def test_a_temporary_silence_outliving_the_schedule_does_not_strand_the_queue(
    hass: HomeAssistant, hass_storage: dict, freezer: Any
) -> None:
    """A person with no wake time has exactly one timer: it must not be lost.

    The fallback timer of §3 is armed on the end the *configured* silence
    publishes. A `notify_switchboard.silence` asked for after the message was
    queued can outlive that end, and then the sequence is:

    * 07:00, the schedule ends and the timer fires; the flush re-decides,
      finds the person still temporarily silent and holds the message;
    * the re-arm that follows reads the schedule, which is now `off` and
      publishes nothing -- so before this test there was no timer left at all;
    * 07:30, the temporary silence expires. Nothing was waiting for it.

    The queue then sat in the store until the *next* night ended, which for a
    message with a time to live usually means it never arrived. Falling back to
    the temporary silence keeps a timer armed across the handover.
    """
    await hass.config.async_set_time_zone("Europe/Paris")
    freezer.move_to(NIGHT_UTC)
    calls = async_mock_service(hass, "notify", "mobile_app_alice")
    hass.states.async_set("schedule.night", "on", {"next_event": SEVEN_UTC.isoformat()})
    entry = await _install_without_a_wake_time(hass, "schedule.night")

    await hass.services.async_call(
        "notify", "switchboard_leak", {"message": "water"}, blocking=True
    )
    await hass.async_block_till_done()
    assert len(entry.runtime_data.switchboard.store.deferrals) == 1

    # 06:30: an hour of requested quiet, ending half an hour after the night.
    freezer.move_to(SIX_UTC + timedelta(minutes=30))
    await hass.services.async_call(
        DOMAIN,
        "silence",
        {"person": "person.alice", "minutes": 60},
        blocking=True,
    )
    await hass.async_block_till_done()

    # 07:00: the night ends, the timer fires, and the message is still held.
    freezer.move_to(SEVEN_UTC)
    hass.states.async_set("schedule.night", "off", {})
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done()
    assert calls == []
    assert len(entry.runtime_data.switchboard.store.deferrals) == 1

    # 07:30: the temporary silence lifts. Somebody has to be waiting for it.
    freezer.move_to(SEVEN_UTC + timedelta(minutes=30))
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done()

    assert [call.data["message"] for call in calls] == ["water"]
    assert entry.runtime_data.switchboard.store.deferrals == {}


async def test_the_re_arm_never_targets_an_instant_that_has_already_passed(
    hass: HomeAssistant, hass_storage: dict, freezer: Any
) -> None:
    """A timer firing at the end a schedule published can beat the schedule.

    `async_track_point_in_time` does not refuse a point in the past: it fires
    on the next pass of the loop
    (`$HA_CORE_SRC/homeassistant/helpers/event.py`, `_TrackPointUTCTime`). So a
    flush that runs at 07:00 while `schedule.night` still reads `on` with a
    `next_event` of 07:00 -- its own state write has not landed yet -- would
    hold the message, re-arm on 07:00, fire again at once, hold again, and
    spin until the state finally changed.

    The re-arm is asserted directly rather than by letting the loop run,
    because the bug this pins is an unbounded loop: a test that drove it would
    not fail, it would never finish.
    """
    await hass.config.async_set_time_zone("Europe/Paris")
    freezer.move_to(NIGHT_UTC)
    async_mock_service(hass, "notify", "mobile_app_alice")
    hass.states.async_set("schedule.night", "on", {"next_event": SEVEN_UTC.isoformat()})
    entry = await _install_without_a_wake_time(hass, "schedule.night")

    await hass.services.async_call(
        "notify", "switchboard_leak", {"message": "water"}, blocking=True
    )
    await hass.async_block_till_done()
    switchboard = entry.runtime_data.switchboard
    assert len(switchboard.store.deferrals) == 1

    # 07:00 sharp, and the schedule has not caught up: it still publishes the
    # end that is now behind us.
    freezer.move_to(SEVEN_UTC)
    armed: list[datetime] = []

    def _record(_hass: HomeAssistant, _action: Any, when: datetime) -> Any:
        armed.append(when)
        return lambda: None

    with patch(
        "custom_components.notify_switchboard.dispatcher.async_track_point_in_time",
        side_effect=_record,
    ):
        switchboard._async_schedule_deferral("person.alice")

    assert all(when > dt_util.now() for when in armed), (
        f"re-armed on {armed}, which is not ahead of {dt_util.now()}"
    )


async def test_a_silence_going_on_again_re_arms_a_queue_that_lost_its_timer(
    hass: HomeAssistant, hass_storage: dict, freezer: Any
) -> None:
    """The other half of the stale re-arm: something has to put the timer back.

    The sibling above is why a wake-time-less queue can end up with no timer at
    all: a flush that runs at the very instant the schedule published reads an
    end that is no longer ahead of it, and dropping that end is the only thing
    that does not spin. What it leaves behind is a queue nothing is waiting on,
    and the next state write of that schedule -- a second block starting where
    the first ended, so `on` again with a later end -- was ignored, because
    `_async_silence_changed` only ever looked at a silence *lifting*.

    The timer itself is what this asserts. Every other way into a flush -- the
    schedule finally going `off`, a restart, a fresh message -- would release
    the queue on its own, so a delivery here would prove nothing about the
    re-arm.
    """
    await hass.config.async_set_time_zone("Europe/Paris")
    freezer.move_to(NIGHT_UTC)
    async_mock_service(hass, "notify", "mobile_app_alice")
    hass.states.async_set("schedule.night", "on", {"next_event": SEVEN_UTC.isoformat()})
    entry = await _install_without_a_wake_time(hass, "schedule.night")

    await hass.services.async_call(
        "notify", "switchboard_leak", {"message": "water"}, blocking=True
    )
    await hass.async_block_till_done()
    switchboard = entry.runtime_data.switchboard
    assert len(switchboard.store.deferrals) == 1

    # 07:00 sharp, before the schedule's own state write lands: the flush finds
    # it still `on`, holds the message, and the re-arm has nothing left but an
    # end that is no longer ahead of it.
    freezer.move_to(SEVEN_UTC)
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done()
    assert len(switchboard.store.deferrals) == 1
    assert switchboard._deferral_unsubs == {}

    # The schedule writes its second block: still `on`, ending an hour later.
    hass.states.async_set("schedule.night", "on", {"next_event": EIGHT_UTC.isoformat()})
    await hass.async_block_till_done()

    assert "person.alice" in switchboard._deferral_unsubs
