"""Per-person silence binary sensors (contract §3.5)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .dispatcher import Switchboard
from .entity import SwitchboardPersonEntity
from .router import PersonConfig

if TYPE_CHECKING:
    from . import SwitchboardConfigEntry


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SwitchboardConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up one silence sensor per configured person."""
    switchboard = entry.runtime_data.switchboard
    async_add_entities(
        SilencedBinarySensor(switchboard, person)
        for person in switchboard.table.persons.values()
    )


class SilencedBinarySensor(SwitchboardPersonEntity, BinarySensorEntity):
    """True while any of the person's silence entities is `on`."""

    platform_domain = "binary_sensor"

    def __init__(self, switchboard: Switchboard, person: PersonConfig) -> None:
        """Initialise `binary_sensor.<person>_silenced`."""
        super().__init__(switchboard, person, "silenced", "Silenced")

    @property
    def is_on(self) -> bool:
        """Return whether the person is currently silenced."""
        return self._switchboard.is_person_silenced(self._person)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose which entities the silence is computed from."""
        return {"sources": list(self._person.silence_entities)}
