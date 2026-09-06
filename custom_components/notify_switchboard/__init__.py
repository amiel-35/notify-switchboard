"""The Notify Switchboard integration.

Notify Switchboard is a pure `notify` proxy (ADR-002): it never delivers a
notification itself, it only forwards to `notify.*` services that already
exist. See `docs/ARCHITECTURE.md` and `docs/contract.md`.

A config entry wires three surfaces onto one `Switchboard`:

- the legacy `notify.switchboard` service and one `notify.switchboard_<slug>`
  per routing-table row -- the only shape `alert.notifiers:` can call
  (`homeassistant/components/notify/legacy.py`);
- a `NotifyEntity`, documented as degraded (message + title only);
- the diagnostic entities of contract §3.5.
"""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .dispatcher import Switchboard
from .legacy import SwitchboardNotificationService

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.EVENT,
    Platform.NOTIFY,
    Platform.SENSOR,
]


@dataclass(slots=True)
class SwitchboardRuntimeData:
    """Runtime data stored on the config entry."""

    switchboard: Switchboard
    legacy_service: SwitchboardNotificationService


type SwitchboardConfigEntry = ConfigEntry[SwitchboardRuntimeData]


async def async_setup_entry(hass: HomeAssistant, entry: SwitchboardConfigEntry) -> bool:
    """Set up Notify Switchboard from a config entry."""
    switchboard = Switchboard(hass, entry)
    await switchboard.async_setup()

    legacy_service = SwitchboardNotificationService(switchboard)
    entry.runtime_data = SwitchboardRuntimeData(
        switchboard=switchboard, legacy_service=legacy_service
    )

    # The entity platforms first: forwarding `Platform.NOTIFY` is what sets up
    # the `notify` integration, which the legacy service registration needs.
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    await legacy_service.async_register(hass)

    entry.async_on_unload(entry.add_update_listener(_async_update_options))
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: SwitchboardConfigEntry
) -> bool:
    """Unload a config entry."""
    runtime_data = entry.runtime_data
    await runtime_data.legacy_service.async_unregister()
    runtime_data.switchboard.async_shutdown()
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_migrate_entry(
    hass: HomeAssistant, entry: SwitchboardConfigEntry
) -> bool:
    """Migrate an old config entry.

    Sprint 1 introduces `version = 1` / `minor_version = 1`; there is no older
    schema to migrate from yet. A future schema bump adds its own branch here.
    """
    # Downgrades are not supported.
    return entry.version <= 1


async def _async_update_options(
    hass: HomeAssistant, entry: SwitchboardConfigEntry
) -> None:
    """Reload the entry when options change."""
    await hass.config_entries.async_reload(entry.entry_id)
