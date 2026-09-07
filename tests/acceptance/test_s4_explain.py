"""`notify_switchboard.explain` — a read-only answer to "would this arrive?".

Written before the Sprint 4 implementation exists, against:

- `docs/contract.md` §"v0.4 addendum (ADR-0018)" → "`notify_switchboard.explain`"
- `docs/ADR/0018-zero-config-and-explainability.md` §1
- `docs/sprints/sprint-4-brief.md` item 1

0.3.0 can already say what happened — `sensor.switchboard_dropped_today`
carries its reasons, the diagnostics carry a decision log — but nothing can
say what *would* happen, and "why didn't I get the leak alert?" is the first
question a router has to answer. `explain` runs the real decision over the
real world and reports it, per person, without touching anything.

Two properties are load-bearing and are tested separately from the answers
themselves:

- **the answer is complete**: every decision kind carries a `detail` a human
  can act on, translated into the instance language;
- **the question changes nothing**: no `notify.*` call, no counter, no
  `event.switchboard_delivery`, no deferral, no stored snooze touched. A card
  that calls `explain` on every render must not inflate the day's counts.

Note on `pytest.raises(ServiceValidationError)`: core's `ServiceNotFound` is a
subclass of it (`homeassistant/exceptions.py`), so a service that does not
exist at all would satisfy a bare `raises`. Every refusal test below asserts
`has_service` first and the `translation_key` after — the same discipline
`tests/acceptance/test_s3_services.py` adopted (README, assumption 9).
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from homeassistant.exceptions import ServiceValidationError
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.notify_switchboard.const import DOMAIN

from .conftest import make_entry, make_person, make_target

SERVICE_EXPLAIN = "explain"

# The exact keys of one person's answer (contract v0.4, "the response is a
# mapping ... Each person's value has exactly these keys").
PERSON_KEYS = frozenset(
    {"decision", "until", "reason", "detail", "outputs", "missing_outputs"}
)


async def explain(hass, **data):
    """Call `notify_switchboard.explain` the way a caller has to."""
    assert hass.services.has_service(DOMAIN, SERVICE_EXPLAIN), (
        f"{DOMAIN}.{SERVICE_EXPLAIN} must exist (contract v0.4, ADR-0018 §1)"
    )
    return await hass.services.async_call(
        DOMAIN, SERVICE_EXPLAIN, data, blocking=True, return_response=True
    )


def person_answer(response, person: str) -> dict:
    """Return one person's entry of an `explain` response, checking its shape."""
    assert "persons" in response, (
        "the response is keyed `target` / `priority` / `persons` "
        "(contract v0.4, ADR-0018 §1)"
    )
    assert person in response["persons"], (
        f"{person} is missing from the answer; `persons` is a mapping keyed by "
        f"the `person.*` entity id, got {sorted(response['persons'])}"
    )
    answer = response["persons"][person]
    assert set(answer) == PERSON_KEYS, (
        f"{person}'s answer has keys {sorted(answer)}, expected exactly "
        f"{sorted(PERSON_KEYS)}"
    )
    assert answer["detail"], "`detail` is always present and non-empty"
    return answer


# ---------------------------------------------------------------------------
# The three decisions
# ---------------------------------------------------------------------------


async def test_explain_says_routed_and_names_the_outputs_that_would_be_called(
    hass, enable_custom_integrations, install, mock_outputs, set_person
):
    """A person who would get the message: `routed`, with the services named."""
    mock_outputs("mobile_app_alice", "mobile_app_alice_tablet")
    set_person("person.alice", "home")
    await install(
        make_entry(
            hass,
            persons=[
                make_person(
                    "person.alice", ["mobile_app_alice", "mobile_app_alice_tablet"]
                )
            ],
            targets=[make_target("leak", "Leak", audience=["person.alice"])],
            default_target="leak",
        )
    )

    response = await explain(hass, target="leak")

    assert response["target"] == "leak"
    assert response["priority"] == "normal"
    answer = person_answer(response, "person.alice")
    assert answer["decision"] == "routed"
    assert answer["reason"] is None
    assert answer["until"] is None
    assert set(answer["outputs"]) == {
        "notify.mobile_app_alice",
        "notify.mobile_app_alice_tablet",
    }, (
        "`outputs` carries full `notify.*` service names, so the answer can be "
        "pasted into Developer tools (ADR-0018 §1)"
    )
    assert answer["missing_outputs"] == []


async def test_explain_says_dropped_with_the_presence_reason_and_the_state(
    hass, enable_custom_integrations, install, mock_outputs, set_person
):
    """`home_only` against somebody who is away: the `detail` names both sides."""
    mock_outputs("mobile_app_alice")
    set_person("person.alice", "not_home")
    await install(
        make_entry(
            hass,
            persons=[make_person("person.alice", ["mobile_app_alice"])],
            targets=[
                make_target(
                    "leak",
                    "Leak",
                    audience=["person.alice"],
                    presence_rule="home_only",
                )
            ],
            default_target="leak",
        )
    )

    answer = person_answer(await explain(hass, target="leak"), "person.alice")

    assert answer["decision"] == "dropped"
    assert answer["reason"] == "presence"
    assert answer["until"] is None
    assert answer["outputs"] == [], (
        "nothing would be called, so `outputs` is empty (ADR-0018 §1)"
    )
    detail = answer["detail"]
    assert "home_only" in detail or "not_home" in detail, (
        "the `detail` of a presence drop must name the rule or the person's "
        f"current state so the user knows what to change; got {detail!r}"
    )


async def test_explain_says_dropped_and_names_the_silence_entity_that_is_on(
    hass, enable_custom_integrations, install, mock_outputs, set_person
):
    """Naming which of two switches is the one that is on is the whole question."""
    mock_outputs("mobile_app_alice")
    set_person("person.alice", "home")
    hass.states.async_set("input_boolean.quiet_hours", "on")
    hass.states.async_set("input_boolean.movie_night", "off")
    await install(
        make_entry(
            hass,
            persons=[
                make_person(
                    "person.alice",
                    ["mobile_app_alice"],
                    silence_entities=[
                        "input_boolean.movie_night",
                        "input_boolean.quiet_hours",
                    ],
                )
            ],
            targets=[make_target("leak", "Leak", audience=["person.alice"])],
            default_target="leak",
        )
    )

    answer = person_answer(await explain(hass, target="leak"), "person.alice")

    assert answer["decision"] == "dropped"
    assert answer["reason"] == "silenced"
    assert "input_boolean.quiet_hours" in answer["detail"], (
        "the `detail` of a silence drop must name the entity that is `on`; got "
        f"{answer['detail']!r}"
    )
    assert "input_boolean.movie_night" not in answer["detail"], (
        "naming a silence entity that is `off` sends the user to the wrong switch"
    )


async def test_explain_says_deferred_with_the_wake_time_as_until(
    hass, enable_custom_integrations, install, mock_outputs, set_person
):
    """A silenced person with a `wake_time` is late, not dropped."""
    mock_outputs("mobile_app_alice")
    set_person("person.alice", "home")
    hass.states.async_set("input_boolean.night", "on")
    await install(
        make_entry(
            hass,
            persons=[
                make_person(
                    "person.alice",
                    ["mobile_app_alice"],
                    silence_entities=["input_boolean.night"],
                    wake_time="07:00:00",
                )
            ],
            targets=[make_target("leak", "Leak", audience=["person.alice"])],
            default_target="leak",
        )
    )

    answer = person_answer(await explain(hass, target="leak"), "person.alice")

    assert answer["decision"] == "deferred"
    assert answer["reason"] is None
    assert answer["outputs"] == ["notify.mobile_app_alice"], (
        "a deferred message is still going somewhere, so `outputs` is filled"
    )
    until = dt_util.parse_datetime(answer["until"])
    assert until is not None, (
        f"`until` must be an ISO 8601 instant, got {answer['until']!r}"
    )
    assert dt_util.as_local(until).time().isoformat() == "07:00:00", (
        "`until` is the person's next wake time (contract v0.4)"
    )


async def test_explain_says_dropped_for_a_snoozed_person(
    hass, enable_custom_integrations, install, mock_outputs, set_person
):
    """A snooze is a drop, not a deferral: `until` stays empty, `detail` says when."""
    mock_outputs("mobile_app_alice")
    set_person("person.alice", "home")
    await install(
        make_entry(
            hass,
            persons=[make_person("person.alice", ["mobile_app_alice"])],
            targets=[
                make_target(
                    "leak", "Leak", audience=["person.alice"], snooze_minutes=[30]
                )
            ],
            default_target="leak",
        )
    )
    await hass.services.async_call(
        DOMAIN,
        "snooze",
        {"target": "leak", "minutes": 30, "person": "person.alice"},
        blocking=True,
    )
    await hass.async_block_till_done()

    answer = person_answer(await explain(hass, target="leak"), "person.alice")

    assert answer["decision"] == "dropped"
    assert answer["reason"] == "snoozed"
    assert answer["until"] is None, (
        "`until` answers 'when will this arrive'; a dropped message never does "
        "(ADR-0018 §1). The snooze expiry belongs in `detail`."
    )
    assert answer["detail"]


async def test_explain_says_dropped_no_outputs_when_a_person_has_none(
    hass, enable_custom_integrations, install, set_person
):
    """The silent, permanent failure this sprint also raises a repair for."""
    set_person("person.alice", "home")
    await install(
        make_entry(
            hass,
            persons=[make_person("person.alice", [])],
            targets=[make_target("leak", "Leak", audience=["person.alice"])],
            default_target="leak",
        )
    )

    answer = person_answer(await explain(hass, target="leak"), "person.alice")

    assert answer["decision"] == "dropped"
    assert answer["reason"] == "no_outputs"
    assert answer["outputs"] == []


# ---------------------------------------------------------------------------
# Missing outputs, audience, priority
# ---------------------------------------------------------------------------


async def test_explain_separates_outputs_that_exist_from_outputs_that_do_not(
    hass, enable_custom_integrations, install, mock_outputs, set_person
):
    """A typo in an output is invisible until three failed deliveries; not here."""
    mock_outputs("mobile_app_alice")
    set_person("person.alice", "home")
    await install(
        make_entry(
            hass,
            persons=[
                make_person("person.alice", ["mobile_app_alice", "mobile_app_typo"])
            ],
            targets=[make_target("leak", "Leak", audience=["person.alice"])],
            default_target="leak",
        )
    )

    answer = person_answer(await explain(hass, target="leak"), "person.alice")

    assert answer["decision"] == "routed"
    assert answer["outputs"] == ["notify.mobile_app_alice"]
    assert answer["missing_outputs"] == ["notify.mobile_app_typo"], (
        "an output that is not a registered `notify.*` service is reported "
        "separately, whatever the decision (contract v0.4)"
    )


async def test_explain_covers_the_whole_audience_and_can_be_asked_about_one_person(
    hass, enable_custom_integrations, install, mock_outputs, set_person
):
    """No `person` field means the whole audience; one `person` means one answer."""
    mock_outputs("mobile_app_alice", "mobile_app_bob")
    set_person("person.alice", "home")
    set_person("person.bob", "home")
    await install(
        make_entry(
            hass,
            persons=[
                make_person("person.alice", ["mobile_app_alice"]),
                make_person("person.bob", ["mobile_app_bob"]),
            ],
            targets=[
                make_target("leak", "Leak", audience=["person.alice", "person.bob"])
            ],
            default_target="leak",
        )
    )

    whole = await explain(hass, target="leak")
    assert set(whole["persons"]) == {"person.alice", "person.bob"}

    one = await explain(hass, target="leak", person="person.bob")
    assert set(one["persons"]) == {"person.bob"}


async def test_explain_answers_not_in_audience_instead_of_refusing(
    hass, enable_custom_integrations, install, mock_outputs, set_person
):
    """Asking why a row never reaches somebody is a question, not a mistake."""
    mock_outputs("mobile_app_alice", "mobile_app_bob")
    set_person("person.alice", "home")
    set_person("person.bob", "home")
    await install(
        make_entry(
            hass,
            persons=[
                make_person("person.alice", ["mobile_app_alice"]),
                make_person("person.bob", ["mobile_app_bob"]),
            ],
            targets=[make_target("leak", "Leak", audience=["person.alice"])],
            default_target="leak",
        )
    )

    answer = person_answer(
        await explain(hass, target="leak", person="person.bob"), "person.bob"
    )

    assert answer["decision"] == "dropped"
    assert answer["reason"] == "not_in_audience"


async def test_explain_honours_a_priority_override_the_way_a_real_call_does(
    hass, enable_custom_integrations, install, mock_outputs, set_person
):
    """`critical` bypasses silence in the explanation exactly as in the routing."""
    mock_outputs("mobile_app_alice")
    set_person("person.alice", "home")
    hass.states.async_set("input_boolean.night", "on")
    await install(
        make_entry(
            hass,
            persons=[
                make_person(
                    "person.alice",
                    ["mobile_app_alice"],
                    silence_entities=["input_boolean.night"],
                )
            ],
            targets=[make_target("leak", "Leak", audience=["person.alice"])],
            default_target="leak",
        )
    )

    silenced = await explain(hass, target="leak")
    assert person_answer(silenced, "person.alice")["decision"] == "dropped"

    bypassed = await explain(hass, target="leak", priority="critical")
    assert bypassed["priority"] == "critical"
    assert person_answer(bypassed, "person.alice")["decision"] == "routed"


# ---------------------------------------------------------------------------
# Purity
# ---------------------------------------------------------------------------


async def test_explain_changes_nothing_at_all(
    hass, enable_custom_integrations, install, mock_outputs, set_person
):
    """No call, no counter, no event, no deferral, no snooze touched."""
    calls = mock_outputs("mobile_app_alice", "mobile_app_bob")
    set_person("person.alice", "home")
    set_person("person.bob", "home")
    hass.states.async_set("input_boolean.night", "on")
    await install(
        make_entry(
            hass,
            persons=[
                make_person("person.alice", ["mobile_app_alice"]),
                # Silenced with a wake time: an implementation that "explains"
                # by routing for real would queue a deferral here.
                make_person(
                    "person.bob",
                    ["mobile_app_bob"],
                    silence_entities=["input_boolean.night"],
                    wake_time="07:00:00",
                ),
            ],
            targets=[
                make_target(
                    "leak",
                    "Leak",
                    audience=["person.alice", "person.bob"],
                    snooze_minutes=[30],
                )
            ],
            default_target="leak",
        )
    )
    await hass.services.async_call(
        DOMAIN,
        "snooze",
        {"target": "leak", "minutes": 30, "person": "person.alice"},
        blocking=True,
    )
    await hass.async_block_till_done()

    before = {
        entity_id: hass.states.get(entity_id).state
        for entity_id in (
            "sensor.switchboard_routed_today",
            "sensor.switchboard_dropped_today",
            "sensor.switchboard_deferred_today",
            "sensor.alice_active_snoozes",
            "sensor.alice_last_notification",
            "event.switchboard_delivery",
        )
    }
    calls["mobile_app_alice"].clear()

    await explain(hass, target="leak")
    await explain(hass, target="leak", priority="critical")
    await hass.async_block_till_done()

    assert calls["mobile_app_alice"] == [], (
        "`explain` evaluates; it never calls an output (ADR-0018 §1)"
    )
    for entity_id, state in before.items():
        assert hass.states.get(entity_id).state == state, (
            f"{entity_id} moved from {state!r} to "
            f"{hass.states.get(entity_id).state!r}: `explain` is a pure "
            "evaluation (contract v0.4)"
        )


async def test_explain_does_not_queue_the_deferral_it_predicts(
    hass, enable_custom_integrations, install, mock_outputs, set_person
):
    """Nothing must arrive at the wake time because somebody asked a question."""
    calls = mock_outputs("mobile_app_alice")
    set_person("person.alice", "home")
    hass.states.async_set("input_boolean.night", "on")
    await install(
        make_entry(
            hass,
            persons=[
                make_person(
                    "person.alice",
                    ["mobile_app_alice"],
                    silence_entities=["input_boolean.night"],
                    wake_time="07:00:00",
                )
            ],
            targets=[make_target("leak", "Leak", audience=["person.alice"])],
            default_target="leak",
        )
    )

    assert (
        person_answer(await explain(hass, target="leak"), "person.alice")["decision"]
        == "deferred"
    )

    # Past any wake time this test could have landed on.
    hass.states.async_set("input_boolean.night", "off")
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(days=1, minutes=5))
    await hass.async_block_till_done()

    assert calls["mobile_app_alice"] == [], (
        "an explained deferral is not a queued deferral (ADR-0018 §1)"
    )


# ---------------------------------------------------------------------------
# Refusals
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("data", "translation_key"),
    [
        ({"target": "nope"}, "unknown_target"),
        ({"target": "leak", "person": "person.nobody"}, "unknown_person"),
    ],
)
async def test_explain_refuses_an_unknown_target_or_person(
    hass, enable_custom_integrations, install, mock_outputs, data, translation_key
):
    """Same refusals, same translation keys as the five acting services (ADR-0015)."""
    mock_outputs("mobile_app_alice")
    await install(
        make_entry(
            hass,
            persons=[make_person("person.alice", ["mobile_app_alice"])],
            targets=[make_target("leak", "Leak", audience=["person.alice"])],
            default_target="leak",
        )
    )

    assert hass.services.has_service(DOMAIN, SERVICE_EXPLAIN)
    with pytest.raises(ServiceValidationError) as err:
        await hass.services.async_call(
            DOMAIN, SERVICE_EXPLAIN, data, blocking=True, return_response=True
        )

    assert err.value.translation_domain == DOMAIN
    assert err.value.translation_key == translation_key


async def test_explain_must_be_called_with_return_response(
    hass, enable_custom_integrations, install, mock_outputs
):
    """`SupportsResponse.ONLY`: a call that discards the answer is refused by core."""
    mock_outputs("mobile_app_alice")
    await install(
        make_entry(
            hass,
            persons=[make_person("person.alice", ["mobile_app_alice"])],
            targets=[make_target("leak", "Leak", audience=["person.alice"])],
            default_target="leak",
        )
    )

    assert hass.services.has_service(DOMAIN, SERVICE_EXPLAIN)
    with pytest.raises(ServiceValidationError) as err:
        await hass.services.async_call(
            DOMAIN, SERVICE_EXPLAIN, {"target": "leak"}, blocking=True
        )

    # Core's own refusal for a service registered `SupportsResponse.ONLY`
    # (`homeassistant/core.py`, `ServiceRegistry.async_call`, lines 2914-2918).
    assert err.value.translation_key == "service_lacks_response_request"


# ---------------------------------------------------------------------------
# Translation
# ---------------------------------------------------------------------------


async def test_the_detail_is_written_in_the_instance_language(
    hass, enable_custom_integrations, install, mock_outputs, set_person
):
    """`detail` is a translated sentence, not an English one with a French UI.

    Nothing here pins the wording: what is asserted is that the same scenario
    produces a different sentence on a French instance than on an English one,
    the same way `test_s3_entities.py` checks the entity names.
    """
    details: dict[str, str] = {}
    for language in ("en", "fr"):
        hass.config.language = language
        mock_outputs("mobile_app_alice")
        set_person("person.alice", "home")
        hass.states.async_set("input_boolean.night", "on")
        entry = make_entry(
            hass,
            persons=[
                make_person(
                    "person.alice",
                    ["mobile_app_alice"],
                    silence_entities=["input_boolean.night"],
                )
            ],
            targets=[make_target("leak", "Leak", audience=["person.alice"])],
            default_target="leak",
            entry_id=f"ns_explain_{language}",
        )
        await install(entry)

        answer = person_answer(await explain(hass, target="leak"), "person.alice")
        details[language] = answer["detail"]

        await hass.config_entries.async_remove(entry.entry_id)
        await hass.async_block_till_done()

    assert details["fr"] != details["en"], (
        "the `detail` of a silenced drop reads the same in French as in "
        f"English ({details['en']!r}); it is not translated (ADR-0018 §1)"
    )
