"""`max_deliveries` — a bound on how often one episode may reach one person.

Written before the Sprint 6 implementation exists, against:

- `docs/contract.md` §"v0.6 addendum (ADR-0020)" → "`max_deliveries`"
- `docs/ADR/0020-bounded-declarative-escalation.md` §3
- `docs/sprints/sprint-6-brief.md` item 3

An alert with `repeat: [5]` that nobody is in a position to acknowledge will
call this integration every five minutes for as long as it runs. `max_deliveries`
is the household saying "three is enough" — and it is the second thing in this
sprint that looks like it wants a counter of its own and must not have one.

The bound lives in the episode record ADR-0019 §5 already keeps, next to the
recipients, and it is advanced by a **delivery** and never by time. A "delivery"
is the unit `sensor.switchboard_routed_today` already counts: one (person,
target) pair that reached at least one output. The record resets when the row's
next episode opens, which is what "reset at episode end" means for a record the
contract keeps after the alert has gone idle.
"""

from __future__ import annotations

from .conftest import make_entry, make_person, make_target


def _entry(
    hass,
    *,
    cap: int | None,
    alert_entity: str | None = "alert.leak",
    persons: list[str] | None = None,
    silence_entities: list[str] | None = None,
):
    audience = persons or ["person.alice"]
    return make_entry(
        hass,
        persons=[
            make_person(
                person,
                [f"mobile_app_{person.partition('.')[2]}"],
                silence_entities=list(silence_entities or []),
            )
            for person in audience
        ],
        targets=[
            make_target(
                "leak",
                "Leak",
                alert_entity=alert_entity,
                audience=audience,
                max_deliveries=cap,
            )
        ],
        default_target="leak",
    )


async def _send(hass, *, message: str = "Leak!", **data):
    payload: dict = {"message": message}
    if data:
        payload["data"] = data
    await hass.services.async_call("notify", "switchboard_leak", payload, blocking=True)
    await hass.async_block_till_done()


async def test_the_cap_drops_the_next_delivery_with_the_max_deliveries_reason(
    hass,
    enable_custom_integrations,
    install,
    mock_outputs,
    set_person,
    real_alert,
    drop_reasons,
):
    """Two is two: the third message of the episode does not go out."""
    calls = mock_outputs("mobile_app_alice")
    set_person("person.alice", "home")
    alert = await real_alert("leak")
    await install(_entry(hass, cap=2))

    await alert.begin()
    for index in range(3):
        await _send(hass, message=f"Leak {index}")

    assert len(calls["mobile_app_alice"]) == 2, (
        "`max_deliveries: 2` bounds the episode at two routed deliveries per "
        "person (contract v0.6, ADR-0020 §3)"
    )
    assert "max_deliveries" in drop_reasons(), (
        "nothing is silently lost: the message the cap stops is dropped with "
        "a reason of its own"
    )


async def test_the_cap_is_per_person_and_not_per_episode(
    hass, enable_custom_integrations, install, mock_outputs, set_person, real_alert
):
    """Alice being talked out does not use up Bob's budget."""
    calls = mock_outputs("mobile_app_alice", "mobile_app_bob")
    set_person("person.alice", "home")
    set_person("person.bob", "home")
    alert = await real_alert("leak")
    await install(_entry(hass, cap=2, persons=["person.alice", "person.bob"]))

    await alert.begin()
    for index in range(3):
        await _send(hass, message=f"Leak {index}")

    assert len(calls["mobile_app_alice"]) == 2
    assert len(calls["mobile_app_bob"]) == 2, (
        "the bound is per (episode, person); a single per-episode counter "
        "would have stopped after two deliveries in total (ADR-0020 §3)"
    )


async def test_the_done_message_is_never_counted_and_is_always_allowed(
    hass, enable_custom_integrations, install, mock_outputs, set_person, real_alert
):
    """A cap stops the router repeating itself, not the news that it is over."""
    calls = mock_outputs("mobile_app_alice")
    set_person("person.alice", "home")
    alert = await real_alert("leak")
    await install(_entry(hass, cap=1))

    await alert.begin()
    await _send(hass, message="Leak!")
    await _send(hass, message="Still leaking")
    assert len(calls["mobile_app_alice"]) == 1, "the second message is over the cap"

    await alert.end()
    await _send(hass, message="All good", switchboard_done=True)

    assert [call.data["message"] for call in calls["mobile_app_alice"]] == [
        "Leak!",
        "All good",
    ], (
        "the `done` message is not counted against the cap and is delivered "
        "whatever the cap says (contract v0.6, ADR-0020 §3)"
    )


async def test_the_count_starts_again_at_the_next_episode(
    hass, enable_custom_integrations, install, mock_outputs, set_person, real_alert
):
    """A cap bounds one run of the alert, not the row for ever."""
    calls = mock_outputs("mobile_app_alice")
    set_person("person.alice", "home")
    alert = await real_alert("leak")
    await install(_entry(hass, cap=1))

    await alert.begin()
    await _send(hass, message="first episode")
    await _send(hass, message="over the cap")
    await alert.end()

    await alert.begin()
    await _send(hass, message="second episode")

    assert [call.data["message"] for call in calls["mobile_app_alice"]] == [
        "first episode",
        "second episode",
    ]


async def test_a_row_without_an_alert_entity_is_never_capped(
    hass, enable_custom_integrations, install, mock_outputs, set_person
):
    """No `alert_entity` means no episode, and a cap with no episode is inert.

    Bounding such a row would need a counter with no lifecycle — a counter of
    the router's own, which the sprint's guard-rail refuses (ADR-0020 §0).
    """
    calls = mock_outputs("mobile_app_alice")
    set_person("person.alice", "home")
    await install(_entry(hass, cap=1, alert_entity=None))

    for index in range(3):
        await _send(hass, message=f"Leak {index}")

    assert len(calls["mobile_app_alice"]) == 3


async def test_critical_does_not_bypass_the_cap(
    hass,
    enable_custom_integrations,
    install,
    mock_outputs,
    set_person,
    real_alert,
    drop_reasons,
):
    """`critical` bypasses a person's quiet, not a bound the household set.

    This is the case the rule is designed for: when an escalation widens the
    audience, the newly added people start at zero and hear about it, while the
    person who has already been told stays capped (ADR-0020 §3).
    """
    calls = mock_outputs("mobile_app_alice")
    set_person("person.alice", "home")
    alert = await real_alert("leak")
    await install(_entry(hass, cap=1))

    await alert.begin()
    await _send(hass, message="Leak!")
    await _send(hass, message="Louder", priority="critical")

    assert len(calls["mobile_app_alice"]) == 1
    assert "max_deliveries" in drop_reasons()


async def test_a_delivery_dropped_for_another_reason_does_not_consume_the_budget(
    hass,
    enable_custom_integrations,
    install,
    mock_outputs,
    set_person,
    real_alert,
    drop_reasons,
):
    """The cap is the last rule, so a message that never went out costs nothing."""
    calls = mock_outputs("mobile_app_alice")
    set_person("person.alice", "home")
    hass.states.async_set("input_boolean.alice_night", "on")
    alert = await real_alert("leak")
    await install(_entry(hass, cap=1, silence_entities=["input_boolean.alice_night"]))

    await alert.begin()
    await _send(hass, message="slept through this one")
    assert len(calls["mobile_app_alice"]) == 0
    assert "silenced" in drop_reasons()

    hass.states.async_set("input_boolean.alice_night", "off")
    await hass.async_block_till_done()

    await _send(hass, message="the first one she actually gets")
    await _send(hass, message="over the cap")

    assert [call.data["message"] for call in calls["mobile_app_alice"]] == [
        "the first one she actually gets"
    ], (
        "the silenced message was never delivered, so it did not consume the "
        "budget; the next one did (contract v0.6, ADR-0020 §3)"
    )
    assert "max_deliveries" in drop_reasons()
