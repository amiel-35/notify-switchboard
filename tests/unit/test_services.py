"""Unit tests for the v0.2 UI services, temporary silence and row texts.

The acceptance suite (`tests/acceptance/test_s2_services.py`,
`test_s2_row_texts.py`) pins the contract; this file covers the branches it
does not reach: the voluptuous schemas, each refusal path of the shared
validation helpers, the interaction between the two silence sources, the
`repairs` issue raised on a recurring bad call, service teardown on unload, and
template rendering when the alert is missing or the template is broken.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import homeassistant.helpers.issue_registry as ir
import homeassistant.util.dt as dt_util
import pytest
import voluptuous as vol
from homeassistant.core import Context, HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
    async_mock_service,
)

from custom_components.notify_switchboard.const import (
    DOMAIN,
    ISSUE_INVALID_SERVICE_CALLS_MANY,
    MAX_INVALID_SERVICE_CALLS,
    MAX_SILENCE_MINUTES,
    MAX_TRACKED_INVALID_SERVICE_CALLS,
    MIN_SILENCE_MINUTES,
    UI_SERVICES,
)
from custom_components.notify_switchboard.diagnostics import (
    async_get_config_entry_diagnostics,
)
from custom_components.notify_switchboard.router import (
    PersonConfig,
    RoutingContext,
    has_temporary_silence,
    is_silenced,
    parse_target,
)
from custom_components.notify_switchboard.services import (
    ACKNOWLEDGE_SCHEMA,
    SILENCE_SCHEMA,
    SNOOZE_SCHEMA,
    UNSILENCE_SCHEMA,
    UNSNOOZE_SCHEMA,
    async_loaded_switchboard,
)
from custom_components.notify_switchboard.store import SwitchboardStorage


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
    """Build one `entry.options["targets"]` row (v0.2 shape)."""
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
        "message": None,
        "done_message": None,
        "default_title": None,
    }
    row.update(overrides)
    return row


async def install(
    hass: HomeAssistant, persons: list[dict], targets: list[dict], default: str
) -> MockConfigEntry:
    """Create and set up a config entry."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id="ns_services_entry",
        title="Notify Switchboard",
        version=1,
        minor_version=1,
        options={"persons": persons, "targets": targets, "default_target": default},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


def test_acknowledge_schema_requires_a_target() -> None:
    assert ACKNOWLEDGE_SCHEMA({"target": "leak"}) == {"target": "leak"}
    with pytest.raises(vol.Invalid):
        ACKNOWLEDGE_SCHEMA({})


def test_snooze_schema_coerces_minutes_and_keeps_person_optional() -> None:
    assert SNOOZE_SCHEMA({"target": "leak", "minutes": "60"}) == {
        "target": "leak",
        "minutes": 60,
    }
    assert SNOOZE_SCHEMA(
        {"target": "leak", "minutes": 15, "person": "person.alice"}
    ) == {"target": "leak", "minutes": 15, "person": "person.alice"}
    with pytest.raises(vol.Invalid):
        SNOOZE_SCHEMA({"target": "leak"})
    with pytest.raises(vol.Invalid):
        SNOOZE_SCHEMA({"target": "leak", "minutes": "soon"})
    with pytest.raises(vol.Invalid):
        SNOOZE_SCHEMA({"target": "leak", "minutes": 15, "person": "not an entity"})


def test_snooze_schema_accepts_zero_so_the_handler_can_refuse_it() -> None:
    """`vol.Invalid` from a schema is not a `ServiceValidationError`.

    `homeassistant/core.py`, `ServiceRegistry.async_call`, re-raises a schema's
    `vol.Invalid` as-is, so every refusal the contract wants reported as a
    `ServiceValidationError` has to happen in the handler.
    """
    assert SILENCE_SCHEMA({"person": "person.alice", "minutes": 0})["minutes"] == 0


def test_unsnooze_and_unsilence_schemas() -> None:
    assert UNSNOOZE_SCHEMA({"target": "leak"}) == {"target": "leak"}
    assert UNSILENCE_SCHEMA({"person": "person.alice"}) == {"person": "person.alice"}
    with pytest.raises(vol.Invalid):
        UNSILENCE_SCHEMA({})


# ---------------------------------------------------------------------------
# Registration lifecycle
# ---------------------------------------------------------------------------


async def test_services_survive_an_unload_and_act_again_after_a_reload(
    hass: HomeAssistant,
) -> None:
    """v0.3 (ADR-0017 §5): unloading removes the ability to act, not the actions.

    0.2.0 unregistered them, because their closures held the unloaded entry's
    `Switchboard`. They now resolve the loaded entry at call time, so nothing
    dangles and an automation naming one of them keeps validating.
    """
    entry = await install(
        hass,
        [make_person("person.alice", ["mobile_app_alice"])],
        [make_target("leak")],
        "leak",
    )
    for service in UI_SERVICES:
        assert hass.services.has_service(DOMAIN, service)

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    for service in UI_SERVICES:
        assert hass.services.has_service(DOMAIN, service)

    with pytest.raises(ServiceValidationError) as err:
        await hass.services.async_call(
            DOMAIN, "unsilence", {"person": "person.alice"}, blocking=True
        )
    assert err.value.translation_key == "no_loaded_entry"

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    await hass.services.async_call(
        DOMAIN, "unsilence", {"person": "person.alice"}, blocking=True
    )


async def test_a_service_call_without_the_integration_set_up_finds_no_entry(
    hass: HomeAssistant,
) -> None:
    """`async_loaded_switchboard` is the single refusal point, and it is reachable."""
    with pytest.raises(ServiceValidationError) as err:
        async_loaded_switchboard(hass)
    assert err.value.translation_domain == DOMAIN
    assert err.value.translation_key == "no_loaded_entry"


async def test_a_reload_rebinds_the_services_to_the_new_switchboard(
    hass: HomeAssistant,
) -> None:
    """After a reload the services must write to the live entry's store."""
    entry = await install(
        hass,
        [make_person("person.alice", ["mobile_app_alice"])],
        [make_target("leak", snooze_minutes=[30])],
        "leak",
    )
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()

    await hass.services.async_call(
        DOMAIN, "snooze", {"target": "leak", "minutes": 30}, blocking=True
    )
    await hass.async_block_till_done()

    switchboard = entry.runtime_data.switchboard
    assert ("person.alice", "leak") in switchboard.store.snoozes


# ---------------------------------------------------------------------------
# Refusals
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("service", "data"),
    [
        ("acknowledge", {"target": "nope"}),
        ("snooze", {"target": "nope", "minutes": 30}),
        ("unsnooze", {"target": "nope"}),
    ],
)
async def test_an_unknown_target_is_refused_on_every_target_service(
    hass: HomeAssistant, service: str, data: dict
) -> None:
    await install(
        hass,
        [make_person("person.alice", ["mobile_app_alice"])],
        [make_target("leak", snooze_minutes=[30])],
        "leak",
    )
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(DOMAIN, service, data, blocking=True)


async def test_an_explicit_person_outside_the_audience_is_refused(
    hass: HomeAssistant,
) -> None:
    await install(
        hass,
        [
            make_person("person.alice", ["mobile_app_alice"]),
            make_person("person.bob", ["mobile_app_bob"]),
        ],
        [make_target("leak", audience=["person.alice"], snooze_minutes=[30])],
        "leak",
    )
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN,
            "snooze",
            {"target": "leak", "minutes": 30, "person": "person.bob"},
            blocking=True,
        )


async def test_an_unknown_person_is_refused_on_snooze(hass: HomeAssistant) -> None:
    await install(
        hass,
        [make_person("person.alice", ["mobile_app_alice"])],
        [make_target("leak", snooze_minutes=[30])],
        "leak",
    )
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN,
            "snooze",
            {"target": "leak", "minutes": 30, "person": "person.ghost"},
            blocking=True,
        )


async def test_a_row_whose_audience_is_unknown_has_nobody_to_snooze(
    hass: HomeAssistant,
) -> None:
    """A hand-edited row naming nobody the table knows cannot be snoozed."""
    await install(
        hass,
        [make_person("person.alice", ["mobile_app_alice"])],
        [make_target("leak", audience=["person.ghost"], snooze_minutes=[30])],
        "leak",
    )
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN, "snooze", {"target": "leak", "minutes": 30}, blocking=True
        )


async def test_a_row_with_no_snooze_durations_refuses_every_duration(
    hass: HomeAssistant,
) -> None:
    await install(
        hass,
        [make_person("person.alice", ["mobile_app_alice"])],
        [make_target("leak", snooze_minutes=[])],
        "leak",
    )
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN, "snooze", {"target": "leak", "minutes": 30}, blocking=True
        )


async def test_unsnooze_on_a_person_with_no_snooze_is_not_an_error(
    hass: HomeAssistant,
) -> None:
    entry = await install(
        hass,
        [make_person("person.alice", ["mobile_app_alice"])],
        [make_target("leak", snooze_minutes=[30])],
        "leak",
    )
    await hass.services.async_call(
        DOMAIN, "unsnooze", {"target": "leak", "person": "person.alice"}, blocking=True
    )
    await hass.async_block_till_done()
    assert entry.runtime_data.switchboard.store.snoozes == {}


async def test_a_recurring_invalid_target_raises_one_repairs_issue(
    hass: HomeAssistant,
) -> None:
    """One refusal answers its caller; a card stuck on a stale slug needs a repair."""
    await install(
        hass,
        [make_person("person.alice", ["mobile_app_alice"])],
        [make_target("leak")],
        "leak",
    )
    registry = ir.async_get(hass)

    for attempt in range(1, MAX_INVALID_SERVICE_CALLS + 1):
        with pytest.raises(ServiceValidationError):
            await hass.services.async_call(
                DOMAIN, "acknowledge", {"target": "stale"}, blocking=True
            )
        issue = registry.async_get_issue(DOMAIN, "invalid_service_target_stale")
        assert (issue is not None) is (attempt >= MAX_INVALID_SERVICE_CALLS)


async def test_a_recurring_unknown_person_raises_one_repairs_issue(
    hass: HomeAssistant,
) -> None:
    await install(
        hass,
        [make_person("person.alice", ["mobile_app_alice"])],
        [make_target("leak")],
        "leak",
    )
    for _ in range(MAX_INVALID_SERVICE_CALLS):
        with pytest.raises(ServiceValidationError):
            await hass.services.async_call(
                DOMAIN,
                "silence",
                {"person": "person.ghost", "minutes": 30},
                blocking=True,
            )

    issue = ir.async_get(hass).async_get_issue(
        DOMAIN, "invalid_service_person_person.ghost"
    )
    assert issue is not None


async def test_acknowledge_logs_the_calling_user(
    hass: HomeAssistant, caplog: pytest.LogCaptureFixture
) -> None:
    """The contract asks for `context.user_id` on a refusal, like the Companion path."""
    await install(
        hass,
        [make_person("person.alice", ["mobile_app_alice"])],
        [make_target("leak", alert_entity="alert.leak", allow_acknowledge=False)],
        "leak",
    )
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN,
            "acknowledge",
            {"target": "leak"},
            blocking=True,
            context=Context(user_id="user-42"),
        )
    assert "user-42" in caplog.text


# ---------------------------------------------------------------------------
# Temporary silence
# ---------------------------------------------------------------------------


def test_is_silenced_combines_both_sources() -> None:
    """ADR-0016: configured silence OR temporary silence, never one instead of the other."""
    person = PersonConfig(
        entity_id="person.alice", silence_entities=("input_boolean.night",)
    )
    now = dt_util.utcnow()
    later = {"person.alice": now + timedelta(minutes=10)}
    earlier = {"person.alice": now - timedelta(minutes=10)}

    assert not is_silenced(person, RoutingContext(now=now))
    assert is_silenced(
        person, RoutingContext(now=now, silenced={"input_boolean.night": True})
    )
    assert is_silenced(person, RoutingContext(now=now, temporary_silences=later))
    assert not is_silenced(person, RoutingContext(now=now, temporary_silences=earlier))
    assert has_temporary_silence(
        "person.alice", RoutingContext(now=now, temporary_silences=later)
    )
    assert not has_temporary_silence(
        "person.bob", RoutingContext(now=now, temporary_silences=later)
    )


async def test_silence_never_touches_the_persons_own_silence_entities(
    hass: HomeAssistant,
) -> None:
    """`silence_entities` are read, never owned (docs/ARCHITECTURE.md)."""
    hass.states.async_set("input_boolean.alice_night", "off")
    entry = await install(
        hass,
        [
            make_person(
                "person.alice",
                ["mobile_app_alice"],
                silence_entities=["input_boolean.alice_night"],
            )
        ],
        [make_target("leak")],
        "leak",
    )

    await hass.services.async_call(
        DOMAIN, "silence", {"person": "person.alice", "minutes": 30}, blocking=True
    )
    await hass.async_block_till_done()

    assert hass.states.get("input_boolean.alice_night").state == "off"
    silenced = hass.states.get("binary_sensor.alice_silenced")
    assert silenced.state == "on"
    assert silenced.attributes["sources"] == ["input_boolean.alice_night"]
    until = entry.runtime_data.switchboard.store.silences["person.alice"]
    assert silenced.attributes["until"] == until.isoformat()


async def test_the_silenced_sensor_only_carries_until_while_temporarily_silent(
    hass: HomeAssistant,
) -> None:
    await install(
        hass,
        [make_person("person.alice", ["mobile_app_alice"])],
        [make_target("leak")],
        "leak",
    )
    assert "until" not in hass.states.get("binary_sensor.alice_silenced").attributes

    await hass.services.async_call(
        DOMAIN, "silence", {"person": "person.alice", "minutes": 30}, blocking=True
    )
    await hass.async_block_till_done()
    assert "until" in hass.states.get("binary_sensor.alice_silenced").attributes

    await hass.services.async_call(
        DOMAIN, "unsilence", {"person": "person.alice"}, blocking=True
    )
    await hass.async_block_till_done()
    assert "until" not in hass.states.get("binary_sensor.alice_silenced").attributes


async def test_a_second_silence_replaces_the_first_and_re_arms_the_timer(
    hass: HomeAssistant, freezer: Any
) -> None:
    entry = await install(
        hass,
        [make_person("person.alice", ["mobile_app_alice"])],
        [make_target("leak")],
        "leak",
    )
    switchboard = entry.runtime_data.switchboard

    await hass.services.async_call(
        DOMAIN, "silence", {"person": "person.alice", "minutes": 10}, blocking=True
    )
    await hass.async_block_till_done()
    first = switchboard.store.silences["person.alice"]

    await hass.services.async_call(
        DOMAIN, "silence", {"person": "person.alice", "minutes": 30}, blocking=True
    )
    await hass.async_block_till_done()
    assert switchboard.store.silences["person.alice"] > first

    # The first timer was cancelled: the silence outlives its original expiry.
    freezer.tick(timedelta(minutes=11))
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done()
    assert hass.states.get("binary_sensor.alice_silenced").state == "on"


async def test_a_silence_that_expired_while_unloaded_is_dropped_at_setup(
    hass: HomeAssistant, freezer: Any
) -> None:
    entry = await install(
        hass,
        [make_person("person.alice", ["mobile_app_alice"])],
        [make_target("leak")],
        "leak",
    )
    await hass.services.async_call(
        DOMAIN, "silence", {"person": "person.alice", "minutes": 10}, blocking=True
    )
    await hass.async_block_till_done()

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()

    freezer.tick(timedelta(minutes=30))
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.runtime_data.switchboard.store.silences == {}
    assert hass.states.get("binary_sensor.alice_silenced").state == "off"


async def test_unsilence_is_a_noop_and_leaves_the_store_alone(
    hass: HomeAssistant,
) -> None:
    entry = await install(
        hass,
        [make_person("person.alice", ["mobile_app_alice"])],
        [make_target("leak")],
        "leak",
    )
    await hass.services.async_call(
        DOMAIN, "unsilence", {"person": "person.alice"}, blocking=True
    )
    await hass.async_block_till_done()
    assert entry.runtime_data.switchboard.store.silences == {}

    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN, "unsilence", {"person": "person.ghost"}, blocking=True
        )


async def test_a_temporary_silence_drops_rather_than_defers_to_the_wake_time(
    hass: HomeAssistant,
) -> None:
    """`wake_time` is the end of the *night*, not of an hour of quiet."""
    calls = async_mock_service(hass, "notify", "mobile_app_alice")
    hass.states.async_set("person.alice", "home")
    entry = await install(
        hass,
        [make_person("person.alice", ["mobile_app_alice"], wake_time="07:00:00")],
        [make_target("leak")],
        "leak",
    )

    await hass.services.async_call(
        DOMAIN, "silence", {"person": "person.alice", "minutes": 30}, blocking=True
    )
    await hass.services.async_call(
        "notify", "switchboard_leak", {"message": "m"}, blocking=True
    )
    await hass.async_block_till_done()

    switchboard = entry.runtime_data.switchboard
    assert calls == []
    assert switchboard.store.deferrals == {}
    assert switchboard.drop_reasons.get("silenced") == 1


async def test_a_night_silence_still_defers_even_under_a_temporary_silence(
    hass: HomeAssistant,
) -> None:
    """Both active: the configured night silence wins, so nothing is lost."""
    async_mock_service(hass, "notify", "mobile_app_alice")
    hass.states.async_set("person.alice", "home")
    hass.states.async_set("input_boolean.alice_night", "on")
    entry = await install(
        hass,
        [
            make_person(
                "person.alice",
                ["mobile_app_alice"],
                silence_entities=["input_boolean.alice_night"],
                wake_time="07:00:00",
            )
        ],
        [make_target("leak")],
        "leak",
    )

    await hass.services.async_call(
        DOMAIN, "silence", {"person": "person.alice", "minutes": 30}, blocking=True
    )
    await hass.services.async_call(
        "notify", "switchboard_leak", {"message": "m"}, blocking=True
    )
    await hass.async_block_till_done()

    assert len(entry.runtime_data.switchboard.store.deferrals) == 1


# ---------------------------------------------------------------------------
# Store: the `silences` list and its migration
# ---------------------------------------------------------------------------


async def test_an_unparsable_silence_row_is_dropped_rather_than_fatal(
    hass: HomeAssistant, hass_storage: dict
) -> None:
    """A hand-edited `.storage` file must never stop the entry from loading."""
    good_until = (dt_util.utcnow() + timedelta(minutes=30)).isoformat()
    hass_storage["notify_switchboard.data"] = {
        "version": 1,
        "minor_version": 3,
        "key": "notify_switchboard.data",
        "data": {
            "snoozes": [],
            "deferrals": [],
            "silences": [
                {"person": "person.alice", "until": good_until},
                {"person": "", "until": good_until},  # no person
                {"person": "person.bob", "until": "not a date"},
                {"person": "person.carol"},  # no `until` at all
            ],
        },
    }

    entry = await install(
        hass,
        [make_person("person.alice", ["mobile_app_alice"])],
        [make_target("leak")],
        "leak",
    )

    assert list(entry.runtime_data.switchboard.store.silences) == ["person.alice"]
    assert hass.states.get("binary_sensor.alice_silenced").state == "on"


async def test_an_unparsable_snooze_or_deferral_row_is_dropped_too(
    hass: HomeAssistant, hass_storage: dict
) -> None:
    """The same tolerance as `silences`, for the other two lists.

    A snooze with no slug and a deferral with no message body are dropped one
    by one; the well-formed rows next to them still load.
    """
    good_until = (dt_util.utcnow() + timedelta(minutes=30)).isoformat()
    hass_storage["notify_switchboard.data"] = {
        "version": 1,
        "minor_version": 3,
        "key": "notify_switchboard.data",
        "data": {
            "snoozes": [
                {"person": "person.alice", "slug": "leak", "expires_at": good_until},
                {"person": "person.alice", "expires_at": good_until},  # no slug
                {"person": "", "slug": "leak", "expires_at": good_until},  # no person
                {"person": "person.alice", "slug": "leak"},  # no `expires_at`
            ],
            "deferrals": [
                {
                    "person": "person.alice",
                    "slug": "leak",
                    "tag": "t",
                    "message": "kept",
                    "queued_at": good_until,
                },
                {"person": "person.alice", "slug": "leak", "tag": "u"},  # no message
                {"person": "person.alice"},  # no slug either
            ],
            "silences": [],
        },
    }

    entry = await install(
        hass,
        [make_person("person.alice", ["mobile_app_alice"])],
        [make_target("leak")],
        "leak",
    )

    store = entry.runtime_data.switchboard.store
    assert list(store.snoozes) == [("person.alice", "leak")]
    assert list(store.deferrals) == [("person.alice", "leak", "t")]
    assert store.deferrals[("person.alice", "leak", "t")].message == "kept"


async def test_the_store_refuses_to_read_a_document_from_the_future(
    hass: HomeAssistant,
) -> None:
    """A downgrade is data loss, so the migration raises instead of guessing."""
    store = SwitchboardStorage(hass, 1, "notify_switchboard.test", minor_version=3)
    with pytest.raises(ValueError, match="Cannot downgrade"):
        await store._async_migrate_func(2, 1, {"snoozes": [], "deferrals": []})


async def test_the_migration_leaves_a_document_already_at_minor_3_alone(
    hass: HomeAssistant,
) -> None:
    """The minor-3 step only fires on an older document."""
    store = SwitchboardStorage(hass, 1, "notify_switchboard.test", minor_version=3)
    data = {"snoozes": [], "deferrals": [], "silences": [{"person": "person.alice"}]}
    migrated = await store._async_migrate_func(1, 3, data)
    assert migrated["silences"] == [{"person": "person.alice"}]

    upgraded = await store._async_migrate_func(1, 2, {"snoozes": [], "deferrals": []})
    assert upgraded["silences"] == []


async def test_a_stored_silence_survives_and_re_arms_its_timer(
    hass: HomeAssistant, hass_storage: dict, freezer: Any
) -> None:
    """A silence loaded from disk still lifts on its own."""
    hass_storage["notify_switchboard.data"] = {
        "version": 1,
        "minor_version": 3,
        "key": "notify_switchboard.data",
        "data": {
            "snoozes": [],
            "deferrals": [],
            "silences": [
                {
                    "person": "person.alice",
                    "until": (dt_util.utcnow() + timedelta(minutes=5)).isoformat(),
                }
            ],
        },
    }

    await install(
        hass,
        [make_person("person.alice", ["mobile_app_alice"])],
        [make_target("leak")],
        "leak",
    )
    assert hass.states.get("binary_sensor.alice_silenced").state == "on"

    freezer.tick(timedelta(minutes=6))
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done()

    assert hass.states.get("binary_sensor.alice_silenced").state == "off"


# ---------------------------------------------------------------------------
# Row texts
# ---------------------------------------------------------------------------


def test_parse_target_normalises_the_three_optional_texts() -> None:
    """Absent, empty and blank all mean "not configured"."""
    empty = parse_target(make_target("leak"))
    assert (empty.message, empty.done_message, empty.default_title) == (
        None,
        None,
        None,
    )

    blank = parse_target(
        make_target("leak", message="  ", done_message="", default_title="   ")
    )
    assert (blank.message, blank.done_message, blank.default_title) == (
        None,
        None,
        None,
    )

    legacy = parse_target({"slug": "leak", "name": "Leak"})
    assert legacy.message is None
    assert legacy.default_title is None

    filled = parse_target(make_target("leak", message=" {{ 1 }} ", default_title=" T "))
    assert filled.message == "{{ 1 }}"
    assert filled.default_title == "T"


async def test_observer_template_renders_none_when_the_alert_does_not_exist(
    hass: HomeAssistant,
) -> None:
    """`alert` is None when the row has no alert entity, or it does not exist yet."""
    calls = async_mock_service(hass, "notify", "mobile_app_alice")
    hass.states.async_set("person.alice", "home")
    await install(
        hass,
        [make_person("person.alice", ["mobile_app_alice"])],
        [
            make_target(
                "observed",
                alert_entity="alert.observed",
                observer_mode=True,
                message="alert is {{ 'missing' if alert is none else 'there' }}",
            )
        ],
        "observed",
    )

    hass.states.async_set("alert.observed", "idle")
    await hass.async_block_till_done()
    hass.states.async_set("alert.observed", "on")
    await hass.async_block_till_done()

    assert calls[0].data["message"] == "alert is there"


async def test_a_broken_template_falls_back_instead_of_breaking_the_route(
    hass: HomeAssistant, caplog: pytest.LogCaptureFixture
) -> None:
    """A template that raises must not swallow the notification."""
    calls = async_mock_service(hass, "notify", "mobile_app_alice")
    hass.states.async_set("person.alice", "home")
    await install(
        hass,
        [make_person("person.alice", ["mobile_app_alice"])],
        [
            make_target(
                "observed",
                alert_entity="alert.observed",
                observer_mode=True,
                message="{{ 1 / 0 }}",
                done_message="{{ 1 / 0 }}",
            )
        ],
        "observed",
    )

    hass.states.async_set("alert.observed", "idle")
    await hass.async_block_till_done()
    hass.states.async_set("alert.observed", "on")
    await hass.async_block_till_done()
    assert calls[0].data["message"] == "Observed"  # the row name

    hass.states.async_set("alert.observed", "idle")
    await hass.async_block_till_done()
    assert calls[1].data["message"] == "Back to normal"
    assert "could not render the row text" in caplog.text


async def test_a_template_rendering_to_nothing_falls_back_too(
    hass: HomeAssistant,
) -> None:
    calls = async_mock_service(hass, "notify", "mobile_app_alice")
    hass.states.async_set("person.alice", "home")
    await install(
        hass,
        [make_person("person.alice", ["mobile_app_alice"])],
        [
            make_target(
                "observed",
                alert_entity="alert.observed",
                observer_mode=True,
                message="{{ '' }}",
            )
        ],
        "observed",
    )

    hass.states.async_set("alert.observed", "idle")
    await hass.async_block_till_done()
    hass.states.async_set("alert.observed", "on")
    await hass.async_block_till_done()

    assert calls[0].data["message"] == "Observed"


async def test_done_message_template_wins_over_the_alerts_own_attribute(
    hass: HomeAssistant,
) -> None:
    """Contract §"Per-row texts" and ADR-0016 §3 both order it this way."""
    calls = async_mock_service(hass, "notify", "mobile_app_alice")
    hass.states.async_set("person.alice", "home")
    await install(
        hass,
        [make_person("person.alice", ["mobile_app_alice"])],
        [
            make_target(
                "observed",
                alert_entity="alert.observed",
                observer_mode=True,
                done_message="From the row",
            )
        ],
        "observed",
    )

    hass.states.async_set("alert.observed", "idle")
    await hass.async_block_till_done()
    hass.states.async_set("alert.observed", "on")
    await hass.async_block_till_done()
    hass.states.async_set("alert.observed", "idle", {"done_message": "From the alert"})
    await hass.async_block_till_done()

    assert calls[1].data["message"] == "From the row"


async def test_default_title_is_resolved_per_row_not_per_request(
    hass: HomeAssistant,
) -> None:
    """A call fanned out over two rows gets each row's own default title."""
    calls = async_mock_service(hass, "notify", "mobile_app_alice")
    hass.states.async_set("person.alice", "home")
    await install(
        hass,
        [make_person("person.alice", ["mobile_app_alice"])],
        [
            make_target("leak", default_title="Leak!"),
            make_target("garage", default_title="Garage!"),
        ],
        "leak",
    )

    await hass.services.async_call(
        "notify",
        "switchboard",
        {"message": "m", "target": ["leak", "garage"]},
        blocking=True,
    )
    await hass.async_block_till_done()

    assert {call.data["title"] for call in calls} == {"Leak!", "Garage!"}


async def test_a_row_without_a_default_title_still_sends_no_title(
    hass: HomeAssistant,
) -> None:
    """Sprint 1 behaviour is unchanged when the new field is absent."""
    calls = async_mock_service(hass, "notify", "mobile_app_alice")
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

    assert "title" not in calls[0].data


async def test_observer_mode_without_a_default_title_still_uses_the_row_name(
    hass: HomeAssistant,
) -> None:
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

    assert calls[0].data["title"] == "Observed"


# ---------------------------------------------------------------------------
# Post-review fixes
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("minutes", [0, MAX_SILENCE_MINUTES + 1, 10**9, 10**15])
async def test_silence_refuses_a_duration_outside_its_bounds(
    hass: HomeAssistant, minutes: int
) -> None:
    """B1: out-of-range `minutes` is a translated refusal, never an `OverflowError`.

    `dt_util.utcnow() + timedelta(minutes=10**15)` raises `OverflowError`, which
    is not a `HomeAssistantError`, so before the bound existed a card typo
    surfaced to the caller as an unhandled exception instead of as the
    `ServiceValidationError` ADR-0015 promises.
    """
    entry = await install(
        hass,
        [make_person("person.alice", ["mobile_app_alice"])],
        [make_target("leak")],
        "leak",
    )

    with pytest.raises(ServiceValidationError) as raised:
        await hass.services.async_call(
            DOMAIN,
            "silence",
            {"person": "person.alice", "minutes": minutes},
            blocking=True,
        )

    assert raised.value.translation_key == "invalid_silence_minutes"
    assert raised.value.translation_placeholders == {
        "minutes": str(minutes),
        "min": str(MIN_SILENCE_MINUTES),
        "max": str(MAX_SILENCE_MINUTES),
    }
    assert entry.runtime_data.switchboard.store.silences == {}


@pytest.mark.parametrize("minutes", [MIN_SILENCE_MINUTES, MAX_SILENCE_MINUTES])
async def test_silence_accepts_both_ends_of_the_range(
    hass: HomeAssistant, minutes: int
) -> None:
    """The bounds are inclusive on both sides."""
    entry = await install(
        hass,
        [make_person("person.alice", ["mobile_app_alice"])],
        [make_target("leak")],
        "leak",
    )
    await hass.services.async_call(
        DOMAIN,
        "silence",
        {"person": "person.alice", "minutes": minutes},
        blocking=True,
    )
    assert "person.alice" in entry.runtime_data.switchboard.store.silences


async def test_many_distinct_invalid_targets_collapse_into_one_issue(
    hass: HomeAssistant,
) -> None:
    """I3: an unbounded caller must not grow the issue registry one row per value."""
    await install(
        hass,
        [make_person("person.alice", ["mobile_app_alice"])],
        [make_target("leak")],
        "leak",
    )
    registry = ir.async_get(hass)

    # Enough distinct slugs to fill the tracking table, each refused often
    # enough to earn its own issue.
    for index in range(MAX_TRACKED_INVALID_SERVICE_CALLS):
        for _ in range(MAX_INVALID_SERVICE_CALLS):
            with pytest.raises(ServiceValidationError):
                await hass.services.async_call(
                    DOMAIN, "acknowledge", {"target": f"stale{index}"}, blocking=True
                )

    assert registry.async_get_issue(DOMAIN, ISSUE_INVALID_SERVICE_CALLS_MANY) is None

    # One value past the cap: no new per-value issue, one aggregated issue.
    for _ in range(MAX_INVALID_SERVICE_CALLS):
        with pytest.raises(ServiceValidationError):
            await hass.services.async_call(
                DOMAIN, "acknowledge", {"target": "overflow"}, blocking=True
            )

    assert registry.async_get_issue(DOMAIN, "invalid_service_target_overflow") is None
    assert (
        registry.async_get_issue(DOMAIN, ISSUE_INVALID_SERVICE_CALLS_MANY) is not None
    )
    per_value = [
        issue
        for issue in registry.issues.values()
        if issue.domain == DOMAIN and issue.issue_id.startswith("invalid_service_")
    ]
    assert len(per_value) == MAX_TRACKED_INVALID_SERVICE_CALLS + 1


async def test_a_person_accepted_again_clears_their_repair_without_a_reload(
    hass: HomeAssistant,
) -> None:
    """I3: the issue outlives the refusals, so an accepted call has to delete it.

    The issue is keyed on the person, not on the target that refused them, so
    any later call the router accepts for that person retires it. If the caller
    is still broken, three more refusals raise it again.
    """
    await install(
        hass,
        [
            make_person("person.alice", ["mobile_app_alice"]),
            make_person("person.bob", ["mobile_app_bob"]),
        ],
        [
            make_target("leak", snooze_minutes=[15], audience=["person.alice"]),
            make_target("fountain", snooze_minutes=[15], audience=["person.bob"]),
        ],
        "leak",
    )
    registry = ir.async_get(hass)

    for _ in range(MAX_INVALID_SERVICE_CALLS):
        with pytest.raises(ServiceValidationError):
            await hass.services.async_call(
                DOMAIN,
                "snooze",
                {"target": "leak", "minutes": 15, "person": "person.bob"},
                blocking=True,
            )
    assert registry.async_get_issue(DOMAIN, "invalid_service_person_person.bob")

    await hass.services.async_call(
        DOMAIN,
        "snooze",
        {"target": "fountain", "minutes": 15, "person": "person.bob"},
        blocking=True,
    )
    assert registry.async_get_issue(DOMAIN, "invalid_service_person_person.bob") is None


async def test_a_silence_also_clears_a_persons_repair(hass: HomeAssistant) -> None:
    """I3, the other entry point that fully accepts a person."""
    await install(
        hass,
        [
            make_person("person.alice", ["mobile_app_alice"]),
            make_person("person.bob", ["mobile_app_bob"]),
        ],
        [make_target("leak", snooze_minutes=[15], audience=["person.alice"])],
        "leak",
    )
    registry = ir.async_get(hass)

    for _ in range(MAX_INVALID_SERVICE_CALLS):
        with pytest.raises(ServiceValidationError):
            await hass.services.async_call(
                DOMAIN,
                "snooze",
                {"target": "leak", "minutes": 15, "person": "person.bob"},
                blocking=True,
            )
    assert registry.async_get_issue(DOMAIN, "invalid_service_person_person.bob")

    await hass.services.async_call(
        DOMAIN, "silence", {"person": "person.bob", "minutes": 5}, blocking=True
    )
    assert registry.async_get_issue(DOMAIN, "invalid_service_person_person.bob") is None

    await hass.services.async_call(
        DOMAIN, "unsilence", {"person": "person.bob"}, blocking=True
    )


async def test_a_target_added_back_in_the_options_clears_its_repair(
    hass: HomeAssistant,
) -> None:
    """I3: a reload (what an options change triggers) drops the fixed repairs."""
    entry = await install(
        hass,
        [make_person("person.alice", ["mobile_app_alice"])],
        [make_target("leak")],
        "leak",
    )
    registry = ir.async_get(hass)

    for _ in range(MAX_INVALID_SERVICE_CALLS):
        with pytest.raises(ServiceValidationError):
            await hass.services.async_call(
                DOMAIN, "acknowledge", {"target": "fountain"}, blocking=True
            )
    assert registry.async_get_issue(DOMAIN, "invalid_service_target_fountain")

    hass.config_entries.async_update_entry(
        entry,
        options={
            "persons": [make_person("person.alice", ["mobile_app_alice"])],
            "targets": [make_target("leak"), make_target("fountain")],
            "default_target": "leak",
        },
    )
    await hass.async_block_till_done()

    assert registry.async_get_issue(DOMAIN, "invalid_service_target_fountain") is None


async def test_acknowledge_carries_the_callers_context_to_alert_turn_off(
    hass: HomeAssistant,
) -> None:
    """I5: the logbook must credit the person who tapped, not the integration.

    `alert.turn_off` gets a *child* of the caller's context, not the caller's
    own: `homeassistant/helpers/service.py` turns a non-empty
    `context.user_id` on an entity service call into an auth lookup plus a
    per-entity permission check, which would put the row's `allow_acknowledge`
    allow-list behind the caller's entity permissions. The logbook resolves the
    parent for attribution.
    """
    turn_off = async_mock_service(hass, "alert", "turn_off")
    await install(
        hass,
        [make_person("person.alice", ["mobile_app_alice"])],
        [make_target("leak", alert_entity="alert.leak", allow_acknowledge=True)],
        "leak",
    )

    caller = Context(user_id="user-42")
    await hass.services.async_call(
        DOMAIN, "acknowledge", {"target": "leak"}, blocking=True, context=caller
    )
    await hass.async_block_till_done()

    assert len(turn_off) == 1
    assert turn_off[0].context.parent_id == caller.id
    assert turn_off[0].context.user_id is None

    # The `acknowledged` event entity keeps the caller's own context: writing
    # entity state runs no permission check, so the attribution is direct.
    assert hass.states.get("event.switchboard_delivery").context is caller


async def test_snooze_carries_the_callers_context_to_the_delivery_event(
    hass: HomeAssistant,
) -> None:
    """I5, snooze half: the `snoozed` event is attributed to its caller too."""
    await install(
        hass,
        [make_person("person.alice", ["mobile_app_alice"])],
        [make_target("leak", snooze_minutes=[15])],
        "leak",
    )

    caller = Context(user_id="user-7")
    await hass.services.async_call(
        DOMAIN,
        "snooze",
        {"target": "leak", "minutes": 15},
        blocking=True,
        context=caller,
    )
    await hass.async_block_till_done()

    state = hass.states.get("event.switchboard_delivery")
    assert state.attributes["event_type"] == "snoozed"
    assert state.context is caller


async def test_diagnostics_report_the_temporary_silences(
    hass: HomeAssistant,
) -> None:
    """M7: a silence is as much part of "why was it quiet" as a snooze is."""
    entry = await install(
        hass,
        [make_person("person.alice", ["mobile_app_alice"])],
        [make_target("leak")],
        "leak",
    )
    await hass.services.async_call(
        DOMAIN, "silence", {"person": "person.alice", "minutes": 30}, blocking=True
    )

    diagnostics = await async_get_config_entry_diagnostics(hass, entry)
    assert diagnostics["silences"] == [
        {
            "person": "person.alice",
            "until": entry.runtime_data.switchboard.store.silences[
                "person.alice"
            ].isoformat(),
            "active": True,
        }
    ]


async def test_a_silence_that_expired_while_unloaded_is_purged_from_the_store_file(
    hass: HomeAssistant, hass_storage: dict, freezer: Any
) -> None:
    """M11: purging at setup only helps if the purge is written back."""
    freezer.move_to(datetime(2026, 9, 10, 12, 0, tzinfo=dt_util.UTC))
    hass_storage["notify_switchboard.data"] = {
        "version": 1,
        "minor_version": 3,
        "key": "notify_switchboard.data",
        "data": {
            "snoozes": [],
            "deferrals": [],
            "silences": [
                {
                    "person": "person.alice",
                    "until": datetime(
                        2026, 9, 10, 11, 0, tzinfo=dt_util.UTC
                    ).isoformat(),
                }
            ],
        },
    }

    await install(
        hass,
        [make_person("person.alice", ["mobile_app_alice"])],
        [make_target("leak")],
        "leak",
    )

    assert hass_storage["notify_switchboard.data"]["data"]["silences"] == []
