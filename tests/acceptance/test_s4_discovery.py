"""Companion outputs and Focus sensors are discovered, not typed.

Written before the Sprint 4 implementation exists, against:

- `docs/ADR/0018-zero-config-and-explainability.md` §2 and §3
- `docs/sprints/sprint-4-brief.md` items 2 and 3

Up to 0.3.0, `outputs` is a free-text list. To fill it a newcomer has to know
that Companion push is a *legacy* notify service and that core names it
`slugify("mobile_app_" + <the device name>)` — and a typo produces no error,
only a repair three failed deliveries later.

Everything needed to do better is already in the instance: each Companion
registration is a `mobile_app` config entry carrying `user_id` and
`device_name`, and a `person.*` publishes the user it is linked to as its
`user_id` state attribute. This file pins the *behaviour* that follows, read
back through the flow result's own schema — the selector's options, their
order, their labels, and what is pre-selected — never through the
implementation's internals.

What the tests build, and why:

- **`mobile_app` config entries are real entries**, added to the entry
  registry with the registration payload shape core's own tests use
  (`$HA_CORE_SRC/tests/components/mobile_app/test_notify.py`), but the
  `mobile_app` component itself is never set up: the router reads config
  entries, and setting the component up would drag in http, webhooks and a
  push relay for nothing.
- **`user_id` values are plain strings.** The link the router follows is an
  equality between two stored ids; nothing reads the auth provider.
- **The push services are mocked** with `async_mock_service`, exactly as every
  other output in this suite is. A registration whose push service does not
  exist must not be offered, which is why the ordering test registers the
  services it expects to see and no others.
"""

from __future__ import annotations

import pytest
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import config_validation as cv, translation

from custom_components.notify_switchboard.const import DOMAIN

from .conftest import (
    make_entry,
    make_person,
    make_target,
    schema_field,
    selector_options,
    suggested_value,
)

# Two Home Assistant users. Only their ids matter: one is linked to the person
# being added, the other to somebody else's phone.
USER_ID = "01JCONFIGURED0000000000000"
OTHER_USER_ID = "01JSOMEBODYELSE0000000000"

SILENCE_DOMAINS = {"binary_sensor", "schedule", "input_boolean"}


def _installed_entry(hass):
    """Return the entry every test starts from: one person, one target."""
    return make_entry(
        hass,
        persons=[make_person("person.alice", ["mobile_app_alice"])],
        targets=[make_target("leak", "Leak", audience=["person.alice"])],
        default_target="leak",
    )


@pytest.fixture
def household(hass, mock_outputs, mobile_app_registration):
    """Set up two Companion registrations, their sensors and their services.

    `person.bob` is linked to `USER_ID` and owns "Phone One"; "Phone Two"
    belongs to another user entirely. `notify.telegram_family` is an unrelated
    legacy notify service that belongs to nobody, and `notify.mobile_app_alice`
    is the output the already-configured person uses.
    """
    mock_outputs(
        "mobile_app_phone_one",
        "mobile_app_phone_two",
        "mobile_app_alice",
        "telegram_family",
    )
    mobile_app_registration(
        "Phone One",
        user_id=USER_ID,
        binary_sensors={
            # iOS Focus, matched on its entity id …
            "phone_one_focus": None,
            # … and on its entity-registry translation key.
            "phone_one_mode": "focus",
            # Anything else the Companion app registers must stay out of it.
            "phone_one_is_charging": "is_charging",
        },
    )
    mobile_app_registration(
        "Phone Two",
        user_id=OTHER_USER_ID,
        binary_sensors={"phone_two_focus": None},
    )
    hass.states.async_set("person.bob", "home", {"user_id": USER_ID})


async def _open_outputs_step(hass, options_flow, entry, person="person.bob"):
    """Add a person through the options flow and stop on the outputs form."""
    result = await options_flow(entry, "person", {"entity_id": person})
    assert result["type"] is FlowResultType.FORM, (
        "picking the person opens a second step, because a form cannot react "
        "to a field it is showing (ADR-0018 §2); got "
        f"{result['type']} / {result.get('reason')}"
    )
    assert result["step_id"] == "person_outputs"
    return result


# ---------------------------------------------------------------------------
# The option list
# ---------------------------------------------------------------------------


async def test_outputs_is_a_multi_select_of_the_existing_notify_services(
    hass, enable_custom_integrations, install, options_flow, household
):
    """Every legacy `notify.*` is offered, except this integration's own."""
    entry = await install(_installed_entry(hass))

    result = await _open_outputs_step(hass, options_flow, entry)
    _marker, validator = schema_field(result, "outputs")
    values = [option["value"] for option in selector_options(result, "outputs")]

    assert validator.config["multiple"] is True
    assert validator.config["custom_value"] is True, (
        "a service that does not exist yet must still be typable (ADR-0018 §2)"
    )
    assert validator.config.get("sort") is False, (
        "the frontend must not re-sort the list: the order below is the point"
    )
    assert set(values) == {
        "mobile_app_phone_one",
        "mobile_app_phone_two",
        "mobile_app_alice",
        "telegram_family",
    }, f"unexpected option list {values}"
    assert not any(value.startswith("switchboard") for value in values), (
        "offering `notify.switchboard*` as an output configures a recursion "
        'the router then has to refuse (contract §"Output")'
    )


async def test_the_persons_own_phones_come_first_and_are_labelled(
    hass, enable_custom_integrations, install, options_flow, household
):
    """`person.user_id` ↔ the `mobile_app` entry's `user_id` — an exact link."""
    entry = await install(_installed_entry(hass))

    result = await _open_outputs_step(hass, options_flow, entry)
    options = selector_options(result, "outputs")

    assert options[0]["value"] == "mobile_app_phone_one", (
        "the service of the phone registered to this person's Home Assistant "
        f"user comes first; got {[option['value'] for option in options]}"
    )
    assert options[0]["label"] != options[0]["value"], (
        "and it is labelled, so the user can tell which one is theirs"
    )
    assert "mobile_app_phone_one" in options[0]["label"], (
        "the label still has to name the service it selects"
    )
    marker_free = [option for option in options[1:]]
    for option in marker_free:
        # 0.7.1 (ADR-0018 §2, amendment 2026-09-07): every option carries a
        # readable label; only the person's own phones carry the "this
        # person's device" marker. The value stays the raw service name.
        assert option["label"], f"{option['value']} must carry a readable label"
        assert option["label"] != "", "labels are never empty"
        assert "mobile_app_phone_one" not in option["label"] or option is options[0]


@pytest.mark.parametrize("language", ["en", "fr", "es"])
async def test_the_label_of_a_persons_own_phone_is_translated(
    hass, enable_custom_integrations, install, options_flow, household, language
):
    """The marker is a translated string, not an English word in a French UI."""
    hass.config.language = language
    entry = await install(_installed_entry(hass))

    strings = await translation.async_get_translations(
        hass, language, "common", {DOMAIN}
    )
    key = f"component.{DOMAIN}.common.this_persons_device"
    assert strings.get(key), f"translations/{language}.json must define {key}"

    result = await _open_outputs_step(hass, options_flow, entry)
    label = selector_options(result, "outputs")[0]["label"]
    assert strings[key] in label, (
        f"the label {label!r} does not use the translated marker "
        f"{strings[key]!r} (ADR-0018 §2)"
    )


# ---------------------------------------------------------------------------
# What is pre-selected
# ---------------------------------------------------------------------------


async def test_a_new_persons_phones_are_pre_selected(
    hass, enable_custom_integrations, install, options_flow, household
):
    """The point of the sprint: adding a person is one form, already filled."""
    entry = await install(_installed_entry(hass))

    result = await _open_outputs_step(hass, options_flow, entry)

    assert suggested_value(result, "outputs") == ["mobile_app_phone_one"], (
        "somebody else's phone and an unrelated notify service must be "
        "offered but not pre-selected"
    )


async def test_the_focus_binary_sensors_of_those_phones_are_pre_selected(
    hass, enable_custom_integrations, install, options_flow, household
):
    """iOS Focus, matched on the entity id or on the entity's translation key."""
    entry = await install(_installed_entry(hass))

    result = await _open_outputs_step(hass, options_flow, entry)
    _marker, validator = schema_field(result, "silence_entities")

    assert validator.config["multiple"] is True
    assert set(cv.ensure_list(validator.config["domain"])) == SILENCE_DOMAINS
    assert set(suggested_value(result, "silence_entities") or []) == {
        "binary_sensor.phone_one_focus",
        "binary_sensor.phone_one_mode",
    }, (
        "only the Focus sensors of this person's own devices are proposed: not "
        "their other Companion sensors, and not another person's phone "
        "(ADR-0018 §3)"
    )


async def test_a_person_with_no_linked_user_gets_nothing_pre_selected(
    hass, enable_custom_integrations, install, options_flow, household
):
    """No `user_id` on the `person.*` means no exact link, so no guessing."""
    hass.states.async_set("person.carol", "home")
    entry = await install(_installed_entry(hass))

    result = await _open_outputs_step(hass, options_flow, entry, person="person.carol")

    assert not suggested_value(result, "outputs"), (
        "without the `person.user_id` link there is nothing to discover, and "
        "guessing from the person's name is exactly what ADR-0018 §2 rejects"
    )
    assert not suggested_value(result, "silence_entities")
    for option in selector_options(result, "outputs"):
        assert option["label"] == option["value"]


async def test_editing_a_person_suggests_what_is_stored_not_what_is_discovered(
    hass, enable_custom_integrations, install, options_flow, household
):
    """Discovery must never silently re-add an output somebody removed."""
    entry = make_entry(
        hass,
        persons=[
            make_person("person.alice", ["mobile_app_alice"]),
            make_person("person.bob", ["telegram_family"]),
        ],
        targets=[make_target("leak", "Leak", audience=["person.alice"])],
        default_target="leak",
    )
    await install(entry)

    result = await options_flow(entry, "edit_person", {"entity_id": "person.bob"})
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "person_outputs"

    assert suggested_value(result, "outputs") == ["telegram_family"], (
        "the stored row wins over discovery when editing an existing person"
    )


# ---------------------------------------------------------------------------
# Submitting
# ---------------------------------------------------------------------------


async def test_a_service_that_does_not_exist_yet_can_still_be_typed(
    hass, enable_custom_integrations, install, options_flow, household
):
    """`custom_value`: a phone that has not registered yet is a legitimate output."""
    entry = await install(_installed_entry(hass))

    result = await options_flow(
        entry,
        "person",
        {"entity_id": "person.bob"},
        {
            "outputs": ["mobile_app_phone_one", "mobile_app_not_registered_yet"],
            "silence_entities": ["binary_sensor.phone_one_focus"],
        },
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    stored = next(
        row for row in entry.options["persons"] if row["entity_id"] == "person.bob"
    )
    assert stored["outputs"] == [
        "mobile_app_phone_one",
        "mobile_app_not_registered_yet",
    ]
    assert stored["silence_entities"] == ["binary_sensor.phone_one_focus"]
