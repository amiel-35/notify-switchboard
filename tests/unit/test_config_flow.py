"""Tests for the Notify Switchboard config and options flows."""

from __future__ import annotations

from typing import Any

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
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
        "remove_person",
        "target",
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
