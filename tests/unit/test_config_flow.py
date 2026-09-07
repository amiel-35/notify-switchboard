"""Tests for the Notify Switchboard config and options flows."""

from __future__ import annotations

from typing import Any

import pytest
import yaml
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType, InvalidData
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_mock_service,
)

from custom_components.notify_switchboard.const import (
    CONF_DEFAULT_TARGET,
    CONF_PERSONS,
    CONF_TARGETS,
    DOMAIN,
)


async def _create_entry(hass: HomeAssistant) -> MockConfigEntry:
    """Run the user step and return the created entry."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    return hass.config_entries.async_entries(DOMAIN)[0]


def _person_outputs_input(**overrides: Any) -> dict[str, Any]:
    """The second half of the person editor (ADR-0018 §2 splits it in two)."""
    data: dict[str, Any] = {
        "outputs": ["mobile_app_alice"],
        "silence_entities": [],
    }
    data.update(overrides)
    return data


def suggested_value(result: Any, key: str) -> Any:
    """Return what `add_suggested_values_to_schema` pre-filled one field with."""
    for marker in result["data_schema"].schema:
        if str(marker) == key:
            return (marker.description or {}).get("suggested_value")
    raise AssertionError(f"{key} is not a field of step {result.get('step_id')!r}")


# ADR-0020 §1 splits the target editor in two. The five fields that make a
# target route are the `target` step; the nine preferences are
# `target_advanced`, reached from the checkbox `target_saved` grew or from its
# own menu entry.
TARGET_BASIC = ("slug", "name", "alert_entity", "audience", "observer_mode")


def _target_input(**overrides: Any) -> dict[str, Any]:
    """The five fields of the `target` step."""
    data = {
        "slug": "leak",
        "name": "Fuite d'eau",
        "audience": ["person.alice"],
        "observer_mode": False,
    }
    data.update(overrides)
    return data


def _target_advanced_input(**overrides: Any) -> dict[str, Any]:
    """The nine fields of the `target_advanced` step."""
    data: dict[str, Any] = {
        "default_priority": "normal",
        "presence_rule": "always",
        "allow_acknowledge": False,
        "snooze_minutes": "15, 60",
        "default_data": {"channel": "family"},
    }
    data.update(overrides)
    return data


async def test_user_step_creates_an_empty_table(hass: HomeAssistant) -> None:
    """Setup takes no input and starts with an empty routing table."""
    entry = await _create_entry(hass)
    assert entry.title == "Notify Switchboard"
    assert entry.version == 1
    assert entry.minor_version == 1
    assert entry.options == {
        CONF_PERSONS: [],
        CONF_TARGETS: [],
        CONF_DEFAULT_TARGET: None,
    }


async def test_second_instance_is_aborted(hass: HomeAssistant) -> None:
    """Only one Notify Switchboard entry can exist."""
    await _create_entry(hass)
    second = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert second["type"] is FlowResultType.ABORT
    assert second["reason"] == "single_instance_allowed"


async def test_options_menu_lists_every_step(hass: HomeAssistant) -> None:
    """The options entry point is a menu, not a form."""
    entry = await _create_entry(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.MENU
    assert set(result["menu_options"]) == {
        "person",
        "edit_person",
        # v0.6 (ADR-0020 §1 and §2): a labelled menu entry is a step id, so
        # each advanced editor needs a picker of its own.
        "edit_person_advanced",
        "remove_person",
        "target",
        "edit_target",
        "edit_target_advanced",
        "remove_target",
        "general",
        # v0.5 (ADR-0019 §1): the household's time-to-live policy.
        "ttl",
        # v0.4 (ADR-0018 §6): send one real message and read what happened.
        "test_person",
        "test_target",
    }


async def _options_step(
    hass: HomeAssistant, entry: MockConfigEntry, step: str, *inputs: Any
) -> Any:
    """Open the options menu, pick `step`, and optionally submit `user_input`.

    A submission that creates the entry updates `entry.options`, which fires the
    update listener, which reloads the entry
    (`__init__._async_update_options`). That reload is a task, so it is drained
    here before returning: a test that ends with one still in flight leaves the
    entry out of `ConfigEntryState.LOADED` at the moment
    `pytest-homeassistant-custom-component`'s `hass` fixture unloads what it
    finds loaded, and the `Switchboard` set up a moment later -- on a
    Home Assistant that has already stopped -- arms its midnight counter reset
    with nobody left to cancel it ("Lingering timer after test ...
    Switchboard._async_reset_counters", roughly two runs in ten under load).
    """
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": step}
    )
    for user_input in inputs:
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], user_input
        )
    await hass.async_block_till_done()
    return result


PERSON_ADVANCED = ("wake_time", "summary")


async def _add_person(
    hass: HomeAssistant, entry: MockConfigEntry, person: str = "person.alice", **kw: Any
) -> Any:
    """Drive the person editor to the end, advanced step included when asked.

    ADR-0020 §2 moved `wake_time` and `summary` to `person_advanced`, which has
    no shortcut from `person_outputs` on purpose: the one form a first install
    fills stays at two fields. A caller that names either one therefore walks
    the picker afterwards, exactly as somebody would in the UI.
    """
    advanced = {key: kw.pop(key) for key in PERSON_ADVANCED if key in kw}
    result = await _options_step(
        hass, entry, "person", {"entity_id": person}, _person_outputs_input(**kw)
    )
    if not advanced or result["type"] is not FlowResultType.CREATE_ENTRY:
        return result
    return await _options_step(
        hass,
        entry,
        "edit_person_advanced",
        {"entity_id": person},
        advanced,
    )


async def _add_target(
    hass: HomeAssistant, entry: MockConfigEntry, **overrides: Any
) -> Any:
    """Drive the whole target editor: five fields, snippet, then the nine.

    Both halves every time, through the `advanced` checkbox of `target_saved`
    (ADR-0020 §1), so a helper called with `snooze_minutes=` or `message=`
    keeps meaning what it meant in 0.5.
    """
    basic = {key: value for key, value in overrides.items() if key in TARGET_BASIC}
    advanced = {
        key: value for key, value in overrides.items() if key not in TARGET_BASIC
    }
    return await _options_step(
        hass,
        entry,
        "target",
        _target_input(**basic),
        {"advanced": True},
        _target_advanced_input(**advanced),
    )


async def test_adding_a_person_bootstraps_the_managed_default_row(
    hass: HomeAssistant,
) -> None:
    """ADR-0018 §4: the first person on an empty table gets a row for free."""
    entry = await _create_entry(hass)

    result = await _add_person(hass, entry)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()

    assert entry.options[CONF_PERSONS][0]["entity_id"] == "person.alice"
    row = entry.options[CONF_TARGETS][0]
    assert row["slug"] == "default"
    assert row["managed"] is True
    assert row["audience"] == ["person.alice"]
    assert entry.options[CONF_DEFAULT_TARGET] == "default"


async def test_adding_a_target_next_to_the_managed_row(hass: HomeAssistant) -> None:
    """A hand-written row joins the table; the default target does not move."""
    entry = await _create_entry(hass)
    await _add_person(hass, entry)

    result = await _add_target(hass, entry)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()

    rows = {row["slug"]: row for row in entry.options[CONF_TARGETS]}
    assert set(rows) == {"default", "leak"}
    assert rows["leak"]["snooze_minutes"] == [15, 60]
    assert rows["leak"]["default_data"] == {"channel": "family"}
    assert "managed" not in rows["leak"]
    assert entry.options[CONF_DEFAULT_TARGET] == "default"


async def test_the_managed_row_is_not_recreated_once_it_is_gone(
    hass: HomeAssistant,
) -> None:
    """The row bootstraps an empty table; it never re-adds itself later."""
    entry = await _create_entry(hass)
    await _add_person(hass, entry)
    await _add_target(hass, entry)
    await _options_step(hass, entry, "remove_target", {"slug": "default"})
    await hass.async_block_till_done()
    assert [row["slug"] for row in entry.options[CONF_TARGETS]] == ["leak"]

    await _add_person(hass, entry, "person.bob", outputs=["mobile_app_bob"])
    await hass.async_block_till_done()

    assert [row["slug"] for row in entry.options[CONF_TARGETS]] == ["leak"]


async def test_recursive_output_is_rejected_by_the_flow(hass: HomeAssistant) -> None:
    """Contract "Output": recursion is refused at config time."""
    entry = await _create_entry(hass)
    result = await _options_step(
        hass,
        entry,
        "person",
        {"entity_id": "person.alice"},
        _person_outputs_input(outputs=["switchboard_leak"]),
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "person_outputs"
    assert result["errors"] == {"outputs": "recursive_output"}


async def test_a_person_with_no_output_is_refused_by_the_second_step(
    hass: HomeAssistant,
) -> None:
    """The rule lives in `validate_person` and is reported on the right form."""
    entry = await _create_entry(hass)
    result = await _options_step(
        hass,
        entry,
        "person",
        {"entity_id": "person.alice"},
        _person_outputs_input(outputs=[]),
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"outputs": "no_outputs"}
    assert entry.options[CONF_PERSONS] == []


async def test_resubmitting_a_slug_updates_the_row(hass: HomeAssistant) -> None:
    """The target step is keyed by slug: re-submitting one edits it in place.

    Uniqueness is therefore structural here; `validate_target`'s
    `duplicate_slug` rule guards any other caller.
    """
    entry = await _create_entry(hass)
    await _add_person(hass, entry)
    await _add_target(hass, entry)

    result = await _add_target(hass, entry, name="Another leak")
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    rows = [row for row in entry.options[CONF_TARGETS] if row["slug"] == "leak"]
    assert len(rows) == 1
    assert rows[0]["name"] == "Another leak"


async def test_invalid_slug_is_rejected_by_the_flow(hass: HomeAssistant) -> None:
    """A slug has to be a slug (accents and spaces included)."""
    entry = await _create_entry(hass)
    await _add_person(hass, entry)
    result = await _options_step(
        hass, entry, "target", _target_input(slug="Fuite d'eau")
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"slug": "invalid_slug"}


async def test_target_without_an_audience_is_rejected(hass: HomeAssistant) -> None:
    """A row nobody listens to is refused.

    The audience selector only offers people already in the table, so an
    unknown person cannot even be submitted; `validate_target`'s
    `unknown_person` rule guards a hand-edited options file.
    """
    entry = await _create_entry(hass)
    result = await _options_step(hass, entry, "target", _target_input(audience=[]))
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"audience": "empty_audience"}


async def test_removing_a_person_cleans_every_audience(hass: HomeAssistant) -> None:
    """Removing somebody also removes them from the rows that named them."""
    entry = await _create_entry(hass)
    await _add_person(hass, entry)
    await _add_target(hass, entry)

    result = await _options_step(
        hass, entry, "remove_person", {"entity_id": "person.alice"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert entry.options[CONF_PERSONS] == []
    for row in entry.options[CONF_TARGETS]:
        assert row["audience"] == []


async def test_removing_the_last_target_clears_the_default(
    hass: HomeAssistant,
) -> None:
    """The default target follows the table."""
    entry = await _create_entry(hass)
    await _add_person(hass, entry)

    result = await _options_step(hass, entry, "remove_target", {"slug": "default"})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert entry.options[CONF_TARGETS] == []
    assert entry.options[CONF_DEFAULT_TARGET] is None


async def test_remove_steps_abort_on_an_empty_table(hass: HomeAssistant) -> None:
    """There is nothing to remove, and nothing to configure, at first."""
    entry = await _create_entry(hass)
    for step in ("remove_person", "remove_target"):
        result = await _options_step(hass, entry, step)
        assert result["type"] is FlowResultType.ABORT
        assert result["reason"] == "nothing_to_remove"

    result = await _options_step(hass, entry, "general")
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "nothing_to_configure"


async def test_general_step_picks_the_default_target(hass: HomeAssistant) -> None:
    """With two rows, the default target becomes a choice."""
    entry = await _create_entry(hass)
    await _add_person(hass, entry)
    await _add_target(hass, entry)
    assert entry.options[CONF_DEFAULT_TARGET] == "default"

    result = await _options_step(hass, entry, "general", {"default_target": "leak"})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert entry.options[CONF_DEFAULT_TARGET] == "leak"


async def test_editing_an_existing_person_replaces_the_row(
    hass: HomeAssistant,
) -> None:
    """Submitting the same person again updates rather than duplicates."""
    entry = await _create_entry(hass)
    await _add_person(hass, entry)
    await _add_person(
        hass, entry, outputs=["mobile_app_alice", "persistent_notification"]
    )
    await hass.async_block_till_done()
    assert len(entry.options[CONF_PERSONS]) == 1
    assert entry.options[CONF_PERSONS][0]["outputs"] == [
        "mobile_app_alice",
        "persistent_notification",
    ]


async def test_target_step_stores_the_three_optional_row_texts(
    hass: HomeAssistant,
) -> None:
    """v0.2 addendum (ADR-0016): message, done_message and default_title."""
    entry = await _create_entry(hass)
    await _add_person(hass, entry)

    result = await _add_target(
        hass,
        entry,
        message="Level {{ alert.attributes.level }}",
        done_message="All clear",
        default_title="Switchboard",
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()

    row = next(row for row in entry.options[CONF_TARGETS] if row["slug"] == "leak")
    assert row["message"] == "Level {{ alert.attributes.level }}"
    assert row["done_message"] == "All clear"
    assert row["default_title"] == "Switchboard"


async def test_target_step_leaves_the_optional_texts_none_when_omitted(
    hass: HomeAssistant,
) -> None:
    """A Sprint 1 submission keeps producing a Sprint 1 row."""
    entry = await _create_entry(hass)
    await _add_person(hass, entry)
    await _add_target(hass, entry)
    await hass.async_block_till_done()

    row = next(row for row in entry.options[CONF_TARGETS] if row["slug"] == "leak")
    assert row["message"] is None
    assert row["done_message"] is None
    assert row["default_title"] is None


async def test_an_unparsable_row_template_is_rejected_by_the_schema(
    hass: HomeAssistant,
) -> None:
    """`TemplateSelector` runs `cv.template`, so the schema refuses bad Jinja.

    No rule of our own is needed in `validation.py`: the selector compiles the
    template (`homeassistant/helpers/selector.py`, `TemplateSelector.__call__`)
    and the flow raises `InvalidData` before the row is ever built.
    """
    entry = await _create_entry(hass)
    await _add_person(hass, entry)
    await _add_target(hass, entry)

    for field, bad in (("message", "{{ unclosed "), ("done_message", "{% if %}")):
        with pytest.raises(InvalidData) as err:
            await _options_step(
                hass,
                entry,
                "edit_target_advanced",
                {"slug": "leak"},
                _target_advanced_input(**{field: bad}),
            )
        assert field in str(err.value)

    row = next(r for r in entry.options[CONF_TARGETS] if r["slug"] == "leak")
    assert row["message"] is None


# ---------------------------------------------------------------------------
# M9: editing a row opens it pre-filled
# ---------------------------------------------------------------------------


def _suggested(schema: Any) -> dict[str, Any]:
    """Return {field: suggested_value} for every marker that carries one."""
    return {
        str(marker): marker.description["suggested_value"]
        for marker in schema.schema
        if isinstance(marker.description, dict)
        and "suggested_value" in marker.description
    }


async def test_editing_a_target_pre_fills_every_field_it_is_about_to_overwrite(
    hass: HomeAssistant,
) -> None:
    """The form writes the whole row, so it must open on the whole stored row.

    Without the suggested values, opening the target form to change one word of
    `message` reset `done_message`, `default_title`, `snooze_minutes`,
    `default_data` and the rest to their schema defaults the moment it was
    submitted.
    """
    entry = await _create_entry(hass)
    await _add_person(hass, entry)
    await _add_target(
        hass,
        entry,
        message="Level {{ alert.attributes.level }}",
        done_message="All clear",
        default_title="Switchboard",
        allow_acknowledge=True,
    )

    result = await _options_step(hass, entry, "edit_target", {"slug": "leak"})
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "target"

    suggested = _suggested(result["data_schema"])
    assert suggested["slug"] == "leak"
    assert suggested["name"] == "Fuite d'eau"
    assert suggested["audience"] == ["person.alice"]

    result = await _options_step(hass, entry, "edit_target_advanced", {"slug": "leak"})
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "target_advanced"

    suggested = _suggested(result["data_schema"])
    assert suggested["allow_acknowledge"] is True
    assert suggested["default_data"] == {"channel": "family"}
    # Stored as a list of ints, edited as the text `parse_snooze_minutes` reads.
    assert suggested["snooze_minutes"] == "15, 60"
    # The three v0.2 texts, which is what the review was about.
    assert suggested["message"] == "Level {{ alert.attributes.level }}"
    assert suggested["done_message"] == "All clear"
    assert suggested["default_title"] == "Switchboard"


async def test_editing_a_person_pre_fills_their_row(hass: HomeAssistant) -> None:
    entry = await _create_entry(hass)
    await _add_person(
        hass, entry, silence_entities=["input_boolean.night"], wake_time="07:00:00"
    )

    result = await _options_step(
        hass, entry, "edit_person", {"entity_id": "person.alice"}
    )
    assert result["step_id"] == "person_outputs"

    suggested = _suggested(result["data_schema"])
    assert suggested["outputs"] == ["mobile_app_alice"]
    assert suggested["silence_entities"] == ["input_boolean.night"]

    result = await _options_step(
        hass, entry, "edit_person_advanced", {"entity_id": "person.alice"}
    )
    assert result["step_id"] == "person_advanced"
    assert _suggested(result["data_schema"])["wake_time"] == "07:00:00"


async def test_a_validation_error_gives_back_what_was_typed(
    hass: HomeAssistant,
) -> None:
    """A rejected form must not also lose the fields that were fine."""
    entry = await _create_entry(hass)
    await _add_person(hass, entry)

    result = await _options_step(
        hass, entry, "target", _target_input(slug="Not A Slug", name="Kept")
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"slug": "invalid_slug"}

    suggested = _suggested(result["data_schema"])
    assert suggested["slug"] == "Not A Slug"
    assert suggested["name"] == "Kept"
    assert suggested["audience"] == ["person.alice"]

    # And the same on the other half of the editor (ADR-0020 §1).
    await _add_target(hass, entry)
    result = await _options_step(
        hass,
        entry,
        "edit_target_advanced",
        {"slug": "leak"},
        _target_advanced_input(snooze_minutes="every hour"),
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"snooze_minutes": "invalid_snooze_minutes"}
    assert _suggested(result["data_schema"])["snooze_minutes"] == "every hour"


async def test_editing_is_refused_while_the_table_is_empty(
    hass: HomeAssistant,
) -> None:
    entry = await _create_entry(hass)

    for step in ("edit_person", "edit_target"):
        result = await _options_step(hass, entry, step)
        assert result["type"] is FlowResultType.ABORT
        assert result["reason"] == "nothing_to_edit"


# ---------------------------------------------------------------------------
# v0.4 (ADR-0018): discovery corner cases and the test steps
# ---------------------------------------------------------------------------


async def test_test_steps_abort_when_there_is_nothing_to_test(
    hass: HomeAssistant,
) -> None:
    """An empty table has no row to route through and nobody to route to."""
    entry = await _create_entry(hass)

    for step in ("test_person", "test_target"):
        result = await _options_step(hass, entry, step)
        assert result["type"] is FlowResultType.ABORT
        assert result["reason"] == "nothing_to_test"


async def test_submitting_the_test_result_returns_to_the_menu(
    hass: HomeAssistant,
) -> None:
    """Reading the result is the end of it; nothing is written by a test."""
    async_mock_service(hass, "notify", "mobile_app_alice")
    hass.states.async_set("person.alice", "home")
    entry = await _create_entry(hass)
    await _add_person(hass, entry)
    before = dict(entry.options)

    result = await _options_step(hass, entry, "test_target", {"slug": "default"}, {})

    assert result["type"] is FlowResultType.MENU
    assert dict(entry.options) == before


async def test_discovery_ignores_what_is_not_a_phone_with_a_focus_sensor(
    hass: HomeAssistant, entity_registry: er.EntityRegistry
) -> None:
    """A registration with no device name, and a sensor that is not binary.

    Both are shapes a real instance produces -- an old registration, a
    Companion sensor of another platform -- and neither must end up pre-selected
    (ADR-0018 §2 and §3).
    """
    hass.states.async_set("person.alice", "home", {"user_id": "user-1"})
    registration = MockConfigEntry(
        domain="mobile_app",
        source="registration",
        title="Nameless",
        data={"user_id": "user-1", "device_id": "device-nameless"},
    )
    registration.add_to_hass(hass)
    entity_registry.async_get_or_create(
        "sensor",
        "mobile_app",
        "device-nameless-focus",
        config_entry=registration,
        suggested_object_id="nameless_focus",
    )
    entry = await _create_entry(hass)

    result = await _options_step(hass, entry, "person", {"entity_id": "person.alice"})

    assert result["step_id"] == "person_outputs"
    suggested = _suggested(result["data_schema"])
    assert suggested["outputs"] == [], (
        "a registration with no device_name names no notify service"
    )
    assert suggested["silence_entities"] == [], (
        "only binary_sensor entities can mean `on` == silent"
    )


async def test_the_alert_snippet_quotes_a_name_yaml_would_misread(
    hass: HomeAssistant,
) -> None:
    """A row name is free text, so the snippet must stay parseable YAML.

    `Fuite: eau # urgence` is the worst realistic case in one string: a colon
    followed by a space turns the scalar into a nested mapping, and an
    unquoted `#` truncates the value at the comment. Emitted raw, the block
    Home Assistant is told to paste into `configuration.yaml` either fails to
    load or silently loses half the name.
    """
    async_mock_service(hass, "notify", "mobile_app_alice")
    entry = await _create_entry(hass)
    await _add_person(hass, entry)

    result = await _options_step(
        hass, entry, "target", _target_input(name="Fuite: eau # urgence")
    )

    assert result["step_id"] == "target_saved"
    snippet = (result["description_placeholders"] or {})["snippet"]
    parsed = yaml.safe_load(snippet)
    assert parsed["alert"]["leak"]["name"] == "Fuite: eau # urgence", (
        f"the snippet must round-trip the row name through YAML; got {snippet!r}"
    )


async def test_the_test_result_is_rendered_as_a_markdown_list(
    hass: HomeAssistant,
) -> None:
    """`{result}` lands in a markdown description, so one person is one bullet.

    Bare newlines are collapsed by the markdown renderer of the frontend, which
    would run every person's answer into a single paragraph.
    """
    async_mock_service(hass, "notify", "mobile_app_alice")
    async_mock_service(hass, "notify", "mobile_app_bob")
    hass.states.async_set("person.alice", "home")
    hass.states.async_set("person.bob", "home")
    entry = await _create_entry(hass)
    await _add_person(hass, entry)
    await _add_person(hass, entry, "person.bob", outputs=["mobile_app_bob"])

    result = await _options_step(hass, entry, "test_target", {"slug": "default"})

    assert result["step_id"] == "test_result"
    text = (result["description_placeholders"] or {})["result"]
    lines = text.splitlines()
    assert len(lines) == 2, f"one bullet per person, got {text!r}"
    assert all(line.startswith("- ") for line in lines), (
        f"every line must be a markdown list item; got {text!r}"
    )
    assert "person.alice" in text and "person.bob" in text


# ---------------------------------------------------------------------------
# v0.5: the three optional options keys (ADR-0019)
# ---------------------------------------------------------------------------


async def test_the_ttl_step_writes_the_mapping_only_when_it_differs(
    hass: HomeAssistant,
) -> None:
    """A household that never changes the policy keeps its three-key options."""
    entry = await _create_entry(hass)
    await _add_person(hass, entry)

    # The form opens on the *effective* policy, defaults included; `high` has
    # no value at all, because it never expires.
    result = await _options_step(hass, entry, "ttl")
    assert result["step_id"] == "ttl"
    assert suggested_value(result, "info") == 120
    assert suggested_value(result, "normal") == 720
    assert suggested_value(result, "high") is None

    # Submitting the defaults back writes nothing.
    result = await _options_step(
        hass, entry, "ttl", {"info": 120, "normal": 720, "high": None}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert "ttl_minutes" not in entry.options

    # A real change is written whole; an empty field means "never expires".
    result = await _options_step(hass, entry, "ttl", {"info": 30})
    await hass.async_block_till_done()
    assert entry.options["ttl_minutes"] == {"info": 30, "normal": None, "high": None}

    # ...and the form now opens on what was stored.
    result = await _options_step(hass, entry, "ttl")
    assert suggested_value(result, "info") == 30
    assert suggested_value(result, "normal") is None


async def test_editing_a_person_carries_the_ttl_policy_through(
    hass: HomeAssistant,
) -> None:
    """The options flow's working copy is built key by key, so it can lose one.

    `_load` rebuilds `self._options` from four named keys rather than copying
    the stored dict, which is what keeps a hand-edited file from smuggling a
    shape the rest of the flow does not expect. `ttl_minutes` is optional and
    new in v0.5, so it has to be named there explicitly: without it, editing a
    person -- a step that has nothing to do with the night -- would write the
    whole options back without the household's expiry policy.
    """
    entry = await _create_entry(hass)
    await _add_person(hass, entry)
    await _options_step(hass, entry, "ttl", {"info": 30})
    await hass.async_block_till_done()
    assert entry.options["ttl_minutes"] == {"info": 30, "normal": None, "high": None}

    await _add_person(
        hass, entry, outputs=["mobile_app_alice", "persistent_notification"]
    )
    await hass.async_block_till_done()

    assert entry.options[CONF_PERSONS][0]["outputs"] == [
        "mobile_app_alice",
        "persistent_notification",
    ], "the edit itself landed"
    assert entry.options["ttl_minutes"] == {"info": 30, "normal": None, "high": None}


async def test_summary_and_clear_done_are_written_only_when_they_differ(
    hass: HomeAssistant,
) -> None:
    """Absent means on for `summary` and off for `clear_done` (ADR-0019)."""
    entry = await _create_entry(hass)
    await _add_person(hass, entry)
    await _add_target(hass, entry)

    person = entry.options[CONF_PERSONS][0]
    row = next(r for r in entry.options[CONF_TARGETS] if r["slug"] == "leak")
    assert "summary" not in person
    assert "clear_done" not in row

    await _add_person(hass, entry, summary=False)
    await _add_target(hass, entry, clear_done=True)

    person = entry.options[CONF_PERSONS][0]
    row = next(r for r in entry.options[CONF_TARGETS] if r["slug"] == "leak")
    assert person["summary"] is False
    assert row["clear_done"] is True


# ---------------------------------------------------------------------------
# v0.6 (ADR-0020 §1 and §2): the two editors, split in two steps each
# ---------------------------------------------------------------------------


async def test_the_advanced_pickers_abort_on_an_empty_table(
    hass: HomeAssistant,
) -> None:
    """Nothing to open advanced settings on, and the menu says so."""
    entry = await _create_entry(hass)

    for step in ("edit_person_advanced", "edit_target_advanced"):
        result = await _options_step(hass, entry, step)
        assert result["type"] is FlowResultType.ABORT
        assert result["reason"] == "nothing_to_edit"


async def test_target_saved_unticked_writes_the_target_and_ends(
    hass: HomeAssistant,
) -> None:
    """The five-field path: a target that routes, without a second form.

    Submitting `{}` -- what every Sprint 4 test does, and what the frontend
    sends for an unticked box -- has to keep writing the target and ending.
    """
    entry = await _create_entry(hass)
    await _add_person(hass, entry)

    result = await _options_step(hass, entry, "target", _target_input(), {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()

    row = next(r for r in entry.options[CONF_TARGETS] if r["slug"] == "leak")
    assert row["default_priority"] == "normal"
    assert row["presence_rule"] == "always"
    assert row["allow_acknowledge"] is False
    assert row["snooze_minutes"] == []
    assert row["default_data"] == {}
    assert "clear_done" not in row


async def test_the_basic_step_keeps_the_advanced_values_of_the_target_it_edits(
    hass: HomeAssistant,
) -> None:
    """Renaming a target must not reset the nine fields it does not show."""
    entry = await _create_entry(hass)
    await _add_person(hass, entry)
    await _add_target(hass, entry, allow_acknowledge=True, default_title="Switchboard")

    result = await _options_step(
        hass, entry, "edit_target", {"slug": "leak"}, _target_input(name="Renamed"), {}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()

    row = next(r for r in entry.options[CONF_TARGETS] if r["slug"] == "leak")
    assert row["name"] == "Renamed"
    assert row["allow_acknowledge"] is True
    assert row["default_title"] == "Switchboard"
    assert row["snooze_minutes"] == [15, 60]


async def test_either_half_of_the_target_editor_clears_managed(
    hass: HomeAssistant,
) -> None:
    """Submitting either form is the user taking the default target over.

    ADR-0018 §4 made `managed` mean "this audience follows the people"; a split
    editor must not leave a half of itself that keeps the flag alive.
    """
    entry = await _create_entry(hass)
    await _add_person(hass, entry)
    assert entry.options[CONF_TARGETS][0]["managed"] is True

    result = await _options_step(
        hass,
        entry,
        "edit_target_advanced",
        {"slug": "default"},
        _target_advanced_input(default_priority="high"),
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()

    row = entry.options[CONF_TARGETS][0]
    assert "managed" not in row
    assert row["default_priority"] == "high"
    assert row["audience"] == ["person.alice"]


async def test_person_advanced_writes_only_the_wake_time_and_the_summary(
    hass: HomeAssistant,
) -> None:
    """The other half of ADR-0020 §2, from the side that could lose outputs."""
    entry = await _create_entry(hass)
    await _add_person(
        hass, entry, outputs=["mobile_app_alice"], silence_entities=["schedule.night"]
    )

    result = await _options_step(
        hass,
        entry,
        "edit_person_advanced",
        {"entity_id": "person.alice"},
        {"wake_time": "07:00:00", "summary": False},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()

    person = entry.options[CONF_PERSONS][0]
    assert person["wake_time"] == "07:00:00"
    assert person["summary"] is False
    assert person["outputs"] == ["mobile_app_alice"]
    assert person["silence_entities"] == ["schedule.night"]


async def test_clearing_the_wake_time_is_a_supported_answer(
    hass: HomeAssistant,
) -> None:
    """ADR-0020 §3 gives an absent wake time a meaning, so it must be settable."""
    entry = await _create_entry(hass)
    await _add_person(hass, entry, wake_time="07:00:00")
    assert entry.options[CONF_PERSONS][0]["wake_time"] == "07:00:00"

    result = await _options_step(
        hass, entry, "edit_person_advanced", {"entity_id": "person.alice"}, {}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()

    person = entry.options[CONF_PERSONS][0]
    assert person["wake_time"] is None
    assert "summary" not in person
