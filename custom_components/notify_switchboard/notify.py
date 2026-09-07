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
    # The one entity of the integration that carries no name of its own: it is
    # the router itself, so with `has_entity_name` it reads as its device's
    # name and needs no `entity.notify.*.name` translation (ADR-0017 §2 lists
    # seven translated entities; this is not one of them). `_attr_name` set to
    # None is enough on its own -- `Entity._name_internal`
    # (`homeassistant/helpers/entity.py`) returns it before it ever looks at a
    # translation key -- but the key is cleared below too, so the code says
    # what this comment says.
    _attr_name = None

    def __init__(self, switchboard: Switchboard) -> None:
        """Initialise the entity."""
        super().__init__(switchboard, "entity")
        # Undo the two things `SwitchboardGlobalEntity` derives from `kind`
        # and that do not apply here: it would have named this entity after a
        # translation key ("entity") that has no string, and given it the id
        # `notify.switchboard_entity` where the contract fixes
        # `notify.switchboard`.
        self._attr_translation_key = None
        self._freeze_object_id(LEGACY_SERVICE_NAME)

    async def async_send_message(self, message: str, title: str | None = None) -> None:
        """Route to the default target with the default priority."""
        await self._switchboard.async_handle_request(
            message, title=title, data={"priority": PRIORITY_NORMAL}
        )
