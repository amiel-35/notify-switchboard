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
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import config_validation as cv, entity_registry as er
from homeassistant.helpers.typing import ConfigType

from .const import DOMAIN
from .dispatcher import Switchboard
from .legacy import SwitchboardNotificationService
from .services import async_register_services
from .store import SwitchboardStore

# There is nothing to configure in YAML: the routing table lives in the config
# entry's options. `config_entry_only_config_schema` says exactly that and is
# what lets `async_setup` exist purely to register the actions
# (`homeassistant/helpers/config_validation.py`).
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.EVENT,
    Platform.NOTIFY,
    Platform.SENSOR,
]

# `unique_id` schemes used by versions before 0.1.0, whose entities are now
# orphans. 0.0.1's `notify.py` gave the `NotifyEntity`
# `f"{entry.entry_id}_notify_entity"`; 0.1.0 gives it `f"{entry_id}:entity"`
# (see `entity.SwitchboardGlobalEntity`), so upgrading left an `unavailable`
# `notify.switchboard` behind and pushed the live entity to
# `notify.switchboard_2`.
LEGACY_UNIQUE_ID_SUFFIXES: tuple[str, ...] = ("_notify_entity",)


@dataclass(slots=True)
class SwitchboardRuntimeData:
    """Runtime data stored on the config entry."""

    switchboard: Switchboard
    legacy_service: SwitchboardNotificationService


type SwitchboardConfigEntry = ConfigEntry[SwitchboardRuntimeData]


@callback
def _async_drop_pre_0_1_0_entities(
    hass: HomeAssistant, entry: SwitchboardConfigEntry
) -> None:
    """Remove registry entries left behind by a pre-0.1.0 `unique_id` scheme.

    A `unique_id` the integration no longer produces can never be claimed
    again, so the entity stays in the registry as `unavailable` *and* keeps
    its entity id, forcing the new entity to `notify.switchboard_2`. Dropping
    the orphan frees `notify.switchboard` for the entity that actually works.
    """
    registry = er.async_get(hass)
    for entity in er.async_entries_for_config_entry(registry, entry.entry_id):
        if entity.unique_id.endswith(LEGACY_UNIQUE_ID_SUFFIXES):
            registry.async_remove(entity.entity_id)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the five `notify_switchboard.*` actions, once.

    Quality-scale rule `action-setup` (ADR-0017 §5): registering them here
    rather than in `async_setup_entry` means an automation that references one
    fails its own validation only when the action genuinely does not exist. A
    call made while no entry is loaded is refused by the handler itself, with a
    translated `ServiceValidationError`.
    """
    async_register_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: SwitchboardConfigEntry) -> bool:
    """Set up Notify Switchboard from a config entry."""
    _async_drop_pre_0_1_0_entities(hass, entry)

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
    # The five `notify_switchboard.*` actions stay registered: from v0.3 they
    # belong to the integration, not to the entry (ADR-0017 §5). What unloading
    # removes is their ability to act -- they look the loaded entry up at call
    # time, so none of them holds on to the `Switchboard` released below.
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


async def async_remove_entry(
    hass: HomeAssistant, entry: SwitchboardConfigEntry
) -> None:
    """Delete the persisted snoozes and deferrals when the entry is removed.

    Home Assistant calls this after the entry is gone
    (`homeassistant/config_entries.py`, `ConfigEntries.async_remove`). Without
    it, `.storage/notify_switchboard.data` would survive the integration and
    a fresh install would inherit somebody else's snoozes.
    """
    await SwitchboardStore(hass).async_remove()


async def _async_update_options(
    hass: HomeAssistant, entry: SwitchboardConfigEntry
) -> None:
    """Reload the entry when options change."""
    await hass.config_entries.async_reload(entry.entry_id)
