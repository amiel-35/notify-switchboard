"""Contract test (ADR-011, extended by ADR-0016): public names frozen by
docs/contract.md.

This is the one test file that mirrors what will become the guarded
`tests/acceptance/test_contract.py` in the real repository. It only checks
existence and shape of the public surface — never internal behaviour (that is
covered by test_s1_*.py / test_s2_*.py).

Extended for the v0.2 addendum (ADR-0016): the contract change that sprint
explicitly authorized was adding the five `notify_switchboard.*` UI services,
so this file is allowed to grow an assertion that they exist after setup —
the same discipline that guards the v0 names.

Extended again for the v0.3 addendum (ADR-0017): the two changes that sprint
authorized are `sensor.switchboard_deferred_today` entering the frozen names,
and the frozen entity ids being frozen *in every instance language* — `fr`
and `es` are `NATIVE_ENTITY_IDS` languages, so translating the entity names
without care renames the ids on exactly those instances.

Extended once more for the v0.4 addendum (ADR-0018): the change that sprint
authorized is a sixth, read-only service, `notify_switchboard.explain`. Its
name, its `SupportsResponse.ONLY` declaration and the keys of its response are
public surface — a card and a template are written against them — so they are
guarded here alongside the v0 names. What each key *means* is
`test_s4_explain.py`'s business, not this file's.

Extended a fourth time for the v0.5 addendum (ADR-0019): two more drop
reasons (`expired`, `not_notified`), the `data` keys `ttl_minutes` and
`switchboard_done`, and the default `tag` / `notification_id` a message
carries when the caller supplies none. Public strings, all of them: an
automation filters on a reason, a Companion channel filters on a tag. The four
`event.switchboard_delivery` event types are asserted, unchanged, by
`test_services_and_entities_exist_after_setup` above — v0.5 adds reasons, not
types. What each rule *does* is `test_s5_*.py`'s business.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import homeassistant.util.dt as dt_util
import pytest
from homeassistant.core import SupportsResponse
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.notify_switchboard.const import DOMAIN

from .conftest import make_entry, make_person, make_target


async def test_services_and_entities_exist_after_setup(
    hass, enable_custom_integrations, install
):
    """After setup: notify.switchboard, notify.switchboard_<slug> per row, event and global/per-person entities."""
    persons = [
        make_person("person.alice", ["mobile_app_alice"]),
        make_person("person.bob", ["mobile_app_bob"]),
    ]
    targets = [
        make_target("leak", "Fuite d'eau", audience=["person.alice", "person.bob"]),
        make_target("garage", "Garage", audience=["person.alice"]),
    ]
    entry = make_entry(hass, persons=persons, targets=targets, default_target="leak")

    await install(entry)

    # --- legacy notify services (contract §"Names") ---
    assert hass.services.has_service("notify", "switchboard")
    assert hass.services.has_service("notify", "switchboard_leak")
    assert hass.services.has_service("notify", "switchboard_garage")

    # --- event entity with fixed event_types ---
    event_state = hass.states.get("event.switchboard_delivery")
    assert event_state is not None
    assert set(event_state.attributes["event_types"]) == {
        "routed",
        "dropped",
        "acknowledged",
        "snoozed",
    }

    # --- global diagnostic entities ---
    assert hass.states.get("sensor.switchboard_routed_today") is not None
    assert hass.states.get("sensor.switchboard_dropped_today") is not None
    # v0.3 addendum (ADR-0017): the deferral counter is a frozen name too.
    assert hass.states.get("sensor.switchboard_deferred_today") is not None

    # --- per-person entities (contract §3.5) ---
    for person_slug in ("alice", "bob"):
        assert hass.states.get(f"binary_sensor.{person_slug}_silenced") is not None
        assert hass.states.get(f"sensor.{person_slug}_last_notification") is not None
        assert hass.states.get(f"sensor.{person_slug}_active_snoozes") is not None


async def test_notify_entity_degraded_path_exists(
    hass, enable_custom_integrations, install
):
    """The NotifyEntity degraded path (`notify.switchboard` entity) exists alongside the legacy service."""
    entry = make_entry(
        hass,
        persons=[make_person("person.alice", ["mobile_app_alice"])],
        targets=[make_target("default", "Default", audience=["person.alice"])],
        default_target="default",
    )

    await install(entry)

    notify_entity_state = hass.states.get("notify.switchboard")
    assert notify_entity_state is not None
    assert hass.services.has_service("notify", "send_message")


async def test_domain_is_notify_switchboard() -> None:
    """The integration domain must never change without a major version (ADR-011)."""
    assert DOMAIN == "notify_switchboard"


async def test_ui_services_exist_after_setup(hass, enable_custom_integrations, install):
    """v0.2 addendum (ADR-0016): the five UI services are registered after setup."""
    entry = make_entry(
        hass,
        persons=[make_person("person.alice", ["mobile_app_alice"])],
        targets=[make_target("leak", "Fuite d'eau", audience=["person.alice"])],
        default_target="leak",
    )

    await install(entry)

    for service in ("acknowledge", "snooze", "unsnooze", "silence", "unsilence"):
        assert hass.services.has_service(DOMAIN, service), (
            f"{DOMAIN}.{service} must exist after setup (contract v0.2, ADR-0016)"
        )


# v0.3 addendum (ADR-0017): the frozen names are frozen in every language.
FROZEN_ENTITY_IDS = (
    "binary_sensor.alice_silenced",
    "event.switchboard_delivery",
    "sensor.alice_active_snoozes",
    "sensor.alice_last_notification",
    "sensor.switchboard_deferred_today",
    "sensor.switchboard_dropped_today",
    "sensor.switchboard_routed_today",
)


@pytest.mark.parametrize("language", ["fr", "es", "en"])
async def test_frozen_entity_ids_do_not_depend_on_the_instance_language(
    hass, enable_custom_integrations, install, language
):
    """v0.3 addendum (ADR-0017): translated names, English ids, in any language."""
    hass.config.language = language
    entry = make_entry(
        hass,
        persons=[make_person("person.alice", ["mobile_app_alice"])],
        targets=[make_target("leak", "Leak", audience=["person.alice"])],
        default_target="leak",
    )

    await install(entry)

    for entity_id in FROZEN_ENTITY_IDS:
        assert hass.states.get(entity_id) is not None, (
            f"{entity_id} is a frozen public name and must exist verbatim on "
            f"a '{language}' instance (docs/contract.md, ADR-0011/ADR-0017)"
        )


# ---------------------------------------------------------------------------
# v0.4 addendum (ADR-0018): the read-only service and its response keys
# ---------------------------------------------------------------------------

EXPLAIN_RESPONSE_KEYS = {"target", "priority", "persons"}
EXPLAIN_PERSON_KEYS = {
    "decision",
    "until",
    "reason",
    "detail",
    "outputs",
    "missing_outputs",
}


async def test_explain_service_exists_and_only_answers(
    hass, enable_custom_integrations, install
):
    """v0.4 addendum (ADR-0018): a sixth service, declared `SupportsResponse.ONLY`."""
    entry = make_entry(
        hass,
        persons=[make_person("person.alice", ["mobile_app_alice"])],
        targets=[make_target("leak", "Leak", audience=["person.alice"])],
        default_target="leak",
    )

    await install(entry)

    assert hass.services.has_service(DOMAIN, "explain"), (
        f"{DOMAIN}.explain must exist after setup (contract v0.4, ADR-0018)"
    )
    assert (
        hass.services.supports_response(DOMAIN, "explain") is SupportsResponse.ONLY
    ), (
        "`explain` answers and never acts, so it is registered "
        "`SupportsResponse.ONLY` (contract v0.4)"
    )


async def test_explain_response_carries_exactly_the_frozen_keys(
    hass, enable_custom_integrations, install, mock_outputs
):
    """The response shape is public surface: a card is written against it."""
    mock_outputs("mobile_app_alice")
    entry = make_entry(
        hass,
        persons=[make_person("person.alice", ["mobile_app_alice"])],
        targets=[make_target("leak", "Leak", audience=["person.alice"])],
        default_target="leak",
    )
    await install(entry)

    response = await hass.services.async_call(
        DOMAIN, "explain", {"target": "leak"}, blocking=True, return_response=True
    )

    assert set(response) == EXPLAIN_RESPONSE_KEYS
    assert set(response["persons"]) == {"person.alice"}, (
        "`persons` is a mapping keyed by the `person.*` entity id (contract v0.4)"
    )
    assert set(response["persons"]["person.alice"]) == EXPLAIN_PERSON_KEYS


# ---------------------------------------------------------------------------
# v0.5 addendum (ADR-0019): two drop reasons, two `data` keys, one tag scheme
# ---------------------------------------------------------------------------

NIGHT = datetime(2026, 9, 10, 21, 30, tzinfo=dt_util.UTC)  # 23:30 Europe/Paris
MORNING = datetime(2026, 9, 11, 5, 5, tzinfo=dt_util.UTC)  # 07:05 Europe/Paris


async def test_expired_is_a_drop_reason_and_data_ttl_minutes_produces_it(
    hass, enable_custom_integrations, install, mock_outputs, set_person, freezer
):
    """`data.ttl_minutes` is a public input key; `expired` is a public reason."""
    await hass.config.async_set_time_zone("Europe/Paris")
    calls = mock_outputs("mobile_app_alice")
    set_person("person.alice", "home")
    hass.states.async_set("input_boolean.alice_night", "on")

    entry = make_entry(
        hass,
        persons=[
            make_person(
                "person.alice",
                ["mobile_app_alice"],
                silence_entities=["input_boolean.alice_night"],
                wake_time="07:00:00",
            )
        ],
        targets=[make_target("leak", "Leak", audience=["person.alice"])],
        default_target="leak",
    )
    freezer.move_to(NIGHT)
    await install(entry)

    await hass.services.async_call(
        "notify",
        "switchboard_leak",
        {"message": "good for a minute", "data": {"ttl_minutes": 1}},
        blocking=True,
    )
    await hass.async_block_till_done()

    freezer.move_to(MORNING)
    hass.states.async_set("input_boolean.alice_night", "off")
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done()

    assert len(calls["mobile_app_alice"]) == 0
    reasons = hass.states.get("sensor.switchboard_dropped_today").attributes["reasons"]
    assert "expired" in reasons, (
        "`expired` joins the frozen drop reasons in v0.5 (ADR-0019 §1)"
    )


async def test_not_notified_is_a_drop_reason_and_switchboard_done_produces_it(
    hass, enable_custom_integrations, install, mock_outputs, set_person, real_alert
):
    """`data.switchboard_done` is a public input key; `not_notified` a public reason."""
    calls = mock_outputs("mobile_app_alice")
    set_person("person.alice", "home")
    hass.states.async_set("input_boolean.alice_night", "on")

    entry = make_entry(
        hass,
        persons=[
            make_person(
                "person.alice",
                ["mobile_app_alice"],
                silence_entities=["input_boolean.alice_night"],
            )
        ],
        targets=[
            make_target(
                "leak", "Leak", alert_entity="alert.leak", audience=["person.alice"]
            )
        ],
        default_target="leak",
    )
    alert = await real_alert("leak")
    await install(entry)

    # An episode Alice sleeps through: she is silenced, so she is told nothing.
    await alert.begin()
    await hass.services.async_call(
        "notify", "switchboard_leak", {"message": "Leak!"}, blocking=True
    )
    await hass.async_block_till_done()
    assert len(calls["mobile_app_alice"]) == 0

    await alert.end()
    await hass.services.async_call(
        "notify",
        "switchboard_leak",
        {"message": "All good", "data": {"switchboard_done": True}},
        blocking=True,
    )
    await hass.async_block_till_done()

    assert len(calls["mobile_app_alice"]) == 0
    reasons = hass.states.get("sensor.switchboard_dropped_today").attributes["reasons"]
    assert "not_notified" in reasons, (
        "`not_notified` joins the frozen drop reasons in v0.5 (ADR-0019 §5)"
    )


async def test_the_default_tag_and_notification_id_are_the_documented_values(
    hass, enable_custom_integrations, install, mock_outputs, set_person
):
    """`switchboard-<slug>` on every message, mirrored as the id in the UI."""
    calls = mock_outputs("mobile_app_alice", "persistent_notification")
    set_person("person.alice", "home")

    entry = make_entry(
        hass,
        persons=[
            make_person("person.alice", ["mobile_app_alice", "persistent_notification"])
        ],
        targets=[make_target("leak", "Leak", audience=["person.alice"])],
        default_target="leak",
    )
    await install(entry)

    await hass.services.async_call(
        "notify", "switchboard_leak", {"message": "m"}, blocking=True
    )
    await hass.async_block_till_done()

    assert calls["mobile_app_alice"][0].data["data"]["tag"] == "switchboard-leak"
    ui = calls["persistent_notification"][0].data["data"]
    assert ui["tag"] == "switchboard-leak"
    assert ui["notification_id"] == "switchboard-leak"


async def test_the_summary_tag_is_a_frozen_value(
    hass, enable_custom_integrations, install, mock_outputs, set_person, freezer
):
    """`switchboard-summary` is public: a Companion channel may key on it."""
    await hass.config.async_set_time_zone("Europe/Paris")
    calls = mock_outputs("mobile_app_alice")
    set_person("person.alice", "home")
    hass.states.async_set("input_boolean.alice_night", "on")

    entry = make_entry(
        hass,
        persons=[
            make_person(
                "person.alice",
                ["mobile_app_alice"],
                silence_entities=["input_boolean.alice_night"],
                wake_time="07:00:00",
            )
        ],
        targets=[
            make_target("a", "A", audience=["person.alice"]),
            make_target("b", "B", audience=["person.alice"]),
        ],
        default_target="a",
    )
    freezer.move_to(NIGHT)
    await install(entry)

    for slug in ("a", "b"):
        await hass.services.async_call(
            "notify", f"switchboard_{slug}", {"message": slug}, blocking=True
        )
        await hass.async_block_till_done()
        freezer.tick(timedelta(minutes=1))

    freezer.move_to(MORNING)
    hass.states.async_set("input_boolean.alice_night", "off")
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done()

    assert len(calls["mobile_app_alice"]) == 1
    assert calls["mobile_app_alice"][0].data["data"]["tag"] == "switchboard-summary"
