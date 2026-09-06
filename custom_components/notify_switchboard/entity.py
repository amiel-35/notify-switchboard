"""Shared entity plumbing for Notify Switchboard.

Contract §3.5 fixes the `unique_id` scheme (`<entry_id>:<person entity_id>:
<kind>`); `tests/acceptance/README.md` fixes the entity ids, which are derived
from the person's object_id. Both are set explicitly here rather than left to
the slugification of a display name.
"""

from __future__ import annotations

from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import Entity

from .const import DOMAIN, LEGACY_SERVICE_NAME, SIGNAL_STATE_UPDATED
from .dispatcher import Switchboard
from .router import PersonConfig

ROUTER_DEVICE_NAME = "Switchboard"


def router_device_info(entry_id: str) -> DeviceInfo:
    """Return the service device representing the router itself."""
    return DeviceInfo(
        identifiers={(DOMAIN, entry_id)},
        name=ROUTER_DEVICE_NAME,
        entry_type=DeviceEntryType.SERVICE,
        manufacturer="Notify Switchboard",
    )


def person_device_info(entry_id: str, person: PersonConfig) -> DeviceInfo:
    """Return the virtual device grouping one person's entities."""
    return DeviceInfo(
        identifiers={(DOMAIN, f"{entry_id}:{person.entity_id}")},
        name=person.object_id.replace("_", " ").title(),
        entry_type=DeviceEntryType.SERVICE,
        manufacturer="Notify Switchboard",
    )


class SwitchboardEntity(Entity):
    """Base entity: no polling, refreshed by the switchboard's signal."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, switchboard: Switchboard) -> None:
        """Store the switchboard this entity reports on."""
        self._switchboard = switchboard
        self._entry_id = switchboard.entry.entry_id

    async def async_added_to_hass(self) -> None:
        """Subscribe to the switchboard's state-updated signal."""
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                f"{SIGNAL_STATE_UPDATED}_{self._entry_id}",
                self._handle_update,
            )
        )

    @callback
    def _handle_update(self) -> None:
        """Write the new state after a routing decision."""
        self.async_write_ha_state()


class SwitchboardGlobalEntity(SwitchboardEntity):
    """A router-wide entity (`*.switchboard_*`)."""

    platform_domain = "sensor"

    def __init__(self, switchboard: Switchboard, kind: str, name: str | None) -> None:
        """Initialise a global entity of the given kind."""
        super().__init__(switchboard)
        self._attr_unique_id = f"{self._entry_id}:{kind}"
        self._attr_name = name
        self._attr_device_info = router_device_info(self._entry_id)
        self.entity_id = f"{self.platform_domain}.{LEGACY_SERVICE_NAME}_{kind}"


class SwitchboardPersonEntity(SwitchboardEntity):
    """A per-person entity (`*.<person object_id>_*`)."""

    platform_domain = "sensor"

    def __init__(
        self,
        switchboard: Switchboard,
        person: PersonConfig,
        kind: str,
        name: str | None,
    ) -> None:
        """Initialise a per-person entity of the given kind."""
        super().__init__(switchboard)
        self._person = person
        self._attr_unique_id = f"{self._entry_id}:{person.entity_id}:{kind}"
        self._attr_name = name
        self._attr_device_info = person_device_info(self._entry_id, person)
        self.entity_id = f"{self.platform_domain}.{person.object_id}_{kind}"
