"""The `NotifyEntity` surface of Notify Switchboard.

Documented as degraded (doctrine §3.1): `notify.send_message` carries only
`message` and `title`, so a call through this entity is routed to the default
row with priority `normal`. The full contract lives on the legacy
`notify.switchboard[_<slug>]` services (see `legacy.py`).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.components.notify import NotifyEntity, NotifyEntityFeature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import LEGACY_SERVICE_NAME, PRIORITY_NORMAL
from .dispatcher import Switchboard
from .entity import SwitchboardGlobalEntity

if TYPE_CHECKING:
    from . import SwitchboardConfigEntry


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SwitchboardConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the degraded notify entity."""
    async_add_entities([SwitchboardNotifyEntity(entry.runtime_data.switchboard)])


class SwitchboardNotifyEntity(SwitchboardGlobalEntity, NotifyEntity):
    """`notify.switchboard` entity: message and title only."""

    platform_domain = "notify"
    _attr_supported_features = NotifyEntityFeature.TITLE

    def __init__(self, switchboard: Switchboard) -> None:
        """Initialise the entity."""
        super().__init__(switchboard, "entity", None)
        # The contract fixes the entity id; `SwitchboardGlobalEntity` would
        # have derived `notify.switchboard_entity` from the unique_id kind.
        self.entity_id = f"{self.platform_domain}.{LEGACY_SERVICE_NAME}"

    async def async_send_message(self, message: str, title: str | None = None) -> None:
        """Route to the default target with the default priority."""
        await self._switchboard.async_handle_request(
            message, title=title, data={"priority": PRIORITY_NORMAL}
        )
