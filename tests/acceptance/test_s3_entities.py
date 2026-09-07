"""Translated entity names with frozen entity ids (contract v0.3, ADR-0017).

Written before the Sprint 3 implementation exists, against:

- `docs/contract.md` §"v0.3 addendum (ADR-0017)" → "Names"
- `docs/ADR/0017-debts-and-robustness.md` §2
- `docs/sprints/sprint-3-brief.md` items 1 and 2

The property under test is a *pair*, and only the pair is interesting:

- the friendly name a user reads must be in the instance language;
- the entity id an `alert:`, a card or an automation is written against must
  be the English form frozen by the contract, **in every language**.

Doing only the first half is what a naive `_attr_translation_key` change
gives, and on a French or Spanish instance it silently breaks the second
half: `fr` and `es` are both in `homeassistant/generated/languages.py`
`NATIVE_ENTITY_IDS`, so `EntityPlatform.async_load_translations`
(`homeassistant/helpers/entity_platform.py`) would build the object id out of
the localized name. See `tests/acceptance/README.md` §"Sprint 3" for the
mechanism and for how the language is switched here.

Nothing below asserts *which* French words are used: the expected name is
read from the integration's own `translations/fr.json` through
`homeassistant.helpers.translation.async_get_translations`. What is asserted
is that the string exists, that it is what the entity shows, and that it is
not the English one.
"""

from __future__ import annotations

import pytest
from homeassistant.helpers import translation

from custom_components.notify_switchboard.const import DOMAIN

from .conftest import make_entry, make_person, make_target

# `entity.<platform>.<translation_key>.name` for every entity of the
# integration, keyed by the frozen entity id it must appear on
# (ADR-0017 §2, table). The person-scoped ones are formatted with the
# person's object_id.
GLOBAL_ENTITIES: dict[str, str] = {
    "sensor.switchboard_routed_today": "sensor.routed_today",
    "sensor.switchboard_dropped_today": "sensor.dropped_today",
    "sensor.switchboard_deferred_today": "sensor.deferred_today",
    "event.switchboard_delivery": "event.delivery",
}

PERSON_ENTITIES: dict[str, str] = {
    "binary_sensor.{object_id}_silenced": "binary_sensor.silenced",
    "sensor.{object_id}_last_notification": "sensor.last_notification",
    "sensor.{object_id}_active_snoozes": "sensor.active_snoozes",
}


def _translation_key(suffix: str) -> str:
    """Return the full translation key of an entity name."""
    return f"component.{DOMAIN}.entity.{suffix}.name"


def _expected_entity_ids(object_id: str) -> dict[str, str]:
    """Return {frozen entity id: entity-name translation suffix}."""
    expected = dict(GLOBAL_ENTITIES)
    for template, suffix in PERSON_ENTITIES.items():
        expected[template.format(object_id=object_id)] = suffix
    return expected


def _make_entry(hass):
    """Build the one-person, one-target entry every test below uses."""
    return make_entry(
        hass,
        persons=[make_person("person.alice", ["mobile_app_alice"])],
        targets=[make_target("leak", "Leak", audience=["person.alice"])],
        default_target="leak",
    )


@pytest.mark.parametrize("language", ["fr", "en"])
async def test_entity_ids_are_the_frozen_english_ones_in_any_language(
    hass, enable_custom_integrations, install, language
):
    """Contract §"Names": the ids do not move when the instance is not English.

    `fr` is a `NATIVE_ENTITY_IDS` language, so this is a real risk and not a
    formality: without `Entity.suggested_object_id` returning the frozen form,
    a fresh French install comes up with French object ids.
    """
    hass.config.language = language
    await install(_make_entry(hass))

    for entity_id in _expected_entity_ids("alice"):
        assert hass.states.get(entity_id) is not None, (
            f"{entity_id} must exist verbatim on a '{language}' instance "
            "(docs/contract.md, frozen names)"
        )


async def test_every_entity_name_is_translated_in_all_three_languages(
    hass, enable_custom_integrations, install
):
    """`strings.json` and en/fr/es carry an `entity.<platform>.<key>.name` for each entity."""
    await install(_make_entry(hass))

    suffixes = set(_expected_entity_ids("alice").values())
    per_language: dict[str, dict[str, str]] = {}
    for language in ("en", "fr", "es"):
        strings = await translation.async_get_translations(
            hass, language, "entity", {DOMAIN}
        )
        for suffix in suffixes:
            key = _translation_key(suffix)
            assert key in strings, (
                f"translations/{language}.json must define {key} "
                "(ADR-0017 §2: every entity of this integration is named "
                "through a translation key)"
            )
            assert strings[key], f"{key} is empty in translations/{language}.json"
        per_language[language] = strings

    # A translation file that merely copies the English name is not a
    # translation; the point of the sprint is that a French user reads French.
    for language in ("fr", "es"):
        translated = [
            suffix
            for suffix in suffixes
            if per_language[language][_translation_key(suffix)]
            != per_language["en"][_translation_key(suffix)]
        ]
        assert translated, (
            f"translations/{language}.json repeats every English entity name; "
            "the entities are not actually translated"
        )


@pytest.mark.parametrize("language", ["fr", "en"])
async def test_friendly_names_are_in_the_instance_language(
    hass, enable_custom_integrations, install, language
):
    """The name a user reads follows `hass.config.language`, the id does not."""
    hass.config.language = language
    await install(_make_entry(hass))

    strings = await translation.async_get_translations(
        hass, language, "entity", {DOMAIN}
    )

    for entity_id, suffix in _expected_entity_ids("alice").items():
        state = hass.states.get(entity_id)
        assert state is not None
        expected_name = strings[_translation_key(suffix)]
        friendly_name = state.attributes.get("friendly_name")
        assert friendly_name is not None, f"{entity_id} has no friendly_name"
        # `_attr_has_entity_name` composes "<device> <entity name>", so the
        # translated entity name is the tail; the head (the router, or the
        # person) is not part of what this test pins.
        assert friendly_name.endswith(expected_name), (
            f"{entity_id} shows {friendly_name!r} on a '{language}' instance, "
            f"expected it to end with the translated name {expected_name!r}"
        )


async def test_a_french_instance_shows_no_english_entity_name(
    hass, enable_custom_integrations, install
):
    """The regression this sprint pays off: English names on a French instance."""
    hass.config.language = "fr"
    await install(_make_entry(hass))

    english = await translation.async_get_translations(hass, "en", "entity", {DOMAIN})
    french = await translation.async_get_translations(hass, "fr", "entity", {DOMAIN})

    for entity_id, suffix in _expected_entity_ids("alice").items():
        key = _translation_key(suffix)
        if english[key] == french[key]:
            # A word that is legitimately identical in both languages proves
            # nothing either way.
            continue
        friendly_name = hass.states.get(entity_id).attributes["friendly_name"]
        assert not friendly_name.endswith(english[key]), (
            f"{entity_id} still shows the English name {english[key]!r} on a "
            "French instance (docs/known-issues.md, 2026-09-07)"
        )


async def test_deferred_today_sensor_exists(hass, enable_custom_integrations, install):
    """Brief item 2: the deferral counter is a public name from 0.3.0 on."""
    await install(_make_entry(hass))

    state = hass.states.get("sensor.switchboard_deferred_today")
    assert state is not None
    assert state.state == "0"
