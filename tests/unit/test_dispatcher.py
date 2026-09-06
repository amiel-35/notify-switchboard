"""Tests for the side-effecting half of the router."""

from __future__ import annotations

from datetime import datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import homeassistant.helpers.device_registry as dr
import homeassistant.helpers.issue_registry as ir
import homeassistant.util.dt as dt_util
import pytest
from homeassistant.core import HomeAssistant
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
from custom_components.notify_switchboard.dispatcher import next_wake_time


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

    # The output is still counted as routed: the decision was to route it.
    assert hass.states.get("sensor.switchboard_routed_today").state == "4"
    assert entry.runtime_data.switchboard.missing_outputs["mobile_app_ghost"] == 4


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
    assert entry.runtime_data.switchboard.missing_outputs == {"mobile_app_late": 1}

    calls = async_mock_service(hass, "notify", "mobile_app_late")
    await hass.services.async_call(
        "notify", "switchboard_leak", {"message": "m"}, blocking=True
    )
    await hass.async_block_till_done()
    assert len(calls) == 1
    assert entry.runtime_data.switchboard.missing_outputs == {}


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


async def test_a_failing_output_is_logged_and_the_delivery_still_counts(
    hass: HomeAssistant,
) -> None:
    """An unexpected exception from an output cannot break the router."""
    async_mock_service(
        hass, "notify", "mobile_app_alice", raise_exception=RuntimeError("boom")
    )
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
