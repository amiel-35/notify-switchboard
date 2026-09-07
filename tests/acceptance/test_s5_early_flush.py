"""An early flush when the silence really ends (contract v0.5, ADR-0019 §4).

`docs/known-issues.md` (2026-09-07): "a configured silence entity that goes
`off` well before the wake time does not trigger an early flush either. The
message waits for the wake time, which is the documented promise." The router
was already subscribed to those entities — it just refreshed a binary sensor
and returned.

From 0.5.0 the last active silence entity turning `off` flushes that person's
queue there and then, unless a temporary `notify_switchboard.silence` is still
running. `wake_time` stays the upper bound: nothing waits *longer* than it did.

No timer is fired in the first test on purpose. The delivery must be caused by
the state change alone; an `async_fire_time_changed` would make a lazy
implementation look correct.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import homeassistant.util.dt as dt_util
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from .conftest import make_entry, make_person, make_target

NIGHT = datetime(2026, 9, 10, 21, 30, tzinfo=dt_util.UTC)  # 23:30 Europe/Paris
FIVE_AM = datetime(2026, 9, 11, 3, 0, tzinfo=dt_util.UTC)  # 05:00 Europe/Paris
SEVEN_AM = datetime(2026, 9, 11, 5, 5, tzinfo=dt_util.UTC)  # 07:05 Europe/Paris


def _entry(hass, *, silence_entities=None):
    return make_entry(
        hass,
        persons=[
            make_person(
                "person.alice",
                ["mobile_app_alice"],
                silence_entities=silence_entities or ["input_boolean.alice_night"],
                wake_time="07:00:00",
            )
        ],
        targets=[make_target("leak", "Leak", audience=["person.alice"])],
        default_target="leak",
    )


async def test_the_last_silence_entity_going_off_flushes_before_the_wake_time(
    hass, enable_custom_integrations, install, mock_outputs, set_person, freezer
):
    """05:00: the night schedule ends two hours early, and so does the queue."""
    await hass.config.async_set_time_zone("Europe/Paris")
    calls = mock_outputs("mobile_app_alice")
    set_person("person.alice", "home")
    hass.states.async_set("input_boolean.alice_night", "on")

    freezer.move_to(NIGHT)
    await install(_entry(hass))

    await hass.services.async_call(
        "notify", "switchboard_leak", {"message": "queued at 23:30"}, blocking=True
    )
    await hass.async_block_till_done()
    assert len(calls["mobile_app_alice"]) == 0

    freezer.move_to(FIVE_AM)
    hass.states.async_set("input_boolean.alice_night", "off")
    await hass.async_block_till_done()

    assert len(calls["mobile_app_alice"]) == 1, (
        "the router is already subscribed to this entity; when the last "
        "active silence lifts, the queue goes out (ADR-0019 §4)"
    )
    assert calls["mobile_app_alice"][0].data["message"] == "queued at 23:30"


async def test_an_early_flush_does_not_deliver_twice_at_the_wake_time(
    hass, enable_custom_integrations, install, mock_outputs, set_person, freezer
):
    """`wake_time` is an upper bound, not a second delivery."""
    await hass.config.async_set_time_zone("Europe/Paris")
    calls = mock_outputs("mobile_app_alice")
    set_person("person.alice", "home")
    hass.states.async_set("input_boolean.alice_night", "on")

    freezer.move_to(NIGHT)
    await install(_entry(hass))

    await hass.services.async_call(
        "notify", "switchboard_leak", {"message": "only once"}, blocking=True
    )
    await hass.async_block_till_done()

    freezer.move_to(FIVE_AM)
    hass.states.async_set("input_boolean.alice_night", "off")
    await hass.async_block_till_done()
    assert len(calls["mobile_app_alice"]) == 1

    freezer.move_to(SEVEN_AM)
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done()

    assert len(calls["mobile_app_alice"]) == 1


async def test_no_early_flush_while_a_temporary_silence_is_still_running(
    hass, enable_custom_integrations, install, mock_outputs, set_person, freezer
):
    """A `notify_switchboard.silence` is a silence too, and it holds the queue."""
    await hass.config.async_set_time_zone("Europe/Paris")
    calls = mock_outputs("mobile_app_alice")
    set_person("person.alice", "home")
    hass.states.async_set("input_boolean.alice_night", "on")

    freezer.move_to(NIGHT)
    await install(_entry(hass))

    await hass.services.async_call(
        "notify", "switchboard_leak", {"message": "queued at 23:30"}, blocking=True
    )
    await hass.async_block_till_done()

    # 04:00: somebody asks for two more hours of quiet, in so many words.
    freezer.move_to(FIVE_AM - timedelta(hours=1))
    await hass.services.async_call(
        "notify_switchboard",
        "silence",
        {"person": "person.alice", "minutes": 180},
        blocking=True,
    )
    await hass.async_block_till_done()

    freezer.move_to(FIVE_AM)
    hass.states.async_set("input_boolean.alice_night", "off")
    await hass.async_block_till_done()

    assert len(calls["mobile_app_alice"]) == 0, (
        "the configured schedule is over but the person is still silenced by "
        "the router's own temporary silence: no early flush (ADR-0019 §4)"
    )


async def test_no_early_flush_while_another_silence_entity_is_still_on(
    hass, enable_custom_integrations, install, mock_outputs, set_person, freezer
):
    """ "The **last** active one": a person with two sources needs both off.

    The first half is the line an over-eager implementation of §4 crosses
    first — one of two silences lifting is not the end of a night. The second
    half is §4 itself, and is red until it exists.
    """
    await hass.config.async_set_time_zone("Europe/Paris")
    calls = mock_outputs("mobile_app_alice")
    set_person("person.alice", "home")
    hass.states.async_set("input_boolean.alice_night", "on")
    hass.states.async_set("binary_sensor.alice_focus", "on")

    freezer.move_to(NIGHT)
    await install(
        _entry(
            hass,
            silence_entities=[
                "input_boolean.alice_night",
                "binary_sensor.alice_focus",
            ],
        )
    )

    await hass.services.async_call(
        "notify", "switchboard_leak", {"message": "queued at 23:30"}, blocking=True
    )
    await hass.async_block_till_done()

    freezer.move_to(FIVE_AM)
    hass.states.async_set("input_boolean.alice_night", "off")
    await hass.async_block_till_done()
    assert len(calls["mobile_app_alice"]) == 0, (
        "the Focus sensor is still on, so the night is not over for this person"
    )

    hass.states.async_set("binary_sensor.alice_focus", "off")
    await hass.async_block_till_done()
    assert len(calls["mobile_app_alice"]) == 1
