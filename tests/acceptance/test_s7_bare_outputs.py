"""Bare outputs — an audience entry that is not a person.

Written before the Sprint 7 implementation exists, against:

- `docs/contract.md` §"v0.7 addendum (ADR-0021)" → "Bare outputs"
- `docs/ADR/0021-escalation-and-places-reduced.md` §5
- `docs/sprints/sprint-7-brief.md` item 5

A kitchen speaker, a wall tablet's toast overlay: an output with no presence,
no phone and no bedtime. Until 0.6.0 it has to be modelled as a fake
`person.*`, with a `person.*` entity that never moves and a silence that never
fires — and it then shows up in `explain`, in the repairs and (from §3) in the
routing-table entity as somebody who lives in the house.

An audience entry in the `notify` domain is a bare output; one in the `person`
domain is a person; the domain is the whole rule. This is the reduced form of
"places" and the whole of it: there is no `places` object, no schedule and no
new drop reason (ADR-0021 §9).
"""

from __future__ import annotations

from .conftest import explain, make_entry, make_person, make_target

SPEAKER = "notify.kitchen_speaker"


def _entry(
    hass,
    *,
    audience: list[str] | None = None,
    presence_rule: str = "always",
    default_data: dict | None = None,
    alert_entity: str | None = None,
    silence: bool = False,
):
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
                alert_entity=alert_entity,
                audience=audience or ["person.alice", SPEAKER],
                presence_rule=presence_rule,
                default_data=default_data or {},
                snooze_minutes=[15],
                allow_acknowledge=True,
            )
        ],
        default_target="leak",
    )


async def _send(hass, **data):
    payload: dict = {"message": "Leak!"}
    if data:
        payload["data"] = data
    await hass.services.async_call("notify", "switchboard_leak", payload, blocking=True)
    await hass.async_block_till_done()


async def test_a_notify_service_in_the_audience_receives_the_message(
    hass, enable_custom_integrations, install, mock_outputs, set_person
):
    """The whole feature in one assertion: the speaker is told."""
    calls = mock_outputs("mobile_app_alice", "kitchen_speaker")
    set_person("person.alice", "home")
    await install(_entry(hass))

    await _send(hass)

    assert len(calls["kitchen_speaker"]) == 1, (
        "an `audience` entry in the `notify` domain is a bare output and is "
        "delivered to, not treated as an unknown person (ADR-0021 §5)"
    )
    assert calls["kitchen_speaker"][0].data["message"] == "Leak!"
    assert len(calls["mobile_app_alice"]) == 1, (
        "the persons of the audience are unaffected"
    )


async def test_a_bare_output_receives_the_caller_and_row_data_and_nothing_else(
    hass, enable_custom_integrations, install, mock_outputs, set_person
):
    """No buttons, no `authenticationRequired`, no router-invented tag.

    This is ADR-0019 §6's rule — a key the router added goes only to the
    outputs that read it — applied to an output that is nobody's phone. A
    sibling adapter that validates its own `data` raises on a key it does not
    know, so the difference is not cosmetic.
    """
    calls = mock_outputs("mobile_app_alice", "kitchen_speaker")
    set_person("person.alice", "home")
    await install(_entry(hass, default_data={"volume": 0.6}))

    await _send(hass, priority="critical", campaign="night")

    data = calls["kitchen_speaker"][0].data.get("data", {})
    assert data.get("volume") == 0.6, "the target's `default_data` is proxied"
    assert data.get("campaign") == "night", "the caller's own keys are proxied"
    assert "actions" not in data
    assert "authenticationRequired" not in data
    assert "notification_id" not in data
    assert "tag" not in data, (
        "the default `tag` is a key the router invented; it reaches the "
        "Companion outputs and the bare `persistent_notification` output, and "
        "nothing else (ADR-0019 §6, ADR-0021 §5)"
    )


async def test_a_bare_output_has_no_presence_no_silence_and_no_snooze(
    hass, enable_custom_integrations, install, mock_outputs, set_person, drop_reasons
):
    """The person is quiet; the speaker is not, because it has no bedtime."""
    calls = mock_outputs("mobile_app_alice", "kitchen_speaker")
    set_person("person.alice", "home")
    hass.states.async_set("input_boolean.alice_night", "on")
    await hass.async_block_till_done()
    await install(_entry(hass, silence=True))

    await _send(hass)

    assert len(calls["mobile_app_alice"]) == 0
    assert "silenced" in drop_reasons()
    assert len(calls["kitchen_speaker"]) == 1, (
        "a bare output has no silence entity, no snooze and no wake time: it "
        "is delivered now or not at all (ADR-0021 §5)"
    )


async def test_a_bare_output_is_ignored_by_the_presence_rule(
    hass, enable_custom_integrations, install, mock_outputs, set_person, drop_reasons
):
    """A `home_only` target with nobody home still reaches the kitchen."""
    calls = mock_outputs("mobile_app_alice", "kitchen_speaker")
    set_person("person.alice", "not_home")
    await install(_entry(hass, presence_rule="home_only"))

    await _send(hass)

    assert len(calls["mobile_app_alice"]) == 0
    assert "presence" in drop_reasons()
    assert len(calls["kitchen_speaker"]) == 1


async def test_a_delivered_bare_output_is_one_routed_delivery(
    hass, enable_custom_integrations, install, mock_outputs, set_person, routed_sensor
):
    """It is a notification that went out, so it is counted like one."""
    mock_outputs("mobile_app_alice", "kitchen_speaker")
    set_person("person.alice", "home")
    await install(_entry(hass))

    await _send(hass)

    assert routed_sensor().state == "2", (
        "one person and one bare output are two routed deliveries (ADR-0021 §5)"
    )
    payload = hass.states.get("event.switchboard_delivery").attributes
    assert payload["event_type"] == "routed"
    assert payload["target"] == "leak"


async def test_a_missing_bare_output_is_a_delivery_failed_drop(
    hass, enable_custom_integrations, install, mock_outputs, set_person, drop_reasons
):
    """A speaker that does not exist fails the way a person's phone does."""
    mock_outputs("mobile_app_alice")
    set_person("person.alice", "home")
    await install(_entry(hass))

    await _send(hass)

    assert "delivery_failed" in drop_reasons(), (
        "no drop reason is added for a bare output: a missing one is the "
        "`delivery_failed` a missing person output already is (ADR-0021 §5)"
    )


async def test_a_bare_output_pointing_back_at_the_switchboard_is_refused(
    hass, enable_custom_integrations, install, mock_outputs, set_person, drop_reasons
):
    """The recursion guard does not care which side of the audience it is on."""
    mock_outputs("mobile_app_alice")
    set_person("person.alice", "home")
    await install(_entry(hass, audience=["person.alice", "notify.switchboard_leak"]))

    await _send(hass)

    assert "recursion" in drop_reasons(), (
        "an audience entry resolving to `notify.switchboard*` is refused with "
        "the existing `recursion` reason (ADR-0021 §5)"
    )


async def test_a_bare_output_takes_part_in_the_episode_for_the_done_message(
    hass, enable_custom_integrations, install, mock_outputs, set_person, real_alert
):
    """ "Back to normal" reaches the speaker that heard the alarm, and nobody else.

    Alice sleeps through the episode behind a silence, so she is told nothing
    and must not be told it is over (ADR-0019 §5); the speaker heard it, so it
    is. A bare output is an episode recipient like any other.
    """
    calls = mock_outputs("mobile_app_alice", "kitchen_speaker")
    set_person("person.alice", "home")
    hass.states.async_set("input_boolean.alice_night", "on")
    await hass.async_block_till_done()
    alert = await real_alert("leak")
    await install(_entry(hass, alert_entity="alert.leak", silence=True))

    await alert.begin()
    await _send(hass)
    assert len(calls["kitchen_speaker"]) == 1
    assert len(calls["mobile_app_alice"]) == 0

    await alert.end()
    await hass.services.async_call(
        "notify",
        "switchboard_leak",
        {"message": "All good", "data": {"switchboard_done": True}},
        blocking=True,
    )
    await hass.async_block_till_done()

    assert [call.data["message"] for call in calls["kitchen_speaker"]] == [
        "Leak!",
        "All good",
    ]
    assert len(calls["mobile_app_alice"]) == 0


async def test_explain_lists_the_bare_outputs_under_a_top_level_outputs_key(
    hass, enable_custom_integrations, install, mock_outputs, set_person
):
    """A bare output has no person to hang off, so it gets a key of its own."""
    mock_outputs("mobile_app_alice", "kitchen_speaker")
    set_person("person.alice", "home")
    await install(_entry(hass))

    response = await explain(hass, target="leak")

    assert response["outputs"] == [SPEAKER], (
        "`outputs` is a top-level key of the `explain` response listing the "
        "target's bare outputs, in audience order (contract v0.7, ADR-0021 §8)"
    )
    assert set(response["persons"]) == {"person.alice"}, (
        "`persons` stays a mapping of `person.*` entity ids; a bare output is "
        "not a person and never appears there"
    )
