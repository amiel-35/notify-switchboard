"""The interface speaks to a human, not to the code (Sprint 7.1).

Written before the 0.7.1 implementation exists, against
`docs/sprints/sprint-7.1-brief.md`. Two halves:

1. a sweep of `strings.json` and the three translations — no raw entity id and
   no code word may reach a title, a label or a description, in any language;
2. the code that builds what a user reads at runtime — the option labels of the
   two selectors, the friendly name a step description interpolates, and the
   test result — which no amount of rewriting in the JSON can fix.

The first half is deliberately mechanical: the wording of a sentence is a
matter of taste and belongs to the maintainer, but "does this screen show
somebody `person.dev_bob`" is a question a test can answer.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_mock_service,
)

from custom_components.notify_switchboard import dispatcher
from custom_components.notify_switchboard.config_flow import (
    _audience_options,
    _output_label,
    _output_options,
    _person_label,
    _target_label,
)
from custom_components.notify_switchboard.const import (
    DECISION_DEFERRED,
    DECISION_ROUTED,
    DROP_DELIVERY_FAILED,
    DROP_EXPIRED,
    DROP_NO_OUTPUTS,
    DROP_NOT_IN_AUDIENCE,
    DROP_NOT_NOTIFIED,
    DROP_PRESENCE,
    DROP_RECURSION,
    DROP_SILENCED,
    DROP_SNOOZED,
    DROP_UNKNOWN_PERSON,
    DROP_UNKNOWN_TARGET,
    VALID_PRESENCE_RULES,
    VALID_PRIORITIES,
)
from custom_components.notify_switchboard.router import RoutingContext

from .test_config_flow import (  # noqa: PLC2701 - the flow helpers live there
    _add_person,
    _add_target,
    _create_entry,
    _options_step,
)
from .test_dispatcher import install, make_person, make_target

COMPONENT = (
    Path(__file__).resolve().parents[2] / "custom_components" / "notify_switchboard"
)
FILES = [
    COMPONENT / "strings.json",
    COMPONENT / "translations" / "en.json",
    COMPONENT / "translations" / "fr.json",
    COMPONENT / "translations" / "es.json",
]

PLACEHOLDER = re.compile(r"\{[^{}]*\}")

# A raw entity id in a sentence somebody reads is the single loudest symptom of
# the interface speaking like the code (`person.dev_bob` in a description).
ENTITY_ID = re.compile(r"\b(?:person|alert|notify)\.[a-z0-9_]+", re.IGNORECASE)

# Words that only mean something to whoever wrote the router.
CODE_WORDS = re.compile(
    r"\b("
    r"slug|slugs"
    r"|entity|entities|entit[ée]|entit[ée]s|entidad|entidades"
    r"|service notify|servicio notify"
    r"|legacy|payload|retry|retries|r[ée]essay[ée]|r[ée]essay[ée]e"
    r"|store|flow|row|rows|target_map"
    r")\b",
    re.IGNORECASE,
)

# The two documented exceptions of the brief, and nothing else:
#
# - the short identifier explains itself with the service name it becomes,
#   which *is* the explanation a power user needs;
# - `explain` returns a response, and a script author cannot call it without
#   knowing the name of the option that asks for one.
ALLOWED_KEYS = {
    "options/step/target/data_description/slug",
    "services/explain/description",
}


def _walk(node: Any, path: tuple[str, ...] = ()) -> Iterator[tuple[str, str]]:
    """Yield every ("a/b/c", "text") leaf of a translation file."""
    if isinstance(node, dict):
        for key, value in node.items():
            yield from _walk(value, (*path, str(key)))
    elif isinstance(node, str):
        yield "/".join(path), node


def _read(file: Path) -> list[tuple[str, str]]:
    return list(_walk(json.loads(file.read_text(encoding="utf-8"))))


def _prose(key: str, text: str) -> str | None:
    """Return the text of a leaf a user actually reads, or None.

    `{placeholder}` names are stripped: `{entity_id}` is the name of a slot the
    router fills, not a word on the screen. So is the ready-to-paste `alert:`
    block of `target_saved`, which is YAML the user copies rather than prose.
    """
    if key in ALLOWED_KEYS:
        return None
    stripped = PLACEHOLDER.sub(" ", text)
    return stripped.replace("binary_sensor.CHANGE_ME", " ")


@pytest.mark.parametrize("file", FILES, ids=lambda file: file.name)
def test_no_raw_entity_id_reaches_a_title_a_label_or_a_description(file: Path):
    """`person.dev_bob` on a screen is the maintainer's own example of the bug."""
    offenders = [
        (key, text)
        for key, text in _read(file)
        if (prose := _prose(key, text)) is not None and ENTITY_ID.search(prose)
    ]

    assert not offenders, (
        f"{file.name} shows {len(offenders)} raw entity id(s) to the user; a "
        "screen names people and targets by the name Home Assistant shows "
        "(sprint 7.1, rule 2):\n"
        + "\n".join(f"  {key}: {text}" for key, text in offenders)
    )


@pytest.mark.parametrize("file", FILES, ids=lambda file: file.name)
def test_no_code_word_reaches_a_title_a_label_or_a_description(file: Path):
    """A household does not know what a slug, a payload or a flow is."""
    offenders = [
        (key, text, match.group(0))
        for key, text in _read(file)
        if (prose := _prose(key, text)) is not None
        and (match := CODE_WORDS.search(prose))
    ]

    assert not offenders, (
        f"{file.name} uses {len(offenders)} code word(s) on a screen "
        "(sprint 7.1, rule 2):\n"
        + "\n".join(f"  {key}: {word!r} in {text}" for key, text, word in offenders)
    )


@pytest.mark.parametrize("file", FILES, ids=lambda file: file.name)
def test_the_two_new_option_labels_exist(file: Path):
    """The runtime label builders read these; a missing one is a raw name."""
    keys = dict(_read(file))
    for key in ("common/home_assistant_app", "common/persistent_notification"):
        assert keys.get(key), f"{file.name} must define {key}"


# ---------------------------------------------------------------------------
# The labels the two selectors carry
# ---------------------------------------------------------------------------

TEXTS = {
    "home_assistant_app": "Home Assistant app",
    "persistent_notification": "Home Assistant notifications",
}


def test_a_companion_service_is_labelled_with_the_device_name():
    """The chip says "Bob's iPhone", not `mobile_app_bob_s_iphone`."""
    label = _output_label(
        "mobile_app_bob_s_iphone", {"mobile_app_bob_s_iphone": "Bob's iPhone"}, TEXTS
    )
    assert label == "Bob's iPhone (Home Assistant app)"


def test_the_built_in_dashboard_notification_is_named_in_words():
    """`persistent_notification` is the one core service worth a real name."""
    assert (
        _output_label("persistent_notification", {}, TEXTS)
        == "Home Assistant notifications"
    )


def test_any_other_service_is_at_least_readable():
    """Underscores out, first letter up, own name kept in brackets.

    ADR-0018 §2 amendment: a legacy service nobody registered through the
    Companion app has no friendlier name to hide behind, so the raw one stays
    -- somebody who has to go and change a configuration needs it.
    """
    assert (
        _output_label("airplay_bedroom", {}, TEXTS)
        == "Airplay bedroom (airplay_bedroom)"
    )


def test_the_audience_shows_the_name_it_actually_stores():
    """There the value is `notify.<service>`, so that is what the brackets say."""
    assert (
        _output_label("airplay_bedroom", {}, TEXTS, identifier="notify.airplay_bedroom")
        == "Airplay bedroom (notify.airplay_bedroom)"
    )


async def test_somebody_elses_phone_is_offered_by_its_device_name(
    hass: HomeAssistant,
) -> None:
    """The three label kinds, read back off the `outputs` selector itself.

    ADR-0018 §2 amendment 2026-09-07: every option carries a readable label,
    not only the ones this person owns. Only the marker is reserved for those.
    """
    async_mock_service(hass, "notify", "mobile_app_alice_phone")
    async_mock_service(hass, "notify", "airplay_bedroom")

    options = _output_options(
        hass,
        [],
        "their device",
        {"mobile_app_alice_phone": "Alice's phone"},
        TEXTS,
    )

    by_value = {option["value"]: option["label"] for option in options}
    assert by_value["mobile_app_alice_phone"] == "Alice's phone (Home Assistant app)", (
        "another person's phone is named the way its owner named it, and the "
        f"`mobile_app_...` slug behind it is noise; got {by_value!r}"
    )
    assert by_value["airplay_bedroom"] == "Airplay bedroom (airplay_bedroom)", (
        f"an unrelated legacy service still reads as words; got {by_value!r}"
    )
    assert "their device" not in by_value["mobile_app_alice_phone"], (
        "the marker belongs to this person's own phones and to nothing else"
    )


async def test_no_output_option_is_left_showing_a_bare_service_name(
    hass: HomeAssistant,
) -> None:
    """The whole point of the amendment: no chip reads like a slug."""
    async_mock_service(hass, "notify", "mobile_app_bob_s_iphone")
    async_mock_service(hass, "notify", "mobile_app_alice_phone")
    async_mock_service(hass, "notify", "telegram_family")

    options = _output_options(
        hass,
        ["mobile_app_bob_s_iphone"],
        "their device",
        {
            "mobile_app_bob_s_iphone": "Bob's iPhone",
            "mobile_app_alice_phone": "Alice's phone",
        },
        TEXTS,
    )

    for option in options:
        assert option["label"] != option["value"], (
            f"{option['value']} is offered with no label at all"
        )


async def test_the_audience_offers_people_by_name_and_speakers_in_words(
    hass: HomeAssistant,
) -> None:
    """Every option of the audience selector carries a readable label."""
    async_mock_service(hass, "notify", "airplay_bedroom")
    hass.states.async_set("person.dev_bob", "home", {"friendly_name": "Bob"})

    options = _audience_options(hass, ["person.dev_bob"])

    by_value = {option["value"]: option["label"] for option in options}
    assert by_value["person.dev_bob"] == "Bob", (
        "a person is offered by the name Home Assistant shows, never by their "
        f"entity id; got {by_value['person.dev_bob']!r}"
    )
    assert by_value["notify.airplay_bedroom"].startswith("Airplay bedroom"), (
        "a speaker is offered in words, with its own name kept in brackets; "
        f"got {by_value['notify.airplay_bedroom']!r}"
    )
    assert "notify.airplay_bedroom" in by_value["notify.airplay_bedroom"], (
        "the label still has to name what it selects"
    )


async def test_this_persons_own_phone_is_labelled_with_its_device_name(
    hass: HomeAssistant,
) -> None:
    """The one option a frozen acceptance test lets us label (ADR-0018 §2)."""
    async_mock_service(hass, "notify", "mobile_app_bob_s_iphone")

    options = _output_options(
        hass,
        ["mobile_app_bob_s_iphone"],
        "their device",
        {"mobile_app_bob_s_iphone": "Bob's iPhone"},
    )

    assert options[0]["label"].startswith("Bob's iPhone"), (
        f"the device name comes first; got {options[0]['label']!r}"
    )
    assert "their device" in options[0]["label"]
    assert "mobile_app_bob_s_iphone" in options[0]["label"]


# ---------------------------------------------------------------------------
# The names a step description and a result interpolate
# ---------------------------------------------------------------------------


def test_a_person_is_named_by_their_friendly_name(hass: HomeAssistant) -> None:
    """`person.dev_bob` is renamed "Bob" in the UI; the flow follows."""
    hass.states.async_set("person.dev_bob", "home", {"friendly_name": "Bob"})
    assert _person_label(hass, "person.dev_bob") == "Bob"


def test_a_person_with_no_state_still_reads_as_a_name(hass: HomeAssistant) -> None:
    """At setup the `person` integration may not have written its states yet."""
    assert _person_label(hass, "person.dev_bob") == "Dev Bob"


def test_a_target_is_named_by_its_name_not_its_identifier() -> None:
    """The short identifier is plumbing; the name is what the user chose."""
    assert _target_label({"slug": "water_leak", "name": "Water leak"}) == "Water leak"
    assert _target_label({"slug": "water_leak"}) == "water_leak"


async def test_the_person_step_greets_the_person_by_name(
    hass: HomeAssistant,
) -> None:
    """The screen the maintainer called unreadable, read back."""
    async_mock_service(hass, "notify", "mobile_app_alice")
    hass.states.async_set("person.dev_bob", "home", {"friendly_name": "Bob"})
    entry = await _create_entry(hass)

    result = await _options_step(hass, entry, "person", {"entity_id": "person.dev_bob"})

    placeholders = result["description_placeholders"] or {}
    assert placeholders["person"] == "Bob", (
        "the description names the person the way the household does; got "
        f"{placeholders['person']!r}"
    )


async def test_the_night_step_greets_the_person_by_name(
    hass: HomeAssistant,
) -> None:
    """Same for the second half of the person editor."""
    async_mock_service(hass, "notify", "mobile_app_alice")
    hass.states.async_set("person.dev_bob", "home", {"friendly_name": "Bob"})
    entry = await _create_entry(hass)
    await _add_person(hass, entry, "person.dev_bob")

    result = await _options_step(
        hass, entry, "edit_person_advanced", {"entity_id": "person.dev_bob"}
    )

    assert (result["description_placeholders"] or {})["person"] == "Bob"


async def test_the_person_pickers_list_people_by_name(hass: HomeAssistant) -> None:
    """Four pickers, one selector each, all of them showing entity ids in 0.7.0."""
    async_mock_service(hass, "notify", "mobile_app_alice")
    hass.states.async_set("person.dev_bob", "home", {"friendly_name": "Bob"})
    entry = await _create_entry(hass)
    await _add_person(hass, entry, "person.dev_bob")

    for step in (
        "edit_person",
        "edit_person_advanced",
        "remove_person",
        "test_person",
    ):
        result = await _options_step(hass, entry, step)
        options = _selector_options(result, "entity_id")
        assert options == [{"value": "person.dev_bob", "label": "Bob"}], (
            f"the {step!r} picker still lists entity ids; got {options}"
        )


async def test_the_target_pickers_list_targets_by_name(hass: HomeAssistant) -> None:
    """A target is picked by the name its household gave it."""
    async_mock_service(hass, "notify", "mobile_app_alice")
    hass.states.async_set("person.alice", "home", {"friendly_name": "Alice"})
    entry = await _create_entry(hass)
    await _add_person(hass, entry)
    await _add_target(hass, entry, slug="water_leak", name="Water leak")

    for step, key in (
        ("edit_target", "slug"),
        ("edit_target_advanced", "slug"),
        ("edit_target_escalation", "slug"),
        ("remove_target", "slug"),
        ("test_target", "slug"),
        ("general", "default_target"),
    ):
        result = await _options_step(hass, entry, step)
        labels = {
            option["value"]: option["label"]
            for option in _selector_options(result, key)
        }
        assert labels["water_leak"] == "Water leak", (
            f"the {step!r} picker still lists short identifiers; got {labels}"
        )


async def test_the_test_result_names_each_person(hass: HomeAssistant) -> None:
    """One bullet per person, opening on the name the household uses."""
    async_mock_service(hass, "notify", "mobile_app_alice")
    hass.states.async_set("person.dev_bob", "home", {"friendly_name": "Bob"})
    entry = await _create_entry(hass)
    await _add_person(hass, entry, "person.dev_bob")

    result = await _options_step(hass, entry, "test_target", {"slug": "default"})

    text = (result["description_placeholders"] or {})["result"]
    assert text.startswith("- Bob "), (
        "the result opens on the person's name; the entity id stays in "
        f"brackets for whoever has to go and fix something. Got {text!r}"
    )
    assert "person.dev_bob" in text


# ---------------------------------------------------------------------------
# The outputs an `explain` sentence names
# ---------------------------------------------------------------------------


async def test_the_routed_detail_names_outputs_the_way_the_picker_does(
    hass: HomeAssistant,
) -> None:
    """Where a message would go is answered with devices, not service names.

    The `outputs` key of the answer keeps the full `notify.*` names a script
    pastes into Developer tools (ADR-0018 §1); the `detail` **sentence** is the
    half a household reads, and it is built from exactly the labels the
    `outputs` picker offers -- otherwise the same phone is "Bob's iPhone" on
    one screen and `notify.mobile_app_bob_s_iphone` on the next.
    """
    async_mock_service(hass, "notify", "mobile_app_bob_s_iphone")
    async_mock_service(hass, "notify", "persistent_notification")
    async_mock_service(hass, "notify", "airplay_bedroom")
    registration = MockConfigEntry(
        domain="mobile_app",
        source="registration",
        title="Bob's iPhone",
        data={"device_name": "Bob's iPhone", "device_id": "device-bob"},
    )
    registration.add_to_hass(hass)
    hass.states.async_set("person.alice", "home")
    entry = await install(
        hass,
        [
            make_person(
                "person.alice",
                [
                    "mobile_app_bob_s_iphone",
                    "persistent_notification",
                    "airplay_bedroom",
                ],
            )
        ],
        [make_target("leak", audience=["person.alice"])],
        "leak",
    )

    answer = (await entry.runtime_data.switchboard.async_explain("leak"))["persons"][
        "person.alice"
    ]

    detail = answer["detail"]
    assert "Bob's iPhone" in detail, (
        f"a Companion output is named by its device; got {detail!r}"
    )
    assert "Home Assistant notifications" in detail, (
        f"the built-in dashboard notification has a name of its own; got {detail!r}"
    )
    assert "Airplay bedroom" in detail, (
        f"any other output is at least turned back into words; got {detail!r}"
    )
    assert "notify." not in detail, (
        "a service name is the code speaking; the sentence a household reads "
        f"names devices (0.7.1). Got {detail!r}"
    )
    assert answer["outputs"] == [
        "notify.mobile_app_bob_s_iphone",
        "notify.persistent_notification",
        "notify.airplay_bedroom",
    ], "the machine-readable `outputs` key is untouched (ADR-0018 §1)"


def _selector_options(result: Any, key: str) -> list[dict[str, str]]:
    """Return one `SelectSelector`'s options, always as `{value, label}`."""
    for marker, validator in result["data_schema"].schema.items():
        if str(marker) == key:
            return [
                option
                if isinstance(option, dict)
                else {"value": option, "label": option}
                for option in validator.config["options"]
            ]
    raise AssertionError(f"{key} is not a field of step {result.get('step_id')!r}")


# ---------------------------------------------------------------------------
# The code words a `detail` placeholder carries
# ---------------------------------------------------------------------------

# Every drop reason the contract defines. A reason with no `detail_<reason>`
# key falls back to the generic `detail_dropped`, whose sentence interpolates
# `{reason}` -- which is how a household ends up reading "delivery_failed".
DROP_REASONS = (
    DROP_NOT_IN_AUDIENCE,
    DROP_UNKNOWN_PERSON,
    DROP_PRESENCE,
    DROP_SILENCED,
    DROP_SNOOZED,
    DROP_RECURSION,
    DROP_UNKNOWN_TARGET,
    DROP_NO_OUTPUTS,
    DROP_DELIVERY_FAILED,
    DROP_EXPIRED,
    DROP_NOT_NOTIFIED,
)

# The `person.*` states the router reads. `unavailable` is in the list because
# a `person` entity really can be one, and "Alice is currently unavailable" is
# the code speaking exactly as `not_home` is.
PERSON_STATES = ("home", "not_home", "unknown", "unavailable")

# Nothing in this set may *be* what a placeholder puts on a screen: they are
# the router's own words for a choice the user made in words of their own.
#
# "Be", not "contain": ADR-0018 §2 keeps the stored value in brackets after the
# words -- "Only people who are at home (home_only)" -- for the same reason an
# output label keeps its service name, and a frozen acceptance test
# (`test_s4_explain.py`) holds that shape for the presence rule. What the
# amendment forbids is the identifier standing alone, with no words in front
# of it.
CODE_VALUES = frozenset(
    {*VALID_PRIORITIES, *VALID_PRESENCE_RULES, *PERSON_STATES, *DROP_REASONS}
)

SILENCE_ENTITY = "binary_sensor.night"


def _offenders(template: str, placeholders: dict[str, str]) -> dict[str, str]:
    """Return the placeholders this template actually shows, and that are code.

    A placeholder the template does not interpolate is a slot nobody reads --
    `{reason}` is set on every call and only `detail_dropped` prints it -- so
    only the ones the sentence really carries are judged.
    """
    return {
        name: value
        for name, value in placeholders.items()
        if f"{{{name}}}" in template and value in CODE_VALUES
    }


@pytest.mark.parametrize("language", ["en", "fr"])
async def test_no_detail_sentence_interpolates_a_code_word(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch, language: str
) -> None:
    """`explain` answers in words, placeholders included (sprint 7.1, rule 2).

    The JSON sweep above cannot see this one: the sentences are written in
    plain language and it is what the router *fills them with* that is not --
    `home_only`, `not_home`, `high`, `delivery_failed`. So the placeholders are
    read back at the moment they are substituted, for every decision and every
    drop reason the contract defines, in both the instance languages the sweep
    covers.
    """
    await hass.config.async_update(language=language)
    async_mock_service(hass, "notify", "mobile_app_alice")
    hass.states.async_set("person.alice", "not_home", {"friendly_name": "Alice"})
    hass.states.async_set(SILENCE_ENTITY, "on", {"friendly_name": "Night"})
    entry = await install(
        hass,
        [
            make_person(
                "person.alice",
                ["mobile_app_alice"],
                silence_entities=[SILENCE_ENTITY],
            )
        ],
        [make_target("leak", presence_rule="home_only")],
        "leak",
    )
    switchboard = entry.runtime_data.switchboard
    target = switchboard.table.targets["leak"]
    person = switchboard.table.persons["person.alice"]
    # Built by hand rather than read off the world: the point is the sentence,
    # not how a floor is discovered. A `high` floor on the one silence that is
    # `on` is what makes `detail_silenced_floor` the template that answers a
    # `normal` call.
    context = RoutingContext(
        now=dt_util.utcnow(),
        person_states={"person.alice": "not_home"},
        silenced={SILENCE_ENTITY: "high"},
    )

    filled: list[tuple[str, dict[str, str]]] = []
    original = dispatcher._fill

    def _spy(template: str, placeholders: Any) -> str:
        filled.append((template, dict(placeholders)))
        return original(template, placeholders)

    monkeypatch.setattr(dispatcher, "_fill", _spy)

    found: dict[str, str] = {}
    for key in (DECISION_ROUTED, DECISION_DEFERRED, *DROP_REASONS):
        filled.clear()
        await switchboard._async_detail(
            key,
            target,
            "person.alice",
            person,
            context,
            priority="normal",
            outputs=["notify.mobile_app_alice"],
            until=dt_util.utcnow(),
        )
        template, placeholders = filled[-1]
        found |= {
            f"{key}.{name}": value
            for name, value in _offenders(template, placeholders).items()
        }

    assert not found, (
        f"in {language!r}, {len(found)} `detail` placeholder(s) put one of the "
        "router's own words on a screen; a sentence a household reads names a "
        "rule, a whereabouts, an importance and a reason the way the pickers "
        f"do (sprint 7.1, rule 2):\n{found}"
    )
