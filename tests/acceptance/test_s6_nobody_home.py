"""`escalate_when_nobody_home` — an empty house makes a call critical.

Written before the Sprint 6 implementation exists, against:

- `docs/contract.md` §"v0.6 addendum (ADR-0020)" → "`escalate_when_nobody_home`"
- `docs/ADR/0020-bounded-declarative-escalation.md` §1
- `docs/sprints/sprint-6-brief.md` item 1

The rule is the cheapest thing in Sprint 6 and the clearest illustration of
the sprint's guard-rail: it reads `person.*` states that already exist, at the
moment a call arrives, and it owns no timer, no debounce and no memory. Ask
again a second later and the answer may be different — that is the point.

`home` means the literal state `home` (`$HA_CORE_SRC/homeassistant/const.py`,
`STATE_HOME`). A named zone, `not_home`, `unknown`, `unavailable` and a person
the state machine has never heard of all count as "not home": a router that
read `unknown` as "probably in" would decline to escalate exactly when it
knows least.
"""

from __future__ import annotations

from .conftest import explain, make_entry, make_person, make_target


def _entry(hass, *, escalate: bool, presence_rule: str = "always"):
    """One row, one person, one night silence Alice is behind."""
    return make_entry(
        hass,
        persons=[
            make_person(
                "person.alice",
                ["mobile_app_alice"],
                silence_entities=["input_boolean.alice_night"],
            )
        ],
        targets=[
            make_target(
                "leak",
                "Leak",
                audience=["person.alice"],
                presence_rule=presence_rule,
                escalate_when_nobody_home=escalate,
            )
        ],
        default_target="leak",
    )


async def _arrange(hass, set_person, mock_outputs, *, alice: str = "not_home"):
    calls = mock_outputs("mobile_app_alice")
    set_person("person.alice", alice)
    hass.states.async_set("input_boolean.alice_night", "on")
    await hass.async_block_till_done()
    return calls


async def _send(hass, **data):
    payload = {"message": "Leak!"}
    if data:
        payload["data"] = data
    await hass.services.async_call("notify", "switchboard_leak", payload, blocking=True)
    await hass.async_block_till_done()


async def test_a_call_is_escalated_to_critical_when_no_audience_person_is_home(
    hass, enable_custom_integrations, install, mock_outputs, set_person
):
    """The house is empty and Alice is silenced: the message goes out anyway."""
    calls = await _arrange(hass, set_person, mock_outputs)
    await install(_entry(hass, escalate=True))

    await _send(hass)

    assert len(calls["mobile_app_alice"]) == 1, (
        "with nobody home the call's priority becomes `critical` for this "
        "decision, and `critical` is the one priority that bypasses a silence "
        "(contract v0.6, ADR-0020 §1)"
    )


async def test_a_zone_or_an_unknown_state_is_not_home(
    hass, enable_custom_integrations, install, mock_outputs, set_person
):
    """Only the literal state `home` counts as home."""
    calls = await _arrange(hass, set_person, mock_outputs, alice="Work")
    await install(_entry(hass, escalate=True))

    await _send(hass)

    assert len(calls["mobile_app_alice"]) == 1, (
        "a `person.*` in a named zone reports that zone, not `home` "
        "($HA_CORE_SRC/homeassistant/components/person/__init__.py), so the "
        "house is empty and the call escalates (ADR-0020 §1)"
    )


async def test_nothing_is_escalated_while_one_audience_person_is_home(
    hass, enable_custom_integrations, install, mock_outputs, set_person, drop_reasons
):
    """Bob is in: Alice's silence still holds, because somebody is there to hear it."""
    calls = mock_outputs("mobile_app_alice", "mobile_app_bob")
    set_person("person.alice", "not_home")
    set_person("person.bob", "home")
    hass.states.async_set("input_boolean.alice_night", "on")
    await hass.async_block_till_done()

    await install(
        make_entry(
            hass,
            persons=[
                make_person(
                    "person.alice",
                    ["mobile_app_alice"],
                    silence_entities=["input_boolean.alice_night"],
                ),
                make_person("person.bob", ["mobile_app_bob"]),
            ],
            targets=[
                make_target(
                    "leak",
                    "Leak",
                    audience=["person.alice", "person.bob"],
                    escalate_when_nobody_home=True,
                )
            ],
            default_target="leak",
        )
    )

    await _send(hass)

    assert len(calls["mobile_app_bob"]) == 1
    assert len(calls["mobile_app_alice"]) == 0, (
        "one person home is enough: the rule asks whether *anybody* is there, "
        "not whether everybody is (ADR-0020 §1)"
    )
    assert "silenced" in drop_reasons()


async def test_a_row_without_the_flag_is_never_escalated(
    hass, enable_custom_integrations, install, mock_outputs, set_person, drop_reasons
):
    """The default is off, and off means 0.5.0's behaviour to the letter."""
    calls = await _arrange(hass, set_person, mock_outputs)
    await install(_entry(hass, escalate=False))

    await _send(hass)

    assert len(calls["mobile_app_alice"]) == 0
    assert "silenced" in drop_reasons()


async def test_the_escalation_does_not_override_the_presence_rule(
    hass, enable_custom_integrations, install, mock_outputs, set_person, drop_reasons
):
    """A `home_only` row with nobody home drops on `presence`, escalated or not.

    The row said "only tell them when they are here". Raising a priority is
    not permission to contradict it, so the flag is inert on such a row — and
    that is the correct outcome rather than an oversight (ADR-0020 §1).
    """
    calls = await _arrange(hass, set_person, mock_outputs)
    await install(_entry(hass, escalate=True, presence_rule="home_only"))

    await _send(hass)

    assert len(calls["mobile_app_alice"]) == 0
    assert "presence" in drop_reasons()
    assert "silenced" not in drop_reasons(), (
        "the presence rule is evaluated first and is the reason the user has to act on"
    )


async def test_explain_reports_escalated_nobody_home_and_the_escalated_priority(
    hass, enable_custom_integrations, install, mock_outputs, set_person
):
    """`explain` answers about the world as it is, escalation included."""
    await _arrange(hass, set_person, mock_outputs)
    await install(_entry(hass, escalate=True))

    response = await explain(hass, target="leak")

    assert response["escalated"] == "nobody_home", (
        "`escalated` is a top-level key of the `explain` response and names "
        "the rule that changed this decision (contract v0.6, ADR-0020 §8)"
    )
    assert response["priority"] == "critical", (
        "`priority` reports the *escalated* priority, which is what a message "
        "sent right now would carry"
    )
    assert response["persons"]["person.alice"]["decision"] == "routed"


async def test_a_call_that_is_already_critical_reports_no_escalation(
    hass, enable_custom_integrations, install, mock_outputs, set_person
):
    """A rule whose condition holds but which changes nothing leaves `escalated` null.

    Nobody is home and the flag is on, but the caller already asked for
    `critical`: there is nothing to raise, so reporting an escalation would
    make the key useless for the question a card asks it (ADR-0020 §8).
    """
    await _arrange(hass, set_person, mock_outputs)
    await install(_entry(hass, escalate=True))

    response = await explain(hass, target="leak", priority="critical")

    assert response["priority"] == "critical"
    assert response["escalated"] is None
