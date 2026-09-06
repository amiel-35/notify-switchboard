"""Contract test (ADR-011): public names frozen by docs/notify-switchboard-contract-v0.md.

This is the one test file that mirrors what will become the guarded
`tests/acceptance/test_contract.py` in the real repository. It only checks
existence and shape of the public surface — never internal behaviour (that is
covered by test_s1_*.py).
"""

from __future__ import annotations

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
