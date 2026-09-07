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
    """True while either silence source covers the person (ADR-0016).

    The two sources are the person's own `silence_entities` (read, never owned)
    and a temporary `notify_switchboard.silence` the router does own.
    """

    platform_domain = "binary_sensor"

    def __init__(self, switchboard: Switchboard, person: PersonConfig) -> None:
        """Initialise `binary_sensor.<person>_silenced`."""
        super().__init__(switchboard, person, "silenced")

    @property
    def is_on(self) -> bool:
        """Return whether the person is currently silenced."""
        return self._switchboard.is_person_silenced(self._person)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose which entities the silence is computed from, and its end.

        `sources` keeps its Sprint 1 meaning: the configured entities only.
        `until` is added when a temporary silence is running, so a card can say
        how long the quiet lasts (ADR-0016 explicitly allows this; only the
        entity id is frozen by the contract, not its attributes).
        """
        attributes: dict[str, Any] = {"sources": list(self._person.silence_entities)}
        if (
            until := self._switchboard.temporary_silence_until(self._person)
        ) is not None:
            attributes["until"] = until.isoformat()
        return attributes
