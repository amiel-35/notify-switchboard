"""The Notify Switchboard integration.

Notify Switchboard is a pure `notify` proxy: it never delivers a
notification itself, it only forwards to existing `notify.*` services. See
docs/ARCHITECTURE.md in the repository for the full contract.

This module wires a config entry to two independent notify surfaces defined
in notify.py:

- the legacy `notify.switchboard` service, loaded through the discovery
  helper so that `alert.notifiers:` can reference it by name;
- a modern `NotifyEntity`, set up as a regular entity platform.

Both surfaces share the same `Router` instance stored on
`entry.runtime_data`.
"""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_NAME, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import discovery

from .const import CONF_DEFAULT_TARGETS, DEFAULT_TARGETS, DOMAIN, LEGACY_SERVICE_NAME
from .router import Router

PLATFORMS: list[Platform] = [Platform.NOTIFY]


@dataclass(slots=True)
class SwitchboardRuntimeData:
    """Runtime data stored on the config entry."""

    router: Router


type SwitchboardConfigEntry = ConfigEntry[SwitchboardRuntimeData]


async def async_setup_entry(hass: HomeAssistant, entry: SwitchboardConfigEntry) -> bool:
    """Set up Notify Switchboard from a config entry."""
    default_targets: list[str] = list(
        entry.options.get(CONF_DEFAULT_TARGETS, DEFAULT_TARGETS)
    )
    entry.runtime_data = SwitchboardRuntimeData(router=Router(default_targets))

    entry.async_on_unload(entry.add_update_listener(_async_update_options))

    # Legacy `notify.switchboard` service, discovered like `mobile_app` does
    # for its own per-device services. `CONF_NAME` is what the legacy notify
    # platform slugifies into the service name (see notify.py:
    # async_get_service), giving us `notify.switchboard` rather than the
    # generic `notify.notify`.
    hass.async_create_task(
        discovery.async_load_platform(
            hass,
            Platform.NOTIFY,
            DOMAIN,
            {CONF_NAME: LEGACY_SERVICE_NAME, "entry_id": entry.entry_id},
            {},
        ),
        eager_start=True,
    )

    # Modern `NotifyEntity`.
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: SwitchboardConfigEntry
) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_update_options(
    hass: HomeAssistant, entry: SwitchboardConfigEntry
) -> None:
    """Reload the entry when options change."""
    await hass.config_entries.async_reload(entry.entry_id)
