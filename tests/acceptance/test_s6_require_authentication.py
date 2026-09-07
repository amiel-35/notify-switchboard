"""`require_authentication` — a tri-state on the row's Companion buttons.

Written before the Sprint 6 implementation exists, against:

- `docs/contract.md` §"v0.6 addendum (ADR-0020)" → "`require_authentication`"
- `docs/ADR/0020-bounded-declarative-escalation.md` §7
- `docs/sprints/sprint-6-brief.md` item 7

This closes the oldest open entry of `docs/known-issues.md` (2026-09-07, S1,
"`authenticationRequired` cannot be overridden per row"), which named exactly
this tri-state as its planned resolution. Sprint 2's brief listed it under "out
of scope"; the use case that showed up is a `critical` row on a wall tablet
nobody unlocks, and an `info` row about the front door that everybody would
rather was gated.

It governs the buttons and nothing else. The ADR-0009 allow-list stays the only
thing that decides whether a row can be acknowledged at all.
"""

from __future__ import annotations

from .conftest import make_entry, make_person, make_target


def _entry(
    hass,
    *,
    require_authentication: bool | None,
    default_priority: str = "normal",
    escalate_when_nobody_home: bool = False,
):
    return make_entry(
        hass,
        persons=[make_person("person.alice", ["mobile_app_alice"])],
        targets=[
            make_target(
                "leak",
                "Leak",
                alert_entity="alert.leak",
                audience=["person.alice"],
                allow_acknowledge=True,
                snooze_minutes=[15],
                default_priority=default_priority,
                require_authentication=require_authentication,
                escalate_when_nobody_home=escalate_when_nobody_home,
            )
        ],
        default_target="leak",
    )


async def _send(hass) -> dict:
    await hass.services.async_call(
        "notify", "switchboard_leak", {"message": "Leak!"}, blocking=True
    )
    await hass.async_block_till_done()


def _payload(calls) -> dict:
    return calls["mobile_app_alice"][-1].data["data"]


async def test_true_authenticates_the_buttons_of_an_info_row(
    hass, enable_custom_integrations, install, mock_outputs, set_person
):
    """An explicit `true` overrides the priority rule upwards."""
    calls = mock_outputs("mobile_app_alice")
    set_person("person.alice", "home")
    await install(_entry(hass, require_authentication=True, default_priority="info"))

    await _send(hass)

    payload = _payload(calls)
    assert payload["authenticationRequired"] is True, (
        "`require_authentication: true` sets the flag whatever the priority "
        "(contract v0.6, ADR-0020 §7)"
    )
    assert [action["action"] for action in payload["actions"]] == [
        "switchboard:ack:leak",
        "switchboard:snooze:leak:15",
    ]
    assert all(
        action.get("authenticationRequired") is True for action in payload["actions"]
    ), "every button of the row carries it, not just the payload"


async def test_false_leaves_the_buttons_of_a_critical_row_unauthenticated(
    hass, enable_custom_integrations, install, mock_outputs, set_person
):
    """An explicit `false` overrides the priority rule downwards."""
    calls = mock_outputs("mobile_app_alice")
    set_person("person.alice", "home")
    await install(
        _entry(hass, require_authentication=False, default_priority="critical")
    )

    await _send(hass)

    payload = _payload(calls)
    assert "authenticationRequired" not in payload, (
        "`require_authentication: false` never sets the flag, not even on a "
        "`critical` row (contract v0.6, ADR-0020 §7)"
    )
    assert all("authenticationRequired" not in action for action in payload["actions"])


async def test_null_keeps_the_documented_priority_rule(
    hass, enable_custom_integrations, install, mock_outputs, set_person
):
    """The default is `null`, and `null` is 0.5.0's behaviour to the letter."""
    calls = mock_outputs("mobile_app_alice")
    set_person("person.alice", "home")
    await install(_entry(hass, require_authentication=None, default_priority="high"))

    await _send(hass)
    assert _payload(calls)["authenticationRequired"] is True

    await hass.services.async_call(
        "notify",
        "switchboard_leak",
        {"message": "quieter", "data": {"priority": "normal"}},
        blocking=True,
    )
    await hass.async_block_till_done()
    assert "authenticationRequired" not in _payload(calls)


async def test_a_null_row_reads_the_escalated_priority(
    hass, enable_custom_integrations, install, mock_outputs, set_person
):
    """The button that goes out matches the message that goes out.

    A `normal` call escalated to `critical` because the house is empty
    (ADR-0020 §1) carries an authenticated Acknowledge, because the effective
    priority a `null` row reads is the escalated one (§7).
    """
    calls = mock_outputs("mobile_app_alice")
    set_person("person.alice", "not_home")
    await install(
        _entry(
            hass,
            require_authentication=None,
            default_priority="normal",
            escalate_when_nobody_home=True,
        )
    )

    await _send(hass)

    assert _payload(calls)["authenticationRequired"] is True
