"""Escalation after N minutes — a wider audience, on core's clock and no other.

Written before the Sprint 6 implementation exists, against:

- `docs/contract.md` §"v0.6 addendum (ADR-0020)" → "Escalation after N minutes"
- `docs/ADR/0020-bounded-declarative-escalation.md` §0 and §2
- `docs/sprints/sprint-6-brief.md` item 2

This is the file the sprint's guard-rail is really about. "Twenty minutes after
the alert started, if nobody acknowledged, tell the second person" reads like
an `async_call_later`, and it must not be one: the router evaluates the rule
**when it is called**, from the episode's start time and the alert's current
state, and the thing that calls it repeatedly is the alert's own `repeat`.

None of the tests below fires a router timer, because there is none to fire.
Two conditions are read from things that already exist:

- the episode's start — ADR-0019 §5's record, which gains a `started_at`;
- "nobody acknowledged" — the `alert.*` being in state `on`. Core's
  `AlertEntity.state` (`$HA_CORE_SRC/homeassistant/components/alert/entity.py`)
  returns `on` while `_firing and not _ack`, `off` while `_firing and _ack`,
  and `alert.turn_off` — what this integration's own Acknowledge button
  calls — sets `_ack`. So an acknowledged alert reads `off`, and one state
  string answers the question with no bookkeeping of ours.

Every test that calls `begin()` also calls `end()`, so that `end_alerting`
cancels core's repeat and no test here needs an `expected_lingering_timers`
override (`tests/conftest.py`).
"""

from __future__ import annotations

from datetime import datetime, timedelta

from freezegun import freeze_time
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from .conftest import explain, make_entry, make_person, make_target

# An absolute instant, so "the episode is 25 minutes old" is arithmetic rather
# than a race with the suite's own runtime.
T0 = datetime(2026, 9, 10, 12, 0, tzinfo=dt_util.UTC)

AFTER_MINUTES = 20


def _entry(
    hass,
    *,
    after_minutes: int | None = AFTER_MINUTES,
    escalation_audience: list[str] | None = None,
    default_priority: str = "normal",
    alert_entity: str | None = "alert.leak",
):
    """Alice is the audience; Bob is who the row escalates to."""
    if escalation_audience is None:
        escalation_audience = ["person.bob"]
    return make_entry(
        hass,
        persons=[
            make_person("person.alice", ["mobile_app_alice"]),
            make_person("person.bob", ["mobile_app_bob"]),
        ],
        targets=[
            make_target(
                "leak",
                "Leak",
                alert_entity=alert_entity,
                audience=["person.alice"],
                default_priority=default_priority,
                escalation_after_minutes=after_minutes,
                escalation_audience=escalation_audience,
            )
        ],
        default_target="leak",
    )


async def _arrange(hass, set_person, mock_outputs):
    calls = mock_outputs("mobile_app_alice", "mobile_app_bob")
    set_person("person.alice", "home")
    set_person("person.bob", "home")
    await hass.async_block_till_done()
    return calls


async def _send(hass):
    await hass.services.async_call(
        "notify", "switchboard_leak", {"message": "Leak!"}, blocking=True
    )
    await hass.async_block_till_done()


async def _send_after(hass, *, minutes: int):
    """Send one call as if `minutes` had passed since the episode opened.

    The episode's age is read from its stored start, so moving the *state
    machine's* clock is enough and no timer has to be released — which is the
    whole point of ADR-0020 §0.
    """
    with freeze_time(dt_util.utcnow() + timedelta(minutes=minutes)):
        await _send(hass)


async def test_an_episode_older_than_n_minutes_widens_the_audience(
    hass, enable_custom_integrations, install, mock_outputs, set_person, real_alert
):
    """Twenty-five minutes in, with the alert still firing, Bob is told too."""
    calls = await _arrange(hass, set_person, mock_outputs)
    alert = await real_alert("leak")
    await install(_entry(hass))

    await alert.begin()
    await _send(hass)
    assert len(calls["mobile_app_bob"]) == 0, "the episode has just started"

    # No timer is fired: the clock moves, and the *next* call is what escalates.
    await _send_after(hass, minutes=25)

    assert len(calls["mobile_app_bob"]) == 1, (
        "the escalation audience is added to the row's audience at a call "
        "arriving for an episode that started at least "
        f"{AFTER_MINUTES} minutes ago (contract v0.6, ADR-0020 §2)"
    )
    assert len(calls["mobile_app_alice"]) == 2, (
        "widening the audience adds people, it never replaces them"
    )

    await alert.end()


async def test_an_episode_older_than_n_minutes_raises_the_priority_one_step(
    hass, enable_custom_integrations, install, mock_outputs, set_person, real_alert
):
    """`normal → high`: the message that goes out is the escalated one."""
    calls = await _arrange(hass, set_person, mock_outputs)
    alert = await real_alert("leak")
    await install(_entry(hass))

    await alert.begin()
    await _send_after(hass, minutes=25)

    payload = calls["mobile_app_alice"][-1].data["data"]
    assert payload.get("authenticationRequired") is True, (
        "the priority was raised one step to `high`, and `high` is one of the "
        "priorities whose Companion actions require unlocking the phone "
        "(contract §'Buttons and callbacks'); a `normal` message carries no "
        f"such flag, so this is how the raise is visible. Got {payload!r}"
    )

    await alert.end()


async def test_an_episode_younger_than_n_minutes_does_not_escalate(
    hass, enable_custom_integrations, install, mock_outputs, set_person, real_alert
):
    """Nineteen minutes is not twenty."""
    calls = await _arrange(hass, set_person, mock_outputs)
    alert = await real_alert("leak")
    await install(_entry(hass))

    await alert.begin()
    await _send_after(hass, minutes=19)

    assert len(calls["mobile_app_bob"]) == 0
    assert calls["mobile_app_alice"][-1].data["data"].get("authenticationRequired") in (
        None,
        False,
    )

    await alert.end()


async def test_an_alert_already_acknowledged_does_not_escalate(
    hass, enable_custom_integrations, install, mock_outputs, set_person, real_alert
):
    """`off` means somebody answered: escalating past them would be rude and wrong."""
    calls = await _arrange(hass, set_person, mock_outputs)
    alert = await real_alert("leak")
    await install(_entry(hass))

    await alert.begin()
    await hass.services.async_call(
        "alert", "turn_off", {"entity_id": "alert.leak"}, blocking=True
    )
    await hass.async_block_till_done()
    assert hass.states.get("alert.leak").state == "off", (
        "`alert.turn_off` sets `_ack`, which core's `AlertEntity.state` "
        "reports as `off` while the alert is still firing"
    )

    await _send_after(hass, minutes=25)

    assert len(calls["mobile_app_bob"]) == 0, (
        "the escalation requires the alert to be `on` right now; an "
        "acknowledged alert is `off` (ADR-0020 §2)"
    )

    await alert.end()


async def test_an_episode_that_ended_does_not_escalate(
    hass, enable_custom_integrations, install, mock_outputs, set_person, real_alert
):
    """A closed episode is not a long-running one."""
    calls = await _arrange(hass, set_person, mock_outputs)
    alert = await real_alert("leak")
    await install(_entry(hass))

    await alert.begin()
    await alert.end()
    assert hass.states.get("alert.leak").state == "idle"

    await _send_after(hass, minutes=25)

    assert len(calls["mobile_app_bob"]) == 0


async def test_escalation_fires_at_the_first_repeat_after_n_minutes_so_the_delay_is_rounded_up(
    hass,
    enable_custom_integrations,
    install,
    mock_outputs,
    set_person,
    real_alert,
    freezer,
):
    """The documented granularity, driven by a real `repeat`.

    An alert with `repeat: [15]` and `escalation_after_minutes: 20` escalates
    at **30** minutes, not at 20: the router is called when the alert calls it,
    so the effective delay is `N` rounded up to the repeat interval. This is
    the price of owning no clock (ADR-0020 §0), it is written into
    `docs/contract.md`, and it is pinned here so nobody "fixes" it with a timer.

    Core's `AlertEntity._schedule_notify`
    (`$HA_CORE_SRC/homeassistant/components/alert/entity.py`) arms
    `async_track_point_in_time` at `now() + self._delay[self._next_delay]` and
    then advances `_next_delay = min(_next_delay + 1, len(_delay) - 1)`, so a
    one-element `repeat` is a steady 15-minute interval.
    """
    calls = await _arrange(hass, set_person, mock_outputs)
    freezer.move_to(T0)
    alert = await real_alert("leak", repeat=15, notifiers=["switchboard_leak"])
    await install(_entry(hass))

    await alert.begin()
    assert len(calls["mobile_app_alice"]) == 0, "`skip_first` is on"

    freezer.move_to(T0 + timedelta(minutes=15))
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done()

    assert len(calls["mobile_app_alice"]) == 1
    assert len(calls["mobile_app_bob"]) == 0, (
        "the first repeat lands at 15 minutes, which is short of the 20 the "
        "row asks for"
    )

    freezer.move_to(T0 + timedelta(minutes=30))
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done()

    assert len(calls["mobile_app_alice"]) == 2
    assert len(calls["mobile_app_bob"]) == 1, (
        "the escalation happens at the first repeat after N minutes, so the "
        "effective delay is 30 minutes and not 20 (contract v0.6, ADR-0020 §2)"
    )

    await alert.end()


async def test_a_row_missing_half_the_pair_never_escalates(
    hass, enable_custom_integrations, install, mock_outputs, set_person, real_alert
):
    """`escalation_after_minutes` and `escalation_audience` are required together."""
    calls = await _arrange(hass, set_person, mock_outputs)
    alert = await real_alert("leak")
    await install(_entry(hass, after_minutes=None))

    await alert.begin()
    await _send_after(hass, minutes=25)

    assert len(calls["mobile_app_bob"]) == 0, (
        "an audience with no delay is half a rule; a row carrying one key "
        "without the other escalates nothing at all (ADR-0020 §2)"
    )

    await alert.end()


async def test_a_row_without_an_alert_entity_never_escalates(
    hass, enable_custom_integrations, install, mock_outputs, set_person
):
    """No `alert_entity` means no episode, and no episode means no start to measure."""
    calls = await _arrange(hass, set_person, mock_outputs)
    await install(_entry(hass, alert_entity=None))

    await _send_after(hass, minutes=25)

    assert len(calls["mobile_app_bob"]) == 0


async def test_info_stays_info_while_the_audience_still_widens(
    hass, enable_custom_integrations, install, mock_outputs, set_person, real_alert
):
    """A row whose alerts are informational does not become urgent because time passed."""
    await _arrange(hass, set_person, mock_outputs)
    alert = await real_alert("leak")
    await install(_entry(hass, default_priority="info"))

    await alert.begin()
    with freeze_time(dt_util.utcnow() + timedelta(minutes=25)):
        response = await explain(hass, target="leak")

    assert response["escalated"] == "after_minutes"
    assert response["priority"] == "info", (
        "`info` stays `info`; only `normal → high` and `high → critical` are "
        "raised (contract v0.6, ADR-0020 §2)"
    )
    assert set(response["persons"]) == {"person.alice", "person.bob"}, (
        "`explain` covers the *effective* audience, escalation audience "
        "included (ADR-0020 §8)"
    )

    await alert.end()


async def test_explain_reports_escalated_after_minutes(
    hass, enable_custom_integrations, install, mock_outputs, set_person, real_alert
):
    """The card asking "why is this louder than I configured?" gets an answer."""
    await _arrange(hass, set_person, mock_outputs)
    alert = await real_alert("leak")
    await install(_entry(hass))

    await alert.begin()
    with freeze_time(dt_util.utcnow() + timedelta(minutes=25)):
        response = await explain(hass, target="leak")

    assert response["escalated"] == "after_minutes"
    assert response["priority"] == "high"
    assert response["persons"]["person.bob"]["decision"] == "routed", (
        "an escalated person goes through the whole decision like anybody "
        "else, and is never reported `not_in_audience`"
    )

    await alert.end()
