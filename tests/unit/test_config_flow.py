"""Tests for the Notify Switchboard config and options flows."""

from __future__ import annotations

from typing import Any

import pytest
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType, InvalidData
from pytest_homeassistant_custom_component.common import MockConfigEntry

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


def _person_input(**overrides: Any) -> dict[str, Any]:
    data = {
        "entity_id": "person.alice",
        "outputs": ["mobile_app_alice"],
        "silence_entities": [],
    }
    data.update(overrides)
    return data


def _target_input(**overrides: Any) -> dict[str, Any]:
    data = {
        "slug": "leak",
        "name": "Fuite d'eau",
        "class": "building",
        "default_priority": "normal",
        "audience": ["person.alice"],
        "presence_rule": "always",
        "allow_acknowledge": False,
        "snooze_minutes": "15, 60",
        "default_data": {"channel": "family"},
        "observer_mode": False,
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
        "remove_person",
        "target",
        "edit_target",
        "remove_target",
        "general",
    }


async def _options_step(
    hass: HomeAssistant, entry: MockConfigEntry, step: str, user_input: Any = None
) -> Any:
    """Open the options menu, pick `step`, and optionally submit `user_input`."""
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": step}
    )
    if user_input is None:
        return result
    return await hass.config_entries.options.async_configure(
        result["flow_id"], user_input
    )


async def test_adding_a_person_then_a_target(hass: HomeAssistant) -> None:
    """A person and a target can be added, and the default target is derived."""
    entry = await _create_entry(hass)

    result = await _options_step(hass, entry, "person", _person_input())
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert entry.options[CONF_PERSONS][0]["entity_id"] == "person.alice"

    result = await _options_step(hass, entry, "target", _target_input())
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    row = entry.options[CONF_TARGETS][0]
    assert row["slug"] == "leak"
    assert row["snooze_minutes"] == [15, 60]
    assert row["default_data"] == {"channel": "family"}
    assert entry.options[CONF_DEFAULT_TARGET] == "leak"


async def test_recursive_output_is_rejected_by_the_flow(hass: HomeAssistant) -> None:
    """Contract "Output": recursion is refused at config time."""
    entry = await _create_entry(hass)
    result = await _options_step(
        hass, entry, "person", _person_input(outputs=["switchboard_leak"])
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"outputs": "recursive_output"}


async def test_resubmitting_a_slug_updates_the_row(hass: HomeAssistant) -> None:
    """The target step is keyed by slug: re-submitting one edits it in place.

    Uniqueness is therefore structural here; `validate_target`'s
    `duplicate_slug` rule guards any other caller.
    """
    entry = await _create_entry(hass)
    await _options_step(hass, entry, "person", _person_input())
    await _options_step(hass, entry, "target", _target_input())

    result = await _options_step(
        hass, entry, "target", _target_input(name="Another leak")
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert len(entry.options[CONF_TARGETS]) == 1
    assert entry.options[CONF_TARGETS][0]["name"] == "Another leak"


async def test_invalid_slug_is_rejected_by_the_flow(hass: HomeAssistant) -> None:
    """A slug has to be a slug (accents and spaces included)."""
    entry = await _create_entry(hass)
    await _options_step(hass, entry, "person", _person_input())
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
    await _options_step(hass, entry, "person", _person_input())
    await _options_step(hass, entry, "target", _target_input())

    result = await _options_step(
        hass, entry, "remove_person", {"entity_id": "person.alice"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert entry.options[CONF_PERSONS] == []
    assert entry.options[CONF_TARGETS][0]["audience"] == []


async def test_removing_the_last_target_clears_the_default(
    hass: HomeAssistant,
) -> None:
    """The default target follows the table."""
    entry = await _create_entry(hass)
    await _options_step(hass, entry, "person", _person_input())
    await _options_step(hass, entry, "target", _target_input())

    result = await _options_step(hass, entry, "remove_target", {"slug": "leak"})
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
    await _options_step(hass, entry, "person", _person_input())
    await _options_step(hass, entry, "target", _target_input())
    await _options_step(
        hass, entry, "target", _target_input(slug="garage", name="Garage")
    )
    assert entry.options[CONF_DEFAULT_TARGET] == "leak"

    result = await _options_step(hass, entry, "general", {"default_target": "garage"})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert entry.options[CONF_DEFAULT_TARGET] == "garage"


async def test_editing_an_existing_person_replaces_the_row(
    hass: HomeAssistant,
) -> None:
    """Submitting the same person again updates rather than duplicates."""
    entry = await _create_entry(hass)
    await _options_step(hass, entry, "person", _person_input())
    await _options_step(
        hass,
        entry,
        "person",
        _person_input(outputs=["mobile_app_alice", "persistent_notification"]),
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
    await _options_step(hass, entry, "person", _person_input())

    result = await _options_step(
        hass,
        entry,
        "target",
        _target_input(
            message="Level {{ alert.attributes.level }}",
            done_message="All clear",
            default_title="Switchboard",
        ),
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()

    row = entry.options[CONF_TARGETS][0]
    assert row["message"] == "Level {{ alert.attributes.level }}"
    assert row["done_message"] == "All clear"
    assert row["default_title"] == "Switchboard"


async def test_target_step_leaves_the_optional_texts_none_when_omitted(
    hass: HomeAssistant,
) -> None:
    """A Sprint 1 submission keeps producing a Sprint 1 row."""
    entry = await _create_entry(hass)
    await _options_step(hass, entry, "person", _person_input())
    await _options_step(hass, entry, "target", _target_input())
    await hass.async_block_till_done()

    row = entry.options[CONF_TARGETS][0]
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
    await _options_step(hass, entry, "person", _person_input())

    for field, bad in (("message", "{{ unclosed "), ("done_message", "{% if %}")):
        with pytest.raises(InvalidData) as err:
            await _options_step(hass, entry, "target", _target_input(**{field: bad}))
        assert field in str(err.value)

    assert entry.options[CONF_TARGETS] == []


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
    await _options_step(hass, entry, "person", _person_input())
    await _options_step(
        hass,
        entry,
        "target",
        _target_input(
            message="Level {{ alert.attributes.level }}",
            done_message="All clear",
            default_title="Switchboard",
            allow_acknowledge=True,
        ),
    )

    result = await _options_step(hass, entry, "edit_target", {"slug": "leak"})
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "target"

    suggested = _suggested(result["data_schema"])
    assert suggested["slug"] == "leak"
    assert suggested["name"] == "Fuite d'eau"
    assert suggested["class"] == "building"
    assert suggested["audience"] == ["person.alice"]
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
    await _options_step(
        hass,
        entry,
        "person",
        _person_input(silence_entities=["input_boolean.night"], wake_time="07:00:00"),
    )

    result = await _options_step(
        hass, entry, "edit_person", {"entity_id": "person.alice"}
    )
    assert result["step_id"] == "person"

    suggested = _suggested(result["data_schema"])
    assert suggested["entity_id"] == "person.alice"
    assert suggested["outputs"] == ["mobile_app_alice"]
    assert suggested["silence_entities"] == ["input_boolean.night"]
    assert suggested["wake_time"] == "07:00:00"


async def test_a_validation_error_gives_back_what_was_typed(
    hass: HomeAssistant,
) -> None:
    """A rejected form must not also lose the eleven fields that were fine."""
    entry = await _create_entry(hass)
    await _options_step(hass, entry, "person", _person_input())

    result = await _options_step(
        hass, entry, "target", _target_input(slug="Not A Slug", name="Kept")
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"slug": "invalid_slug"}

    suggested = _suggested(result["data_schema"])
    assert suggested["slug"] == "Not A Slug"
    assert suggested["name"] == "Kept"
    assert suggested["snooze_minutes"] == "15, 60"


async def test_editing_is_refused_while_the_table_is_empty(
    hass: HomeAssistant,
) -> None:
    entry = await _create_entry(hass)

    for step in ("edit_person", "edit_target"):
        result = await _options_step(hass, entry, step)
        assert result["type"] is FlowResultType.ABORT
        assert result["reason"] == "nothing_to_edit"
