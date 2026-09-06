"""Tests for the Notify Switchboard config and options flows."""

from __future__ import annotations

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.notify_switchboard.const import CONF_DEFAULT_TARGETS, DOMAIN


async def test_user_step_creates_entry(hass: HomeAssistant) -> None:
    """The user step takes no input and creates the single entry directly."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Notify Switchboard"
    assert result["data"] == {}


async def test_second_instance_is_aborted(hass: HomeAssistant) -> None:
    """Only one Notify Switchboard entry can exist."""
    first = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert first["type"] is FlowResultType.CREATE_ENTRY

    second = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    assert second["type"] is FlowResultType.ABORT
    assert second["reason"] == "single_instance_allowed"


async def test_options_flow_saves_default_targets(hass: HomeAssistant) -> None:
    """The options flow parses the comma-separated target list and saves it."""
    await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    await hass.async_block_till_done()
    entry = hass.config_entries.async_entries(DOMAIN)[0]

    options_result = await hass.config_entries.options.async_init(entry.entry_id)
    assert options_result["type"] is FlowResultType.FORM
    assert options_result["step_id"] == "init"

    updated = await hass.config_entries.options.async_configure(
        options_result["flow_id"],
        {
            CONF_DEFAULT_TARGETS: (
                "notify.mobile_app_amiel, notify.persistent_notification"
            )
        },
    )
    await hass.async_block_till_done()

    assert updated["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_DEFAULT_TARGETS] == [
        "notify.mobile_app_amiel",
        "notify.persistent_notification",
    ]
