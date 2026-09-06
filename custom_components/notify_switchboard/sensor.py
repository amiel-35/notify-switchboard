"""Diagnostic sensors for Notify Switchboard (contract §3.5)."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from .const import ATTR_REASONS
from .dispatcher import Switchboard
from .entity import SwitchboardGlobalEntity, SwitchboardPersonEntity
from .router import PersonConfig

if TYPE_CHECKING:
    from . import SwitchboardConfigEntry


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SwitchboardConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the global and per-person sensors."""
    switchboard = entry.runtime_data.switchboard
    entities: list[SwitchboardGlobalEntity | SwitchboardPersonEntity] = [
        RoutedTodaySensor(switchboard),
        DroppedTodaySensor(switchboard),
    ]
    for person in switchboard.table.persons.values():
        entities.append(LastNotificationSensor(switchboard, person))
        entities.append(ActiveSnoozesSensor(switchboard, person))
    async_add_entities(entities)


class RoutedTodaySensor(SwitchboardGlobalEntity, SensorEntity):
    """How many (person, target) deliveries were routed since local midnight."""

    _attr_state_class = SensorStateClass.TOTAL
    _attr_native_unit_of_measurement = "notifications"

    def __init__(self, switchboard: Switchboard) -> None:
        """Initialise `sensor.switchboard_routed_today`."""
        super().__init__(switchboard, "routed_today", "Routed today")

    @property
    def native_value(self) -> int:
        """Return the number of routed deliveries."""
        return self._switchboard.routed_today


class DroppedTodaySensor(SwitchboardGlobalEntity, SensorEntity):
    """How many deliveries were dropped since local midnight, and why."""

    _attr_state_class = SensorStateClass.TOTAL
    _attr_native_unit_of_measurement = "notifications"

    def __init__(self, switchboard: Switchboard) -> None:
        """Initialise `sensor.switchboard_dropped_today`."""
        super().__init__(switchboard, "dropped_today", "Dropped today")

    @property
    def native_value(self) -> int:
        """Return the number of dropped deliveries."""
        return self._switchboard.dropped_today

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose the drop reasons as `reasons: {reason: count}`."""
        return {ATTR_REASONS: dict(self._switchboard.drop_reasons)}


class LastNotificationSensor(SwitchboardPersonEntity, SensorEntity):
    """When this person was last notified."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, switchboard: Switchboard, person: PersonConfig) -> None:
        """Initialise `sensor.<person>_last_notification`."""
        super().__init__(switchboard, person, "last_notification", "Last notification")

    @property
    def native_value(self) -> datetime | None:
        """Return the timestamp of the last routed delivery."""
        return self._switchboard.last_notification.get(self._person.entity_id)


class ActiveSnoozesSensor(SwitchboardPersonEntity, SensorEntity):
    """How many snoozes are currently running for this person."""

    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "snoozes"

    def __init__(self, switchboard: Switchboard, person: PersonConfig) -> None:
        """Initialise `sensor.<person>_active_snoozes`."""
        super().__init__(switchboard, person, "active_snoozes", "Active snoozes")

    @property
    def native_value(self) -> int:
        """Return the number of active snoozes."""
        return self._switchboard.store.active_snoozes(
            self._person.entity_id, dt_util.utcnow()
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose the snoozed targets and their expiry."""
        now = dt_util.utcnow()
        return {
            "targets": {
                slug: expiry.isoformat()
                for (person, slug), expiry in self._switchboard.store.snoozes.items()
                if person == self._person.entity_id and expiry > now
            }
        }
