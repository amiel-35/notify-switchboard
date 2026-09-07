"""Time-to-live on a deferred message (contract v0.5, ADR-0019 §1).

A deferral is a promise that a message is *late*, not that it is eternal. From
0.5.0 a queued message carries a time-to-live, taken from the global
`ttl_minutes` option (defaults: `info` 120, `normal` 720, `high` none) or from
the call's own `data.ttl_minutes`, and a message whose time has run out when
its flush comes is dropped with the new reason `expired` instead of waking
somebody up about something that stopped mattering hours ago.

Time is moved exactly the way the S1 deferral tests move it: `freezer.move_to`
to an absolute UTC instant with the instance pinned to `Europe/Paris`, then
`async_fire_time_changed(hass, dt_util.utcnow())` to let the wake-time timer
fire. Nothing here patches a constant: the defaults are reached by waiting,
which is what makes a red in this file behavioural.
"""

from __future__ import annotations

from datetime import datetime

import homeassistant.util.dt as dt_util
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from .conftest import make_entry, make_person, make_target

# 23:30 Europe/Paris, deep inside the night silence.
NIGHT = datetime(2026, 9, 10, 21, 30, tzinfo=dt_util.UTC)
# 07:05 Europe/Paris the next morning: 7 h 35 min (455 min) after NIGHT.
MORNING = datetime(2026, 9, 11, 5, 5, tzinfo=dt_util.UTC)
# 08:00 Europe/Paris, for a person whose night silence covers the day.
DAY = datetime(2026, 9, 10, 6, 0, tzinfo=dt_util.UTC)
# 07:05 Europe/Paris the following morning: 23 h 5 min (1385 min) after DAY.
NEXT_MORNING = datetime(2026, 9, 11, 5, 5, tzinfo=dt_util.UTC)


def _entry(hass, *, ttl_minutes=None, targets=None):
    """A silenced person with a 07:00 wake time and one or more rows."""
    return make_entry(
        hass,
        persons=[
            make_person(
                "person.alice",
                ["mobile_app_alice"],
                silence_entities=["input_boolean.alice_night"],
                wake_time="07:00:00",
            )
        ],
        targets=targets
        or [make_target("leak", "Leak", audience=["person.alice"])],
        default_target="leak",
        ttl_minutes=ttl_minutes,
    )


async def _wake(hass, freezer, when) -> None:
    """Move to `when`, end the night silence and let the flush run."""
    freezer.move_to(when)
    hass.states.async_set("input_boolean.alice_night", "off")
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done()


async def test_an_info_deferral_expires_while_a_high_one_survives(
    hass, enable_custom_integrations, install, mock_outputs, set_person, freezer,
    drop_reasons,
):
    """The per-priority defaults: `info` 120 min, `high` never.

    Both messages wait 7 h 35 min. The `info` one is long past its default
    time-to-live and must never be delivered; the `high` one has none at all
    and must arrive intact.
    """
    await hass.config.async_set_time_zone("Europe/Paris")
    calls = mock_outputs("mobile_app_alice")
    set_person("person.alice", "home")
    hass.states.async_set("input_boolean.alice_night", "on")

    entry = _entry(
        hass,
        targets=[
            make_target("chatty", "Chatty", audience=["person.alice"]),
            make_target("urgent", "Urgent", audience=["person.alice"]),
        ],
    )
    freezer.move_to(NIGHT)
    await install(entry)

    await hass.services.async_call(
        "notify",
        "switchboard_chatty",
        {"message": "stale news", "data": {"priority": "info"}},
        blocking=True,
    )
    await hass.services.async_call(
        "notify",
        "switchboard_urgent",
        {"message": "still true", "data": {"priority": "high"}},
        blocking=True,
    )
    await hass.async_block_till_done()
    assert len(calls["mobile_app_alice"]) == 0

    await _wake(hass, freezer, MORNING)

    messages = [call.data["message"] for call in calls["mobile_app_alice"]]
    assert messages == ["still true"], (
        "the `info` deferral outlived its 120 min default TTL and must be "
        "dropped, the `high` one has no TTL at all (ADR-0019 §1)"
    )
    assert "expired" in drop_reasons()


async def test_a_normal_deferral_expires_after_its_twelve_hour_default(
    hass, enable_custom_integrations, install, mock_outputs, set_person, freezer,
    drop_reasons, dropped_sensor,
):
    """`normal` defaults to 720 min; this one waits 1385 and must not arrive."""
    await hass.config.async_set_time_zone("Europe/Paris")
    calls = mock_outputs("mobile_app_alice")
    set_person("person.alice", "home")
    hass.states.async_set("input_boolean.alice_night", "on")

    entry = _entry(hass)
    freezer.move_to(DAY)
    await install(entry)

    await hass.services.async_call(
        "notify", "switchboard_leak", {"message": "yesterday morning"}, blocking=True
    )
    await hass.async_block_till_done()
    assert len(calls["mobile_app_alice"]) == 0

    before = dropped_sensor().state
    await _wake(hass, freezer, NEXT_MORNING)

    assert len(calls["mobile_app_alice"]) == 0
    assert "expired" in drop_reasons()
    assert int(dropped_sensor().state) > int(before), (
        "an expired deferral is a drop and is counted like one (ADR-0019 §1)"
    )


async def test_the_global_option_overrides_the_default_for_a_priority(
    hass, enable_custom_integrations, install, mock_outputs, set_person, freezer,
    drop_reasons,
):
    """`ttl_minutes` in the options is what the household chose, not a hint."""
    await hass.config.async_set_time_zone("Europe/Paris")
    calls = mock_outputs("mobile_app_alice")
    set_person("person.alice", "home")
    hass.states.async_set("input_boolean.alice_night", "on")

    # `high` normally never expires; here the household gave it five minutes.
    entry = _entry(hass, ttl_minutes={"high": 5})
    freezer.move_to(NIGHT)
    await install(entry)

    await hass.services.async_call(
        "notify",
        "switchboard_leak",
        {"message": "urgent but stale", "data": {"priority": "high"}},
        blocking=True,
    )
    await hass.async_block_till_done()

    await _wake(hass, freezer, MORNING)

    assert len(calls["mobile_app_alice"]) == 0
    assert "expired" in drop_reasons()


async def test_a_per_call_ttl_overrides_the_option_and_the_default(
    hass, enable_custom_integrations, install, mock_outputs, set_person, freezer,
    drop_reasons,
):
    """`data.ttl_minutes` wins over both the mapping and the priority default."""
    await hass.config.async_set_time_zone("Europe/Paris")
    calls = mock_outputs("mobile_app_alice")
    set_person("person.alice", "home")
    hass.states.async_set("input_boolean.alice_night", "on")

    entry = _entry(hass, ttl_minutes={"high": None})
    freezer.move_to(NIGHT)
    await install(entry)

    await hass.services.async_call(
        "notify",
        "switchboard_leak",
        {
            "message": "good for five minutes",
            "data": {"priority": "high", "ttl_minutes": 5},
        },
        blocking=True,
    )
    await hass.async_block_till_done()

    await _wake(hass, freezer, MORNING)

    assert len(calls["mobile_app_alice"]) == 0
    assert "expired" in drop_reasons()


async def test_a_per_call_ttl_of_zero_means_this_message_never_expires(
    hass, enable_custom_integrations, install, mock_outputs, set_person, freezer,
):
    """`ttl_minutes: 0` is the caller's opt-out, in the other direction.

    Without it this `info` message would be dropped by the 120 min default,
    exactly as the first test in this file asserts.
    """
    await hass.config.async_set_time_zone("Europe/Paris")
    calls = mock_outputs("mobile_app_alice")
    set_person("person.alice", "home")
    hass.states.async_set("input_boolean.alice_night", "on")

    entry = _entry(hass)
    freezer.move_to(NIGHT)
    await install(entry)

    await hass.services.async_call(
        "notify",
        "switchboard_leak",
        {
            "message": "keep this whatever the policy says",
            "data": {"priority": "info", "ttl_minutes": 0},
        },
        blocking=True,
    )
    await hass.async_block_till_done()

    await _wake(hass, freezer, MORNING)

    assert len(calls["mobile_app_alice"]) == 1
    assert (
        calls["mobile_app_alice"][0].data["message"]
        == "keep this whatever the policy says"
    )


async def test_an_expired_deferral_leaves_the_queue(
    hass, enable_custom_integrations, install, mock_outputs, set_person, freezer,
    deferred_sensor,
):
    """An expired message is removed, not held for the following night.

    A second flush the next morning must find nothing left to send: a message
    that expired is gone, not merely skipped.
    """
    await hass.config.async_set_time_zone("Europe/Paris")
    calls = mock_outputs("mobile_app_alice")
    set_person("person.alice", "home")
    hass.states.async_set("input_boolean.alice_night", "on")

    entry = _entry(hass)
    freezer.move_to(NIGHT)
    await install(entry)

    await hass.services.async_call(
        "notify",
        "switchboard_leak",
        {"message": "stale", "data": {"priority": "info"}},
        blocking=True,
    )
    await hass.async_block_till_done()
    assert deferred_sensor().state == "1"

    await _wake(hass, freezer, MORNING)
    assert len(calls["mobile_app_alice"]) == 0

    # The night after: nothing must resurface.
    hass.states.async_set("input_boolean.alice_night", "on")
    await hass.async_block_till_done()
    await _wake(hass, freezer, datetime(2026, 9, 12, 5, 5, tzinfo=dt_util.UTC))
    assert len(calls["mobile_app_alice"]) == 0
