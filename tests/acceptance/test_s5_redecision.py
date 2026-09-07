"""A deferred message is re-decided in full at its flush (contract v0.5, ADR-0019 §3).

0.4.0 re-reads exactly one thing before delivering a queued message: the
silence (`docs/known-issues.md`, 2026-09-07, "a deferral now re-checks silence,
but only silence"). Everything else — audience, presence rule, snooze — is
taken on trust from a decision made hours earlier.

From 0.5.0 the flush runs the same `router.decide` an inbound call runs, over
the world as it is at that moment, with the message's **original** priority.
A message that no longer routes is dropped with the reason that says why, not
delivered blindly; a message the fresh decision calls `silenced` is still held
and re-armed, because that is what a deferral is for.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import homeassistant.util.dt as dt_util
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from .conftest import make_entry, make_person, make_target

NIGHT = datetime(2026, 9, 10, 21, 30, tzinfo=dt_util.UTC)  # 23:30 Europe/Paris
MORNING = datetime(2026, 9, 11, 5, 5, tzinfo=dt_util.UTC)  # 07:05 Europe/Paris


def _entry(hass, *, presence_rule: str = "always", snooze_minutes=None):
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
        targets=[
            make_target(
                "leak",
                "Leak",
                audience=["person.alice"],
                presence_rule=presence_rule,
                snooze_minutes=snooze_minutes or [],
            )
        ],
        default_target="leak",
    )


async def _wake(hass, freezer) -> None:
    freezer.move_to(MORNING)
    hass.states.async_set("input_boolean.alice_night", "off")
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done()


async def test_a_deferral_is_dropped_with_presence_when_the_person_left_home(
    hass, enable_custom_integrations, install, mock_outputs, set_person, freezer,
    drop_reasons,
):
    """The scenario the known-issues entry describes, now decided rather than sent.

    Alice is home and silenced at 23:30, so the message is queued under a
    `home_only` row. She leaves before 07:00. The row says `home_only`; the
    message must therefore be dropped with `presence`, exactly as an inbound
    call at 07:05 would be.
    """
    await hass.config.async_set_time_zone("Europe/Paris")
    calls = mock_outputs("mobile_app_alice")
    set_person("person.alice", "home")
    hass.states.async_set("input_boolean.alice_night", "on")

    freezer.move_to(NIGHT)
    await install(_entry(hass, presence_rule="home_only"))

    await hass.services.async_call(
        "notify", "switchboard_leak", {"message": "queued while home"}, blocking=True
    )
    await hass.async_block_till_done()
    assert len(calls["mobile_app_alice"]) == 0

    set_person("person.alice", "not_home")
    await hass.async_block_till_done()

    await _wake(hass, freezer)

    assert len(calls["mobile_app_alice"]) == 0, (
        "a `home_only` row must not deliver to somebody who is away, whether "
        "the message is fresh or queued (ADR-0019 §3)"
    )
    assert "presence" in drop_reasons(), (
        "the drop carries the real reason, not a new deferral-specific one"
    )


async def test_a_deferral_is_dropped_with_snoozed_when_the_row_was_snoozed_overnight(
    hass, enable_custom_integrations, install, mock_outputs, set_person, freezer,
    drop_reasons,
):
    """Snoozing a row at 02:00 must silence its queued message too."""
    await hass.config.async_set_time_zone("Europe/Paris")
    calls = mock_outputs("mobile_app_alice")
    set_person("person.alice", "home")
    hass.states.async_set("input_boolean.alice_night", "on")

    freezer.move_to(NIGHT)
    await install(_entry(hass, snooze_minutes=[600]))

    await hass.services.async_call(
        "notify", "switchboard_leak", {"message": "queued before the snooze"},
        blocking=True,
    )
    await hass.async_block_till_done()

    freezer.tick(timedelta(hours=2))  # 01:30 Europe/Paris
    await hass.services.async_call(
        "notify_switchboard",
        "snooze",
        {"target": "leak", "minutes": 600, "person": "person.alice"},
        blocking=True,
    )
    await hass.async_block_till_done()

    await _wake(hass, freezer)

    assert len(calls["mobile_app_alice"]) == 0
    assert "snoozed" in drop_reasons()


async def test_a_deferral_still_silenced_at_the_flush_is_kept_not_dropped(
    hass, enable_custom_integrations, install, mock_outputs, set_person, freezer,
    drop_reasons,
):
    """`silenced` is the one re-decision outcome that holds instead of dropping.

    Green against 0.4.0 on purpose: this is the half of the rule that must
    **not** change. A full re-decision that started dropping messages because
    the night ran late would break the promise the deferral exists for.

    The message is sent `high` so that the next day's flush is a test of §3
    and not of the `normal` time-to-live of §1.
    """
    await hass.config.async_set_time_zone("Europe/Paris")
    calls = mock_outputs("mobile_app_alice")
    set_person("person.alice", "home")
    hass.states.async_set("input_boolean.alice_night", "on")

    freezer.move_to(NIGHT)
    await install(_entry(hass))

    await hass.services.async_call(
        "notify",
        "switchboard_leak",
        {"message": "the night ran late", "data": {"priority": "high"}},
        blocking=True,
    )
    await hass.async_block_till_done()

    # 07:05, but the schedule is still on: hold, do not drop.
    freezer.move_to(MORNING)
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done()
    assert len(calls["mobile_app_alice"]) == 0
    assert "silenced" not in drop_reasons(), (
        "a message held at its flush is still queued, not dropped: the "
        "re-decision's `silenced` outcome is the exception (ADR-0019 §3)"
    )

    # The next morning, with the schedule finally over.
    freezer.move_to(MORNING + timedelta(days=1))
    hass.states.async_set("input_boolean.alice_night", "off")
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done()

    assert len(calls["mobile_app_alice"]) == 1
    assert calls["mobile_app_alice"][0].data["message"] == "the night ran late"


async def test_the_re_decision_uses_the_priority_the_message_was_queued_with(
    hass, enable_custom_integrations, install, mock_outputs, set_person, freezer
):
    """A row's `default_priority` may change overnight; the message's does not.

    A `high` message is queued on a row whose `default_priority` is `info`. If
    the flush re-decides with the row's default instead of the message's own
    priority, `info`'s 120 min TTL kills it (ADR-0019 §1) and nothing arrives.

    Green against 0.4.0 on purpose — 0.4.0 has no TTL to fall into — and a
    guard against the most natural way to get §3 wrong.
    """
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
            make_target(
                "leak", "Leak", audience=["person.alice"], default_priority="info"
            )
        ],
        default_target="leak",
    )
    freezer.move_to(NIGHT)
    await install(entry)

    # `critical` is never deferred, so this one goes straight out...
    await hass.services.async_call(
        "notify",
        "switchboard_leak",
        {"message": "critical now", "data": {"priority": "critical"}},
        blocking=True,
    )
    await hass.async_block_till_done()
    assert len(calls["mobile_app_alice"]) == 1

    # ...while a `high` one is queued, and must not be re-graded to the row's
    # `info` default at the flush, where `info`'s 120 min TTL would kill it.
    await hass.services.async_call(
        "notify",
        "switchboard_leak",
        {"message": "high, queued", "data": {"priority": "high"}},
        blocking=True,
    )
    await hass.async_block_till_done()

    freezer.move_to(MORNING)
    hass.states.async_set("input_boolean.alice_night", "off")
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done()

    messages = [call.data["message"] for call in calls["mobile_app_alice"]]
    assert messages == ["critical now", "high, queued"], (
        "the flush re-decides with the message's original priority, so a "
        "`high` message does not inherit the row's `info` default and its "
        "120 min TTL (ADR-0019 §1 and §3)"
    )
