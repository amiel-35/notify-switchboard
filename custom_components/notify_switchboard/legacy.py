"""The legacy `notify.switchboard[_<slug>]` services.

`alert.notifiers:` can only call a legacy notify service
(`homeassistant/components/notify/legacy.py`, `BaseNotificationService`), so
this is the router's main entry point (doctrine §3.1). The `targets` property
is what makes core register one `notify.switchboard_<slug>` service per row of
the routing table.

The service is registered directly rather than through
`homeassistant.helpers.discovery.async_load_platform`: the discovery route can
only be undone with `notify.async_reset_platform`, which cancels the `notify`
integration's *global* discovery dispatcher and would stop the service from
coming back after a config entry reload.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from homeassistant.components.notify.const import ATTR_DATA, ATTR_TARGET, ATTR_TITLE
from homeassistant.components.notify.legacy import BaseNotificationService
from homeassistant.core import HomeAssistant

from .const import LEGACY_SERVICE_NAME

if TYPE_CHECKING:
    from .dispatcher import Switchboard

_LOGGER = logging.getLogger(__name__)


class SwitchboardNotificationService(BaseNotificationService):
    """Legacy notify service that hands every call to the `Switchboard`."""

    def __init__(self, switchboard: Switchboard) -> None:
        """Initialise the service for one config entry."""
        self._switchboard = switchboard
        self._registered = False

    @property
    def targets(self) -> Mapping[str, Any] | None:
        """Return one target per routing-table row.

        Core turns each key into `notify.switchboard_<key>` (see
        `BaseNotificationService.async_register_services`).
        """
        return {slug: slug for slug in self._switchboard.table.targets}

    async def async_register(self, hass: HomeAssistant) -> None:
        """Register `notify.switchboard` and every per-target service."""
        await self.async_setup(hass, LEGACY_SERVICE_NAME, LEGACY_SERVICE_NAME)
        await self.async_register_services()
        self._registered = True

    async def async_unregister(self) -> None:
        """Remove every service this class registered."""
        if not self._registered:
            return
        await self.async_unregister_services()
        self._registered = False

    async def async_send_message(self, message: str, **kwargs: Any) -> None:
        """Route one message (contract "Input")."""
        target = kwargs.get(ATTR_TARGET)
        _LOGGER.debug("notify.switchboard called for %s", target)
        await self._switchboard.async_handle_request(
            message,
            title=kwargs.get(ATTR_TITLE),
            targets=list(target) if target else None,
            data=kwargs.get(ATTR_DATA) or {},
        )
