"""Routing decision tests (contract §"Routing decision", brief items 3-4-10)."""

from __future__ import annotations

import homeassistant.helpers.issue_registry as ir
import pytest
from homeassistant.exceptions import HomeAssistantError

from custom_components.notify_switchboard.const import (
    ATTR_PRIORITY,
    ATTR_SOURCE_ENTITY,
    DOMAIN,
)

from .conftest import make_entry, make_person, make_target


async def test_home_only_routes_to_present_person_and_skips_absent_one(
    hass, enable_custom_integrations, install, mock_outputs, set_person
):
    """presence_rule=home_only: only the person whose person.* state is 'home' is notified."""
    calls = mock_outputs("mobile_app_alice", "mobile_app_bob")
    set_person("person.alice", "home")
    set_person("person.bob", "not_home")

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
                presence_rule="home_only",
                default_data={"channel": "family"},
            )
        ],
        default_target="leak",
    )
    await install(entry)

    await hass.services.async_call(
        "notify",
        "switchboard_leak",
        {
            "message": "De l'eau sous l'évier",
            "title": "Alerte",
            "data": {
                "tag": "t1",
                "channel": "override",
                ATTR_SOURCE_ENTITY: "sensor.leak_kitchen",
            },
        },
        blocking=True,
    )
    await hass.async_block_till_done()

    assert len(calls["mobile_app_alice"]) == 1
    assert len(calls["mobile_app_bob"]) == 0

    call = calls["mobile_app_alice"][0]
    assert call.data["message"] == "De l'eau sous l'évier"
    assert call.data["title"] == "Alerte"
    # caller data wins over the row's default_data on conflicting keys
    assert call.data["data"]["channel"] == "override"
    assert call.data["data"]["tag"] == "t1"
    # data.source_entity (contract §"Input") is passed through to the output
    assert call.data["data"][ATTR_SOURCE_ENTITY] == "sensor.leak_kitchen"


async def test_away_only_routes_to_absent_person_and_skips_present_one(
    hass, enable_custom_integrations, install, mock_outputs, set_person
):
    """presence_rule=away_only is the mirror image of home_only."""
    calls = mock_outputs("mobile_app_alice", "mobile_app_bob")
    set_person("person.alice", "home")
    set_person("person.bob", "not_home")

    entry = make_entry(
        hass,
        persons=[
            make_person("person.alice", ["mobile_app_alice"]),
            make_person("person.bob", ["mobile_app_bob"]),
        ],
        targets=[
            make_target(
                "away_reminder",
                "Rappel absence",
                audience=["person.alice", "person.bob"],
                presence_rule="away_only",
            )
        ],
        default_target="away_reminder",
    )
    await install(entry)

    await hass.services.async_call(
        "notify",
        "switchboard_away_reminder",
        {"message": "N'oublie pas les clés", "title": "Rappel"},
        blocking=True,
    )
    await hass.async_block_till_done()

    assert len(calls["mobile_app_alice"]) == 0
    assert len(calls["mobile_app_bob"]) == 1


async def test_failing_output_does_not_prevent_other_persons_from_being_notified(
    hass, enable_custom_integrations, install, mock_outputs, set_person
):
    """Contract §"Output": a failing output never prevents other outputs or persons."""
    failing_calls = mock_outputs(
        "mobile_app_alice", raise_exception=HomeAssistantError("boom")
    )
    ok_calls = mock_outputs("mobile_app_bob")
    calls = {**failing_calls, **ok_calls}

    set_person("person.alice", "home")
    set_person("person.bob", "home")

    entry = make_entry(
        hass,
        persons=[
            make_person("person.alice", ["mobile_app_alice"]),
            make_person("person.bob", ["mobile_app_bob"]),
        ],
        targets=[
            make_target("leak", "Fuite d'eau", audience=["person.alice", "person.bob"])
        ],
        default_target="leak",
    )
    await install(entry)

    # Must not raise even though alice's output raises internally.
    await hass.services.async_call(
        "notify",
        "switchboard_leak",
        {"message": "De l'eau sous l'évier"},
        blocking=True,
    )
    await hass.async_block_till_done()

    assert len(calls["mobile_app_alice"]) == 1  # it was called (and raised)
    assert len(calls["mobile_app_bob"]) == 1  # bob still got it


@pytest.mark.timeout(10)
async def test_output_pointing_back_to_switchboard_is_rejected_as_recursion(
    hass, enable_custom_integrations, install, mock_outputs, set_person, dropped_sensor
):
    """Contract §"Output": recursion (an output resolving to notify.switchboard*) is rejected at runtime."""
    mock_outputs("mobile_app_alice")
    set_person("person.eve", "home")

    entry = make_entry(
        hass,
        persons=[
            # Eve's "output" is itself a switchboard service: must be rejected, not looped into.
            make_person("person.eve", ["switchboard_loop"]),
        ],
        targets=[make_target("loop", "Loop", audience=["person.eve"])],
        default_target="loop",
    )
    await install(entry)

    await hass.services.async_call(
        "notify",
        "switchboard_loop",
        {"message": "should not recurse"},
        blocking=True,
    )
    await hass.async_block_till_done()

    dropped = dropped_sensor()
    assert dropped is not None
    assert int(dropped.state) >= 1
    assert "recursion" in dropped.attributes["reasons"]


async def test_unknown_target_is_dropped_and_raises_one_repairs_issue(
    hass, enable_custom_integrations, install, mock_outputs, set_person, dropped_sensor
):
    """Contract §"Input": unknown <target> is dropped (reason unknown_target) and raises a repairs issue once."""
    mock_outputs("mobile_app_alice")
    set_person("person.alice", "home")

    entry = make_entry(
        hass,
        persons=[make_person("person.alice", ["mobile_app_alice"])],
        targets=[make_target("leak", "Fuite d'eau", audience=["person.alice"])],
        default_target="leak",
    )
    await install(entry)

    await hass.services.async_call(
        "notify",
        "switchboard",
        {"message": "ghost", "target": ["does_not_exist"]},
        blocking=True,
    )
    await hass.async_block_till_done()

    dropped = dropped_sensor()
    assert dropped is not None
    assert "unknown_target" in dropped.attributes["reasons"]

    registry = ir.async_get(hass)
    domain_issues = [
        issue for issue in registry.issues.values() if issue.domain == DOMAIN
    ]
    assert len(domain_issues) >= 1


async def test_default_priority_can_be_overridden_by_caller_data_priority(
    hass, enable_custom_integrations, install, mock_outputs, set_person
):
    """data.priority overrides the target's default_priority (contract §"Input")."""
    calls = mock_outputs("mobile_app_alice")
    set_person("person.alice", "home")

    entry = make_entry(
        hass,
        persons=[
            make_person(
                "person.alice",
                ["mobile_app_alice"],
                silence_entities=["input_boolean.alice_silence"],
            )
        ],
        targets=[
            make_target(
                "leak",
                "Fuite d'eau",
                audience=["person.alice"],
                default_priority="normal",
            )
        ],
        default_target="leak",
    )
    hass.states.async_set("input_boolean.alice_silence", "on")
    await install(entry)

    # Without an override, "normal" priority does not bypass silence -> dropped.
    await hass.services.async_call(
        "notify", "switchboard_leak", {"message": "m1"}, blocking=True
    )
    await hass.async_block_till_done()
    assert len(calls["mobile_app_alice"]) == 0

    # data.priority: critical overrides the row's default and bypasses silence.
    await hass.services.async_call(
        "notify",
        "switchboard_leak",
        {"message": "m2", "data": {ATTR_PRIORITY: "critical"}},
        blocking=True,
    )
    await hass.async_block_till_done()
    assert len(calls["mobile_app_alice"]) == 1
