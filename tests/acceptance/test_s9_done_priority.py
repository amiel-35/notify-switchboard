"""The all-clear does not ring like the alarm (ADR-0023 §2).

Written before the Sprint 9 implementation exists, against:

- `docs/contract.md` §"v0.9 addendum (ADR-0023)" → "`done_priority`", "A done
  message never rings louder than `done_priority`" and "Which calls are done
  messages"
- `docs/ADR/0023-one-click-automation-and-a-quiet-all-clear.md` §2
- `docs/history/sprints/sprint-9-brief.md` item 2

The bug, observed at the maintainer's home on 2026-10-12: an `alert:` with
`notifiers: [switchboard_<slug>]` calls that one service for its first
message, for every `repeat`, and for its `done_message`
(`$HA_CORE_SRC/homeassistant/components/alert/entity.py`, `_notify` and
`_notify_done_message`, both through `_send_notification_message`). On a
`critical` target the router routed all three at `critical`, so "the leak is
over" arrived as a critical push.

The first tests below drive a **real** core `alert` -- not a synthetic
`alert.*` state -- because the recognition ADR-0023 §2.2 relies on is the
order of core's `end_alerting` itself: `_firing` is cleared before the done
message is awaited and the state is written after it. A synthetic state
cannot reproduce that instant, which is the whole point.

How a priority is observed. A `critical` message carries the critical payload
on a Companion output (contract v0.7: `push.sound.critical` and friends) and
`authenticationRequired`; a `high` one carries `authenticationRequired` only;
the `priority` of the last `routed` `event.switchboard_delivery` says the rest.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import homeassistant.util.dt as dt_util
import pytest
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from .conftest import make_entry, make_person, make_target

SOURCE = "binary_sensor.leak_source"
ALERT = "alert.leak"
PHONE = "mobile_app_alice"

NIGHT = datetime(2026, 9, 10, 21, 30, tzinfo=dt_util.UTC)  # 23:30 Europe/Paris
MORNING = datetime(2026, 9, 11, 5, 5, tzinfo=dt_util.UTC)  # 07:05 Europe/Paris


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@pytest.fixture
async def wired_alert(hass):
    """Set up one real `alert.leak` that lists `switchboard_leak` as notifier.

    `skip_first: false` and `repeat: [1]`: the first message is sent at once,
    a reminder every minute. Ending the alert (`end()`) cancels the reminder
    (`end_alerting` calls `self._cancel()`), and the teardown ends it even for
    a test that failed first, so no core timer outlives a test.
    """
    made: list[Any] = []

    async def _make(*, done_message: str | None = "All clear") -> Any:
        hass.states.async_set(SOURCE, "off")
        config: dict[str, Any] = {
            "name": "Leak",
            "entity_id": SOURCE,
            "state": "on",
            "repeat": [1],
            "can_acknowledge": True,
            "skip_first": False,
            "message": "Leak!",
            "notifiers": ["switchboard_leak"],
        }
        if done_message is not None:
            config["done_message"] = done_message
        assert await async_setup_component(hass, "alert", {"alert": {"leak": config}})
        await hass.async_block_till_done()

        class _Alert:
            async def begin(self) -> None:
                hass.states.async_set(SOURCE, "on")
                await hass.async_block_till_done()

            async def remind(self) -> None:
                async_fire_time_changed(
                    hass, dt_util.utcnow() + timedelta(minutes=1, seconds=5)
                )
                await hass.async_block_till_done()

            async def end(self) -> None:
                hass.states.async_set(SOURCE, "off")
                await hass.async_block_till_done()

        made.append(_Alert())
        return made[-1]

    yield _make

    for alert in made:
        await alert.end()


def _entry(
    hass,
    *,
    default_priority: str = "critical",
    done_priority: str | None = None,
    alert_entity: str | None = ALERT,
    observer_mode: bool = False,
    escalate: bool = False,
    silence: bool = False,
):
    return make_entry(
        hass,
        persons=[
            make_person(
                "person.alice",
                [PHONE],
                silence_entities=["input_boolean.alice_night"] if silence else [],
                wake_time="07:00:00" if silence else None,
            )
        ],
        targets=[
            make_target(
                "leak",
                "Leak",
                default_priority=default_priority,
                alert_entity=alert_entity,
                audience=["person.alice"],
                observer_mode=observer_mode,
                escalate_when_nobody_home=escalate,
                done_priority=done_priority,
            )
        ],
        default_target="leak",
    )


def _messages(calls) -> list[Any]:
    """The calls of one output that are messages, not `clear_notification`."""
    return [call for call in calls if call.data["message"] != "clear_notification"]


def _is_critical(call) -> bool:
    data = call.data.get("data") or {}
    return "push" in data and data["push"]["sound"]["critical"] == 1


def _asks_for_authentication(call) -> bool:
    return bool((call.data.get("data") or {}).get("authenticationRequired"))


def _routed_priority(hass) -> str | None:
    state = hass.states.get("event.switchboard_delivery")
    assert state is not None
    return state.attributes.get("priority")


async def _call(hass, message: str, **data) -> None:
    payload: dict[str, Any] = {"message": message}
    if data:
        payload["data"] = data
    await hass.services.async_call("notify", "switchboard_leak", payload, blocking=True)
    await hass.async_block_till_done()


# ---------------------------------------------------------------------------
# The bug, on a real alert wired through `notifiers:`
# ---------------------------------------------------------------------------


async def test_a_critical_alerts_all_clear_is_not_critical(
    hass, enable_custom_integrations, install, mock_outputs, set_person, wired_alert
):
    """The observed scenario: first message, one reminder, then the end."""
    calls = mock_outputs(PHONE)
    set_person("person.alice", "home")
    alert = await wired_alert()
    await install(_entry(hass))

    await alert.begin()
    await alert.remind()
    await alert.end()

    sent = _messages(calls[PHONE])
    assert [call.data["message"] for call in sent] == [
        "Leak!",
        "Leak!",
        "All clear",
    ], "the alert's own three calls, in order: first, reminder, done"

    first, reminder, done = sent
    assert _is_critical(first), "the alarm itself still rings as critical"
    assert _is_critical(reminder), (
        "a reminder is the alarm again, not its end: still critical"
    )
    assert not _is_critical(done), (
        "the all-clear of a critical alert must not ring like it "
        "(contract v0.9, ADR-0023 §2)"
    )
    assert not _asks_for_authentication(done), (
        "capped at `normal`, the done message carries no "
        "`authenticationRequired` either (contract v0.7: high/critical only)"
    )
    assert _routed_priority(hass) == "normal", (
        "absent `done_priority` means `normal` (contract v0.9)"
    )


async def test_the_alerts_all_clear_keeps_replacing_the_alarm_on_the_phone(
    hass, enable_custom_integrations, install, mock_outputs, set_person, wired_alert
):
    """Priority only: the done call keeps the tag it had (ADR-0023 §2.2).

    The `notifiers:` done message has carried the target's ordinary default
    tag since 0.5, so on a phone it replaces the alarm's notification. 0.9
    changes how loud it is, not where it lands.
    """
    calls = mock_outputs(PHONE)
    set_person("person.alice", "home")
    alert = await wired_alert()
    await install(_entry(hass))

    await alert.begin()
    await alert.end()

    first, done = _messages(calls[PHONE])
    assert done.data["data"]["tag"] == first.data["data"]["tag"] == "switchboard-leak"


async def test_an_acknowledged_alert_ends_quietly_too(
    hass, enable_custom_integrations, install, mock_outputs, set_person, wired_alert
):
    """Acknowledged first (`on -> off`), then over: the state machine says `off`."""
    calls = mock_outputs(PHONE)
    set_person("person.alice", "home")
    alert = await wired_alert()
    await install(_entry(hass))

    await alert.begin()
    await hass.services.async_call(
        "alert", "turn_off", {"entity_id": ALERT}, blocking=True
    )
    await hass.async_block_till_done()
    assert hass.states.get(ALERT).state == "off"
    await alert.end()

    done = _messages(calls[PHONE])[-1]
    assert done.data["message"] == "All clear"
    assert not _is_critical(done)


async def test_a_static_critical_priority_in_the_alerts_data_is_capped_too(
    hass, enable_custom_integrations, install, mock_outputs, set_person
):
    """`data: {priority: critical}` on the `alert:` is the same for all three calls.

    The ceiling is applied last (contract v0.9), after the caller's
    `data.priority`: the alert cannot say "this one is the end", so the router
    does not let its static data decide.
    """
    calls = mock_outputs(PHONE)
    set_person("person.alice", "home")
    hass.states.async_set(SOURCE, "off")
    assert await async_setup_component(
        hass,
        "alert",
        {
            "alert": {
                "leak": {
                    "name": "Leak",
                    "entity_id": SOURCE,
                    "state": "on",
                    "repeat": [60],
                    "skip_first": False,
                    "message": "Leak!",
                    "done_message": "All clear",
                    "notifiers": ["switchboard_leak"],
                    "data": {"priority": "critical"},
                }
            }
        },
    )
    await install(_entry(hass, default_priority="normal"))

    hass.states.async_set(SOURCE, "on")
    await hass.async_block_till_done()
    hass.states.async_set(SOURCE, "off")
    await hass.async_block_till_done()

    first, done = _messages(calls[PHONE])
    assert _is_critical(first)
    assert not _is_critical(done)


async def test_without_a_done_message_the_alert_sends_nothing_more(
    hass, enable_custom_integrations, install, mock_outputs, set_person, wired_alert
):
    """Core sends no done call when the `alert:` has no `done_message`."""
    calls = mock_outputs(PHONE)
    set_person("person.alice", "home")
    alert = await wired_alert(done_message=None)
    await install(_entry(hass))

    await alert.begin()
    await alert.end()

    assert [call.data["message"] for call in _messages(calls[PHONE])] == ["Leak!"]


async def test_a_call_while_the_alert_is_idle_is_not_a_done_message(
    hass, enable_custom_integrations, install, mock_outputs, set_person, wired_alert
):
    """An automation calling the target between two episodes is an ordinary call.

    The recognition needs the live entity and the stored state to disagree
    (ADR-0023 §2.2); between episodes both say `idle`.
    """
    calls = mock_outputs(PHONE)
    set_person("person.alice", "home")
    await wired_alert()
    await install(_entry(hass))

    await _call(hass, "Water meter spinning")

    (call,) = _messages(calls[PHONE])
    assert _is_critical(call), "the target's own priority applies, as in 0.8"


# ---------------------------------------------------------------------------
# The two done messages v0.5 already knew
# ---------------------------------------------------------------------------


async def test_observer_modes_done_message_is_capped(
    hass, enable_custom_integrations, install, mock_outputs, set_person
):
    """Observer mode's `→ idle` message had the same flaw, at the same priority."""
    calls = mock_outputs(PHONE)
    set_person("person.alice", "home")
    hass.states.async_set(ALERT, "idle")
    await install(_entry(hass, observer_mode=True))

    hass.states.async_set(ALERT, "on")
    await hass.async_block_till_done()
    hass.states.async_set(ALERT, "idle")
    await hass.async_block_till_done()

    first, done = _messages(calls[PHONE])
    assert _is_critical(first)
    assert not _is_critical(done)
    assert done.data["data"]["tag"] == "switchboard-leak-done", (
        "an observer done message keeps everything v0.5 gave it"
    )


async def test_a_switchboard_done_call_is_capped_even_when_it_asks_for_critical(
    hass, enable_custom_integrations, install, mock_outputs, set_person
):
    """`data.switchboard_done: true` is a done message; the ceiling wins."""
    calls = mock_outputs(PHONE)
    set_person("person.alice", "home")
    await install(_entry(hass, alert_entity=None))

    await _call(hass, "All clear", switchboard_done=True, priority="critical")

    (done,) = _messages(calls[PHONE])
    assert not _is_critical(done)
    assert _routed_priority(hass) == "normal"


# ---------------------------------------------------------------------------
# The ceiling is the target's to set
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("default_priority", "done_priority", "expected"),
    [
        ("critical", "critical", "critical"),  # the 0.8 behaviour, on request
        ("critical", "high", "high"),
        ("high", "info", "info"),
        ("info", None, "info"),  # never louder than it would have been
        ("normal", "critical", "normal"),  # a ceiling, not a floor
    ],
)
async def test_done_priority_is_a_ceiling(
    hass,
    enable_custom_integrations,
    install,
    mock_outputs,
    set_person,
    default_priority,
    done_priority,
    expected,
):
    """min(what it would have been, `done_priority`) (contract v0.9)."""
    mock_outputs(PHONE)
    set_person("person.alice", "home")
    await install(
        _entry(
            hass,
            alert_entity=None,
            default_priority=default_priority,
            done_priority=done_priority,
        )
    )

    await _call(hass, "All clear", switchboard_done=True)

    assert _routed_priority(hass) == expected


async def test_the_ceiling_holds_after_escalation(
    hass, enable_custom_integrations, install, mock_outputs, set_person
):
    """An empty house raises a call one step; the ceiling is applied after it."""
    mock_outputs(PHONE)
    set_person("person.alice", "not_home")
    await install(
        _entry(hass, alert_entity=None, default_priority="high", escalate=True)
    )

    await _call(hass, "Leak!")
    assert _routed_priority(hass) == "critical", "escalation itself is unchanged"

    await _call(hass, "All clear", switchboard_done=True)
    assert _routed_priority(hass) == "normal"


# ---------------------------------------------------------------------------
# A capped done message is an ordinary message of that priority
# ---------------------------------------------------------------------------


async def test_a_capped_done_message_waits_for_the_morning_and_stays_capped(
    hass,
    enable_custom_integrations,
    install,
    mock_outputs,
    set_person,
    wired_alert,
    freezer,
    deferred_sensor,
):
    """The end of a 3 a.m. leak does not wake the house a second time.

    The alarm is critical and goes through the silence. Its end, capped at
    `normal`, is held by the silence and deferred to the wake time. Nobody is
    home and the target escalates, so at the flush a `normal` message would
    become `high` again -- unless the deferral remembers it is a done message
    (ADR-0023 §2.5). It is the alert's own `notifiers:` call, which carries no
    `switchboard_done` key in its data for the flush to see.
    """
    await hass.config.async_set_time_zone("Europe/Paris")
    calls = mock_outputs(PHONE)
    set_person("person.alice", "not_home")
    hass.states.async_set("input_boolean.alice_night", "on")
    freezer.move_to(NIGHT)
    alert = await wired_alert()
    await install(_entry(hass, default_priority="high", escalate=True, silence=True))

    await alert.begin()
    first = _messages(calls[PHONE])
    assert len(first) == 1 and _is_critical(first[0]), (
        "high, escalated to critical by the empty house, bypasses the silence"
    )

    await alert.end()
    assert len(_messages(calls[PHONE])) == 1, "the all-clear is held, not sent"
    assert deferred_sensor().state == "1"

    freezer.move_to(MORNING)
    hass.states.async_set("input_boolean.alice_night", "off")
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done()

    sent = _messages(calls[PHONE])
    assert [call.data["message"] for call in sent] == ["Leak!", "All clear"]
    assert not _asks_for_authentication(sent[-1]), (
        "re-decided at the flush, the done message keeps its ceiling: `normal`, "
        "not `normal` escalated to `high` (contract v0.9)"
    )
    assert _routed_priority(hass) == "normal"
