"""Notify platform for Notify Switchboard.

Exposes the proxy on the two surfaces `alert.notifiers:` and modern
automations expect:

- `async_get_service` registers the legacy `notify.switchboard` service
  (see __init__.py, which discovers this platform with the service name
  already resolved).
- `async_setup_entry` registers a `NotifyEntity` for the same config entry.

Both simply build a `NotificationRequest`, ask the `Router` for a
`RoutingDecision`, and call every returned `notify.*` service unchanged.
Per-person routing (presence, do-not-disturb, snoozes) is not implemented
here; see router.py for the interface it will grow into.
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.notify import NotifyEntity, NotifyEntityFeature
from homeassistant.components.notify.const import ATTR_DATA, ATTR_TARGET, ATTR_TITLE
from homeassistant.components.notify.legacy import BaseNotificationService
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType

from . import SwitchboardConfigEntry, SwitchboardRuntimeData
from .router import NotificationRequest, Router, RoutingDecision

_LOGGER = logging.getLogger(__name__)


async def _dispatch(
    hass: HomeAssistant, router: Router, request: NotificationRequest
) -> None:
    """Route a request and call every notify service it resolves to.

    TODO(router): once Router.route makes real decisions, also surface
    `decision.dropped` on the diagnostic sensors described in
    docs/ARCHITECTURE.md.
    """
    decision: RoutingDecision = await router.route(request)

    for full_service in decision.targets:
        if "." not in full_service:
            _LOGGER.warning(
                "Ignoring malformed target %r: expected '<domain>.<service>'",
                full_service,
            )
            continue
        service_domain, service_name = full_service.split(".", 1)
        service_data: dict[str, Any] = {"message": request.message}
        if request.title is not None:
            service_data["title"] = request.title
        if request.data:
            service_data["data"] = request.data
        _LOGGER.debug(
            "Forwarding notification to %s.%s: %s",
            service_domain,
            service_name,
            service_data,
        )
        await hass.services.async_call(
            service_domain, service_name, service_data, blocking=True
        )


async def async_get_service(
    hass: HomeAssistant,
    config: ConfigType,
    discovery_info: DiscoveryInfoType | None = None,
) -> BaseNotificationService | None:
    """Set up the legacy `notify.switchboard` service.

    `discovery_info` is populated by __init__.py's `async_setup_entry` with
    the `entry_id` of the config entry it was discovered for.
    """
    if discovery_info is None or "entry_id" not in discovery_info:
        _LOGGER.error("Notify Switchboard can only be set up through the UI")
        return None

    entry = hass.config_entries.async_get_entry(discovery_info["entry_id"])
    if entry is None or not hasattr(entry, "runtime_data"):
        _LOGGER.error("Notify Switchboard config entry is not loaded")
        return None

    runtime_data: SwitchboardRuntimeData = entry.runtime_data
    return SwitchboardNotificationService(hass, runtime_data.router)


class SwitchboardNotificationService(BaseNotificationService):
    """Legacy notify service that proxies to the Router."""

    def __init__(self, hass: HomeAssistant, router: Router) -> None:
        """Initialize the service."""
        self.hass = hass
        self._router = router

    async def async_send_message(self, message: str, **kwargs: Any) -> None:
        """Forward a message to the notify services chosen by the Router."""
        request = NotificationRequest(
            message=message,
            title=kwargs.get(ATTR_TITLE),
            target=kwargs.get(ATTR_TARGET),
            data=dict(kwargs.get(ATTR_DATA) or {}),
        )
        await _dispatch(self.hass, self._router, request)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SwitchboardConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Notify Switchboard entity for a config entry."""
    async_add_entities([SwitchboardNotifyEntity(entry)])


class SwitchboardNotifyEntity(NotifyEntity):
    """Modern notify entity that proxies to the Router."""

    _attr_has_entity_name = True
    _attr_name = "Switchboard"
    _attr_supported_features = NotifyEntityFeature.TITLE

    def __init__(self, entry: ConfigEntry) -> None:
        """Initialize the entity."""
        self._attr_unique_id = f"{entry.entry_id}_notify_entity"
        self._router: Router = entry.runtime_data.router

    async def async_send_message(self, message: str, title: str | None = None) -> None:
        """Forward a message to the notify services chosen by the Router.

        Overrides the base class instead of `send_message` so no executor
        job is scheduled: routing and dispatch are pure async I/O against
        Home Assistant's own service bus.
        """
        request = NotificationRequest(message=message, title=title)
        await _dispatch(self.hass, self._router, request)
