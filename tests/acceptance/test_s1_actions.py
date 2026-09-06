"""Companion buttons, snooze and acknowledge tests (contract §"Buttons and callbacks", ADR-008/009)."""

from __future__ import annotations

from datetime import timedelta

import homeassistant.util.dt as dt_util
from homeassistant.core import Context
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from .conftest import make_entry, make_person, make_target

# ---------------------------------------------------------------------------
# Buttons (brief item 5)
# ---------------------------------------------------------------------------


async def test_buttons_include_acknowledge_and_every_snooze_duration_when_allowed(
    hass, enable_custom_integrations, install, mock_outputs, set_person
):
    calls = mock_outputs("mobile_app_alice")
    set_person("person.alice", "home")

    entry = make_entry(
        hass,
        persons=[make_person("person.alice", ["mobile_app_alice"])],
        targets=[
            make_target(
                "btn_full",
                "Full buttons",
                alert_entity="alert.dummy_full",
                allow_acknowledge=True,
                snooze_minutes=[15, 60],
                audience=["person.alice"],
                default_priority="normal",
            )
        ],
        default_target="btn_full",
    )
    await install(entry)

    await hass.services.async_call(
        "notify", "switchboard_btn_full", {"message": "m"}, blocking=True
    )
    await hass.async_block_till_done()

    assert len(calls["mobile_app_alice"]) == 1
    data = calls["mobile_app_alice"][0].data.get("data", {})
    actions = {action["action"] for action in data.get("actions", [])}
    assert actions == {
        "switchboard:ack:btn_full",
        "switchboard:snooze:btn_full:15",
        "switchboard:snooze:btn_full:60",
    }
    assert data.get("authenticationRequired", False) is False


async def test_buttons_absent_when_row_disallows_acknowledge_and_snooze(
    hass, enable_custom_integrations, install, mock_outputs, set_person
):
    calls = mock_outputs("mobile_app_alice")
    set_person("person.alice", "home")

    entry = make_entry(
        hass,
        persons=[make_person("person.alice", ["mobile_app_alice"])],
        targets=[
            make_target(
                "btn_none",
                "No buttons",
                alert_entity=None,
                allow_acknowledge=False,
                snooze_minutes=[],
                audience=["person.alice"],
                default_priority="normal",
            )
        ],
        default_target="btn_none",
    )
    await install(entry)

    await hass.services.async_call(
        "notify", "switchboard_btn_none", {"message": "m"}, blocking=True
    )
    await hass.async_block_till_done()

    data = calls["mobile_app_alice"][0].data.get("data", {})
    assert not data.get("actions")


async def test_high_and_critical_priority_rows_force_authentication_required(
    hass, enable_custom_integrations, install, mock_outputs, set_person
):
    calls = mock_outputs("mobile_app_alice")
    set_person("person.alice", "home")

    entry = make_entry(
        hass,
        persons=[make_person("person.alice", ["mobile_app_alice"])],
        targets=[
            make_target(
                "btn_high",
                "High priority",
                alert_entity=None,
                allow_acknowledge=False,
                snooze_minutes=[],
                audience=["person.alice"],
                default_priority="high",
            )
        ],
        default_target="btn_high",
    )
    await install(entry)

    await hass.services.async_call(
        "notify", "switchboard_btn_high", {"message": "m"}, blocking=True
    )
    await hass.async_block_till_done()

    data = calls["mobile_app_alice"][0].data.get("data", {})
    assert data.get("authenticationRequired") is True


# ---------------------------------------------------------------------------
# Snooze via Companion callback (brief item 6, contract §"Buttons and callbacks")
# ---------------------------------------------------------------------------


async def test_snooze_action_drops_delivery_then_expires_after_its_duration(
    hass, enable_custom_integrations, install, mock_outputs, set_person, freezer
):
    calls = mock_outputs("mobile_app_alice", "mobile_app_bob")
    set_person("person.alice", "home")
    set_person("person.bob", "home")

    entry = make_entry(
        hass,
        persons=[
            make_person("person.alice", ["mobile_app_alice"]),
            make_person("person.bob", ["mobile_app_bob"]),
        ],
        targets=[
            make_target(
                "leak",
                "Fuite d'eau",
                audience=["person.alice", "person.bob"],
                snooze_minutes=[60],
            )
        ],
        default_target="leak",
    )
    await install(entry)

    # The event's device_id does not resolve to a specific known person (no mobile_app
    # device registry entry was created for it in this test) -- per the brief this
    # ambiguous case snoozes every person in the row's audience. See README
    # "Assumptions" for why the acceptance suite only exercises this documented
    # fallback rather than a specific device -> person mapping.
    hass.bus.async_fire(
        "mobile_app_notification_action",
        {"action": "switchboard:snooze:leak:60", "device_id": "unresolvable-device"},
        context=Context(user_id="test-user"),
    )
    await hass.async_block_till_done()

    await hass.services.async_call(
        "notify", "switchboard_leak", {"message": "still leaking"}, blocking=True
    )
    await hass.async_block_till_done()

    assert len(calls["mobile_app_alice"]) == 0
    assert len(calls["mobile_app_bob"]) == 0

    freezer.tick(timedelta(minutes=61))
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done()

    await hass.services.async_call(
        "notify", "switchboard_leak", {"message": "still leaking 2"}, blocking=True
    )
    await hass.async_block_till_done()

    assert len(calls["mobile_app_alice"]) == 1
    assert len(calls["mobile_app_bob"]) == 1


# ---------------------------------------------------------------------------
# Acknowledge via Companion callback (ADR-009 allow-list)
# ---------------------------------------------------------------------------


async def test_acknowledge_action_turns_off_the_row_alert_when_allowed(
    hass, enable_custom_integrations, install, mock_outputs, set_person
):
    mock_outputs("mobile_app_alice")
    set_person("person.alice", "home")

    entry = make_entry(
        hass,
        persons=[make_person("person.alice", ["mobile_app_alice"])],
        targets=[
            make_target(
                "leak",
                "Fuite d'eau",
                alert_entity="alert.test_leak",
                allow_acknowledge=True,
                audience=["person.alice"],
            )
        ],
        default_target="leak",
    )
    # The router's services must exist before the alert fires, so its `notifiers`
    # call resolves.
    await install(entry)

    assert await async_setup_component(
        hass,
        "alert",
        {
            "alert": {
                "test_leak": {
                    "name": "Fuite d'eau",
                    "entity_id": "binary_sensor.leak_sensor",
                    "state": "on",
                    "repeat": [60],
                    "can_acknowledge": True,
                    "skip_first": False,
                    "notifiers": ["switchboard_leak"],
                }
            }
        },
    )
    await hass.async_block_till_done()

    hass.states.async_set("binary_sensor.leak_sensor", "on")
    await hass.async_block_till_done()

    assert hass.states.get("alert.test_leak").state == "on"

    hass.bus.async_fire(
        "mobile_app_notification_action",
        {"action": "switchboard:ack:leak"},
        context=Context(user_id="test-user"),
    )
    await hass.async_block_till_done()

    assert hass.states.get("alert.test_leak").state == "off"


async def test_acknowledge_is_refused_for_an_alert_not_in_the_routing_table(
    hass, enable_custom_integrations, install, mock_outputs, set_person
):
    mock_outputs("mobile_app_alice")
    set_person("person.alice", "home")

    entry = make_entry(
        hass,
        persons=[make_person("person.alice", ["mobile_app_alice"])],
        targets=[
            make_target(
                "other",
                "Other (no alert linked)",
                alert_entity=None,
                allow_acknowledge=True,
                audience=["person.alice"],
            )
        ],
        default_target="other",
    )
    await install(entry)

    assert await async_setup_component(
        hass,
        "alert",
        {
            "alert": {
                "bystander": {
                    "name": "Bystander alert",
                    "entity_id": "binary_sensor.bystander_sensor",
                    "state": "on",
                    "repeat": [60],
                    "can_acknowledge": True,
                    "skip_first": False,
                    "notifiers": [],
                }
            }
        },
    )
    await hass.async_block_till_done()

    hass.states.async_set("binary_sensor.bystander_sensor", "on")
    await hass.async_block_till_done()
    assert hass.states.get("alert.bystander").state == "on"

    # 1) A slug that exists in the table but has no alert_entity configured.
    hass.bus.async_fire(
        "mobile_app_notification_action",
        {"action": "switchboard:ack:other"},
        context=Context(user_id="test-user"),
    )
    await hass.async_block_till_done()
    assert hass.states.get("alert.bystander").state == "on"

    # 2) A completely forged/unknown slug.
    hass.bus.async_fire(
        "mobile_app_notification_action",
        {"action": "switchboard:ack:totally_unknown_slug"},
        context=Context(user_id="test-user"),
    )
    await hass.async_block_till_done()
    assert hass.states.get("alert.bystander").state == "on"
