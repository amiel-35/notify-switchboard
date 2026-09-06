"""Observer mode and night deferral tests (brief items 7-8, doctrine §3.1 "plan B").

Observer mode note (see README "Assumptions / contract ambiguities"): the
real `alert` entity in home-assistant-core 2026.9.1
(`homeassistant/components/alert/entity.py`) exposes no `message` or
`done_message` state attribute at all -- those are only used internally to
render text sent to `notifiers`. Since the brief explicitly says the router
must read the alert's "message attribute" / "done_message attribute", these
tests drive a synthetic `alert.*`-shaped entity_id directly with
`hass.states.async_set(..., attributes={...})` rather than the real `alert`
platform, so both branches (attribute present / absent) are reachable
deterministically. The real `alert` platform IS used in
`test_s1_actions.py` for the acknowledge scenario, where the message
attribute is irrelevant.
"""

from __future__ import annotations

from datetime import datetime

import homeassistant.util.dt as dt_util
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from .conftest import make_entry, make_person, make_target

# ---------------------------------------------------------------------------
# Observer mode (brief item 8)
# ---------------------------------------------------------------------------


async def test_observer_mode_routes_alert_message_attribute_on_idle_to_on(
    hass, enable_custom_integrations, install, mock_outputs, set_person
):
    calls = mock_outputs("mobile_app_alice")
    set_person("person.alice", "home")

    entry = make_entry(
        hass,
        persons=[make_person("person.alice", ["mobile_app_alice"])],
        targets=[
            make_target(
                "observed",
                "Observed target",
                alert_entity="alert.observer_test",
                observer_mode=True,
                audience=["person.alice"],
            )
        ],
        default_target="observed",
    )
    await install(entry)

    hass.states.async_set("alert.observer_test", "idle")
    await hass.async_block_till_done()

    hass.states.async_set("alert.observer_test", "on", {"message": "Fuite détectée !"})
    await hass.async_block_till_done()

    assert len(calls["mobile_app_alice"]) == 1
    assert calls["mobile_app_alice"][0].data["message"] == "Fuite détectée !"


async def test_observer_mode_falls_back_to_row_name_when_message_attribute_absent(
    hass, enable_custom_integrations, install, mock_outputs, set_person
):
    calls = mock_outputs("mobile_app_alice")
    set_person("person.alice", "home")

    entry = make_entry(
        hass,
        persons=[make_person("person.alice", ["mobile_app_alice"])],
        targets=[
            make_target(
                "observed",
                "Observed target",
                alert_entity="alert.observer_test",
                observer_mode=True,
                audience=["person.alice"],
            )
        ],
        default_target="observed",
    )
    await install(entry)

    hass.states.async_set("alert.observer_test", "idle")
    await hass.async_block_till_done()

    hass.states.async_set("alert.observer_test", "on")  # no "message" attribute
    await hass.async_block_till_done()

    assert len(calls["mobile_app_alice"]) == 1
    assert calls["mobile_app_alice"][0].data["message"] == "Observed target"


async def test_observer_mode_routes_done_message_on_return_to_idle(
    hass, enable_custom_integrations, install, mock_outputs, set_person
):
    calls = mock_outputs("mobile_app_alice")
    set_person("person.alice", "home")

    entry = make_entry(
        hass,
        persons=[make_person("person.alice", ["mobile_app_alice"])],
        targets=[
            make_target(
                "observed",
                "Observed target",
                alert_entity="alert.observer_test",
                observer_mode=True,
                audience=["person.alice"],
            )
        ],
        default_target="observed",
    )
    await install(entry)

    hass.states.async_set("alert.observer_test", "idle")
    await hass.async_block_till_done()
    hass.states.async_set("alert.observer_test", "on", {"message": "Fuite détectée !"})
    await hass.async_block_till_done()
    assert len(calls["mobile_app_alice"]) == 1

    hass.states.async_set(
        "alert.observer_test", "idle", {"done_message": "Tout est revenu à la normale"}
    )
    await hass.async_block_till_done()

    assert len(calls["mobile_app_alice"]) == 2
    assert (
        calls["mobile_app_alice"][1].data["message"] == "Tout est revenu à la normale"
    )


async def test_observer_mode_stops_without_routing_when_alert_transitions_to_off(
    hass, enable_custom_integrations, install, mock_outputs, set_person
):
    """Contract: observer mode "stops on on -> off" (acknowledged), unlike on -> idle."""
    calls = mock_outputs("mobile_app_alice")
    set_person("person.alice", "home")

    entry = make_entry(
        hass,
        persons=[make_person("person.alice", ["mobile_app_alice"])],
        targets=[
            make_target(
                "observed",
                "Observed target",
                alert_entity="alert.observer_test",
                observer_mode=True,
                audience=["person.alice"],
            )
        ],
        default_target="observed",
    )
    await install(entry)

    hass.states.async_set("alert.observer_test", "idle")
    await hass.async_block_till_done()
    hass.states.async_set("alert.observer_test", "on", {"message": "Fuite détectée !"})
    await hass.async_block_till_done()
    assert len(calls["mobile_app_alice"]) == 1

    hass.states.async_set("alert.observer_test", "off")  # acknowledged while firing
    await hass.async_block_till_done()

    assert len(calls["mobile_app_alice"]) == 1  # unchanged: no done message routed


# ---------------------------------------------------------------------------
# Night deferral (brief item 7)
# ---------------------------------------------------------------------------


async def test_night_deferral_delivers_once_at_wake_time_deduped_by_tag(
    hass, enable_custom_integrations, install, mock_outputs, set_person, freezer
):
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
        targets=[make_target("leak", "Fuite d'eau", audience=["person.alice"])],
        default_target="leak",
    )

    freezer.move_to(
        datetime(2026, 9, 10, 21, 30, tzinfo=dt_util.UTC)
    )  # 23:30 Europe/Paris
    await install(entry)

    await hass.services.async_call(
        "notify",
        "switchboard_leak",
        {"message": "first", "data": {"tag": "t1"}},
        blocking=True,
    )
    await hass.async_block_till_done()
    assert (
        len(calls["mobile_app_alice"]) == 0
    )  # silenced -> queued, not dropped forever

    await hass.services.async_call(
        "notify",
        "switchboard_leak",
        {"message": "second", "data": {"tag": "t1"}},
        blocking=True,
    )
    await hass.async_block_till_done()
    assert len(calls["mobile_app_alice"]) == 0

    freezer.move_to(
        datetime(2026, 9, 11, 5, 5, tzinfo=dt_util.UTC)
    )  # 07:05 Europe/Paris
    hass.states.async_set(
        "input_boolean.alice_night", "off"
    )  # schedule ends at wake_time
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done()

    # Exactly one delivery, and it is the latest of the two deduped-by-tag messages.
    assert len(calls["mobile_app_alice"]) == 1
    assert calls["mobile_app_alice"][0].data["message"] == "second"


async def test_night_deferral_delivers_at_correct_local_time_across_dst_change(
    hass, enable_custom_integrations, install, mock_outputs, set_person, freezer
):
    """2026-10-25 is when Europe/Paris falls back from CEST to CET."""
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
        targets=[make_target("leak", "Fuite d'eau", audience=["person.alice"])],
        default_target="leak",
    )

    # 23:30 Europe/Paris on 2026-10-24 (still CEST, UTC+2).
    freezer.move_to(datetime(2026, 10, 24, 21, 30, tzinfo=dt_util.UTC))
    await install(entry)

    await hass.services.async_call(
        "notify",
        "switchboard_leak",
        {"message": "before dst", "data": {"tag": "t2"}},
        blocking=True,
    )
    await hass.async_block_till_done()
    assert len(calls["mobile_app_alice"]) == 0

    # 07:05 Europe/Paris on 2026-10-25, AFTER the fall-back to CET (UTC+1) at 03:00 local.
    freezer.move_to(datetime(2026, 10, 25, 6, 5, tzinfo=dt_util.UTC))
    hass.states.async_set("input_boolean.alice_night", "off")
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done()

    assert len(calls["mobile_app_alice"]) == 1
    assert calls["mobile_app_alice"][0].data["message"] == "before dst"
