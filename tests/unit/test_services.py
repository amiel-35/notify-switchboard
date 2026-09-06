"""Unit tests for the v0.2 UI services, temporary silence and row texts.

The acceptance suite (`tests/acceptance/test_s2_services.py`,
`test_s2_row_texts.py`) pins the contract; this file covers the branches it
does not reach: the voluptuous schemas, each refusal path of the shared
validation helpers, the interaction between the two silence sources, the
`repairs` issue raised on a recurring bad call, service teardown on unload, and
template rendering when the alert is missing or the template is broken.
"""

from __future__ import annotations

from datetime import timedelta
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
    MAX_INVALID_SERVICE_CALLS,
    UI_SERVICES,
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


async def test_services_are_removed_on_unload_and_come_back_on_reload(
    hass: HomeAssistant,
) -> None:
    """No dangling service may survive an unload: its closure holds a dead entry."""
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
        assert not hass.services.has_service(DOMAIN, service)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    for service in UI_SERVICES:
        assert hass.services.has_service(DOMAIN, service)


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
