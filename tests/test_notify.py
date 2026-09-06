"""Tests for the Notify Switchboard notify platform (pass-through)."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_mock_service,
)

from custom_components.notify_switchboard.const import CONF_DEFAULT_TARGETS, DOMAIN


async def test_setup_registers_legacy_service(hass: HomeAssistant) -> None:
    """Setting up the entry registers the legacy notify.switchboard service."""
    entry = MockConfigEntry(domain=DOMAIN, options={CONF_DEFAULT_TARGETS: []})
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert hass.services.has_service("notify", "switchboard")


async def test_setup_registers_notify_entity(hass: HomeAssistant) -> None:
    """Setting up the entry also registers a NotifyEntity."""
    entry = MockConfigEntry(domain=DOMAIN, options={CONF_DEFAULT_TARGETS: []})
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert hass.states.async_entity_ids("notify")


async def test_send_message_forwards_to_default_target(hass: HomeAssistant) -> None:
    """notify.switchboard forwards message/title/data to every default target."""
    calls = async_mock_service(hass, "notify", "test")

    entry = MockConfigEntry(
        domain=DOMAIN, options={CONF_DEFAULT_TARGETS: ["notify.test"]}
    )
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    await hass.services.async_call(
        "notify",
        "switchboard",
        {
            "message": "Leak detected",
            "title": "Water",
            "data": {"class": "building"},
        },
        blocking=True,
    )
    await hass.async_block_till_done()

    assert len(calls) == 1
    assert calls[0].data == {
        "message": "Leak detected",
        "title": "Water",
        "data": {"class": "building"},
    }
