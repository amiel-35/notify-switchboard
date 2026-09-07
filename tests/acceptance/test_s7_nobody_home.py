"""`escalate_when_nobody_home` — an empty house raises a call one step.

Written before the Sprint 7 implementation exists, against:

- `docs/contract.md` §"v0.7 addendum (ADR-0021)" → "`escalate_when_nobody_home`"
- `docs/ADR/0021-escalation-and-places-reduced.md` §1
- `docs/sprints/sprint-7-brief.md` item 1

The rule is the clearest illustration of the sprint's guard-rail: it reads
`person.*` states that already exist, at the moment a call arrives, and it owns
no timer, no debounce and no memory. Ask again a second later and the answer
may be different — that is the point.

**One step, not straight to `critical`.** `info → normal → high → critical`,
and `critical` unchanged. An empty house is a statement that nobody is here to
notice, not a statement that the message became a life-safety alert; a target
whose alerts matter says so with `default_priority: high` and gets a critical
message out of an empty house, which is the case the flag exists for.

`home` means the literal state `home` (`$HA_CORE_SRC/homeassistant/const.py`,
`STATE_HOME`). A named zone, `not_home`, `unknown`, `unavailable` and a person
the state machine has never heard of all count as "not home": a router that
read `unknown` as "probably in" would decline to escalate exactly when it knows
least.
"""

from __future__ import annotations

from .conftest import explain, make_entry, make_person, make_target


def _entry(
    hass,
    *,
    escalate: bool,
    presence_rule: str = "always",
    default_priority: str = "high",
    silence: bool = True,
):
    """One target, one person, and (by default) a night silence to test against."""
    return make_entry(
        hass,
        persons=[
            make_person(
                "person.alice",
                ["mobile_app_alice"],
                silence_entities=["input_boolean.alice_night"] if silence else [],
            )
        ],
        targets=[
            make_target(
                "leak",
                "Leak",
                audience=["person.alice"],
                presence_rule=presence_rule,
                default_priority=default_priority,
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


def _routed_priority(hass) -> str | None:
    """Return the `priority` of the last `event.switchboard_delivery`."""
    state = hass.states.get("event.switchboard_delivery")
    assert state is not None
    return state.attributes.get("priority")


async def test_a_high_call_is_escalated_to_critical_when_no_audience_person_is_home(
    hass, enable_custom_integrations, install, mock_outputs, set_person
):
    """The house is empty and Alice is silenced: the message goes out anyway."""
    calls = await _arrange(hass, set_person, mock_outputs)
    await install(_entry(hass, escalate=True))

    await _send(hass)

    assert len(calls["mobile_app_alice"]) == 1, (
        "with nobody home a `high` call is raised one step to `critical`, and "
        "`critical` is the one priority that bypasses a silence "
        "(contract v0.7, ADR-0021 §1)"
    )
    assert _routed_priority(hass) == "critical"


async def test_a_normal_call_is_raised_one_step_to_high_and_no_further(
    hass, enable_custom_integrations, install, mock_outputs, set_person
):
    """One step means one step: `normal` becomes `high`, not `critical`.

    Alice is out and not silenced, so the message is delivered either way; what
    is being pinned is the priority it was delivered *at*, which is what the
    `routed` event reports and what the critical payload of §7 reads.
    """
    calls = mock_outputs("mobile_app_alice")
    set_person("person.alice", "not_home")
    await install(_entry(hass, escalate=True, default_priority="normal", silence=False))

    await _send(hass)

    assert len(calls["mobile_app_alice"]) == 1
    assert _routed_priority(hass) == "high", (
        "`normal` escalates to `high` and stops there (ADR-0021 §1); jumping "
        "to `critical` would make every empty house bypass every silence"
    )


async def test_an_info_call_is_raised_only_to_normal(
    hass, enable_custom_integrations, install, mock_outputs, set_person
):
    """The bottom of the rank moves by one too, and by no more than one."""
    calls = mock_outputs("mobile_app_alice")
    set_person("person.alice", "not_home")
    await install(_entry(hass, escalate=True, default_priority="info", silence=False))

    await _send(hass)

    assert len(calls["mobile_app_alice"]) == 1
    assert _routed_priority(hass) == "normal"


async def test_a_normal_call_escalated_to_high_still_does_not_bypass_a_silence(
    hass, enable_custom_integrations, install, mock_outputs, set_person, drop_reasons
):
    """`critical` is still the only bypass, and escalation does not add a second."""
    calls = await _arrange(hass, set_person, mock_outputs)
    await install(_entry(hass, escalate=True, default_priority="normal"))

    await _send(hass)

    assert len(calls["mobile_app_alice"]) == 0, (
        "a `normal` call escalated to `high` is still a `high` call, and `high` "
        "has never bypassed a silence (contract §Routing decision, unchanged)"
    )
    assert "silenced" in drop_reasons()


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
        "house is empty and the call escalates (ADR-0021 §1)"
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
                    default_priority="high",
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
        "not whether everybody is (ADR-0021 §1)"
    )
    assert "silenced" in drop_reasons()


async def test_a_target_without_the_flag_is_never_escalated(
    hass, enable_custom_integrations, install, mock_outputs, set_person, drop_reasons
):
    """The default is off, and off means 0.6.0's behaviour to the letter."""
    calls = await _arrange(hass, set_person, mock_outputs)
    await install(_entry(hass, escalate=False))

    await _send(hass)

    assert len(calls["mobile_app_alice"]) == 0
    assert "silenced" in drop_reasons()


async def test_the_escalation_does_not_override_the_presence_rule(
    hass, enable_custom_integrations, install, mock_outputs, set_person, drop_reasons
):
    """A `home_only` target with nobody home drops on `presence`, escalated or not.

    The target said "only tell them when they are here". Raising a priority is
    not permission to contradict it, so the flag is inert on such a target —
    and that is the correct outcome rather than an oversight (ADR-0021 §1).
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
        "the rule that changed this decision (contract v0.7, ADR-0021 §8)"
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
    make the key useless for the question a card asks it (ADR-0021 §8).
    """
    await _arrange(hass, set_person, mock_outputs)
    await install(_entry(hass, escalate=True))

    response = await explain(hass, target="leak", priority="critical")

    assert response["priority"] == "critical"
    assert response["escalated"] is None
