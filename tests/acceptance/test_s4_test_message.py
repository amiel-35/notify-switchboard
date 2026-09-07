"""Testing a person or a target from the options menu, and reading the result.

Written before the Sprint 4 implementation exists, against:

- `docs/contract.md` §"v0.4 addendum (ADR-0018)" → "The test-message tag"
- `docs/ADR/0018-zero-config-and-explainability.md` §6
- `docs/sprints/sprint-4-brief.md` item 6

`explain` says what *would* happen; only a real message proves the output
works. The two options-menu entries added here send one, through the ordinary
routing path — counted, evented, deferred or dropped like any other message —
and then show the `explain` answer for that same call in the step description.

The one public thing about a test message is its tag: `switchboard-test`, in
`data.tag`, so a caller, an automation or a Companion channel can tell a test
from the real thing. Everything else — the wording, the step layout — is the
coding agent's.
"""

from __future__ import annotations

from homeassistant.data_entry_flow import FlowResultType

from .conftest import make_entry, make_person, make_target

TEST_TAG = "switchboard-test"


def _result_text(result) -> str:
    """Return the `explain` summary the result step must carry."""
    assert result["type"] is FlowResultType.FORM, (
        "the test step ends on a form showing what happened; got "
        f"{result['type']} / {result.get('reason')}"
    )
    assert result["step_id"] == "test_result"
    text = (result["description_placeholders"] or {}).get("result")
    assert text, (
        "the result is carried by `description_placeholders['result']` (ADR-0018 §6)"
    )
    return text


def _household(hass):
    """One person, one row, and a default target pointing at it."""
    return make_entry(
        hass,
        persons=[make_person("person.alice", ["mobile_app_alice"])],
        targets=[make_target("leak", "Leak", audience=["person.alice"])],
        default_target="leak",
    )


async def test_testing_a_target_sends_one_tagged_message_through_the_real_path(
    hass, enable_custom_integrations, install, options_flow, mock_outputs, set_person
):
    """A real delivery, counted like any other, carrying the public test tag."""
    calls = mock_outputs("mobile_app_alice")
    set_person("person.alice", "home")
    entry = await install(_household(hass))

    result = await options_flow(entry, "test_target", {"slug": "leak"})

    assert len(calls["mobile_app_alice"]) == 1, (
        "the test step routes exactly one message (ADR-0018 §6); got "
        f"{calls['mobile_app_alice']}"
    )
    payload = calls["mobile_app_alice"][0].data
    assert payload["message"], "the message is translated, but it is not empty"
    assert payload["data"]["tag"] == TEST_TAG, (
        f"`data.tag` must be {TEST_TAG!r} (contract v0.4); got {payload['data']}"
    )
    assert hass.states.get("sensor.switchboard_routed_today").state == "1", (
        "a test message goes through the real routing path, so it is counted "
        "like any other message"
    )
    _result_text(result)


async def test_the_step_description_reports_what_happened_to_each_person(
    hass, enable_custom_integrations, install, options_flow, mock_outputs, set_person
):
    """The `explain` answer for the call that was just made, per person."""
    mock_outputs("mobile_app_alice", "mobile_app_bob")
    set_person("person.alice", "home")
    set_person("person.bob", "not_home")
    entry = await install(
        make_entry(
            hass,
            persons=[
                make_person("person.alice", ["mobile_app_alice"]),
                make_person("person.bob", ["mobile_app_bob"]),
            ],
            targets=[
                make_target(
                    "leak",
                    "Leak",
                    audience=["person.alice", "person.bob"],
                    presence_rule="home_only",
                )
            ],
            default_target="leak",
        )
    )

    text = _result_text(await options_flow(entry, "test_target", {"slug": "leak"}))

    for person in ("person.alice", "person.bob"):
        assert person in text, (
            f"the result names every person of the audience; {person} is "
            f"missing from {text!r}"
        )
    assert "mobile_app_alice" in text, (
        "for somebody the message reached, the result says where it went"
    )


async def test_testing_a_person_routes_through_a_row_that_reaches_them(
    hass, enable_custom_integrations, install, options_flow, mock_outputs, set_person
):
    """Testing a person needs a row; the default target is the first choice."""
    calls = mock_outputs("mobile_app_alice", "mobile_app_bob")
    set_person("person.alice", "home")
    set_person("person.bob", "home")
    entry = await install(
        make_entry(
            hass,
            persons=[
                make_person("person.alice", ["mobile_app_alice"]),
                make_person("person.bob", ["mobile_app_bob"]),
            ],
            targets=[
                make_target("leak", "Leak", audience=["person.alice"]),
                make_target("garage", "Garage", audience=["person.bob"]),
            ],
            default_target="leak",
        )
    )

    result = await options_flow(entry, "test_person", {"entity_id": "person.bob"})

    assert calls["mobile_app_alice"] == [], (
        "testing one person must not notify the whole household"
    )
    assert len(calls["mobile_app_bob"]) == 1, (
        "the default target does not reach this person, so the router falls "
        "back to a row whose audience does (ADR-0018 §6)"
    )
    assert calls["mobile_app_bob"][0].data["data"]["tag"] == TEST_TAG
    assert "person.bob" in _result_text(result)


async def test_testing_a_person_no_row_reaches_is_refused_rather_than_silent(
    hass, enable_custom_integrations, install, options_flow, mock_outputs, set_person
):
    """A person in no audience cannot be tested, and is told so."""
    mock_outputs("mobile_app_alice", "mobile_app_bob")
    set_person("person.alice", "home")
    set_person("person.bob", "home")
    entry = await install(
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

    result = await options_flow(entry, "test_person", {"entity_id": "person.bob"})

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "nothing_to_test"


async def test_a_test_message_never_rewrites_the_configuration(
    hass, enable_custom_integrations, install, options_flow, mock_outputs, set_person
):
    """The test steps read the table; they are not another way to edit it."""
    mock_outputs("mobile_app_alice")
    set_person("person.alice", "home")
    entry = await install(_household(hass))
    before = dict(entry.options)

    await options_flow(entry, "test_target", {"slug": "leak"})

    assert dict(entry.options) == before
