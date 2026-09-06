"""`event.switchboard_delivery` -- the router's one-off facts (contract §3.5).

This is not a log: history is the recorder's job. The entity carries the four
frozen event types and the attributes of the last one.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.components.event import EventEntity
from homeassistant.core import Context, HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import DELIVERY_EVENT_TYPES, DOMAIN
from .dispatcher import Switchboard
from .entity import SwitchboardGlobalEntity

if TYPE_CHECKING:
    from . import SwitchboardConfigEntry


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SwitchboardConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the single delivery event entity."""
    async_add_entities([DeliveryEvent(entry.runtime_data.switchboard)])


class DeliveryEvent(SwitchboardGlobalEntity, EventEntity):
    """One event per routing outcome."""

    platform_domain = "event"
    _attr_event_types = DELIVERY_EVENT_TYPES

    def __init__(self, switchboard: Switchboard) -> None:
        """Initialise `event.switchboard_delivery`."""
        super().__init__(switchboard, "delivery", "Delivery")

    async def async_added_to_hass(self) -> None:
        """Subscribe to the switchboard's delivery signal."""
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                f"{DOMAIN}_delivery_{self._entry_id}",
                self._handle_delivery,
            )
        )

    @callback
    def _handle_delivery(
        self,
        event_type: str,
        attributes: dict[str, Any],
        context: Context | None = None,
    ) -> None:
        """Record one delivery event.

        When the switchboard acted for somebody — a UI service call, a
        Companion button — that caller's `Context` is adopted before the state
        is written (`homeassistant/helpers/entity.py`, `async_set_context`), so
        the logbook credits the acknowledgement or the snooze to them rather
        than to the integration.
        """
        if context is not None:
            self.async_set_context(context)
        self._trigger_event(event_type, attributes)
        self.async_write_ha_state()

    @callback
    def _handle_update(self) -> None:
        """Ignore plain state refreshes: an event entity only moves on events."""
