"""The `notify_switchboard.*` UI services (v0.2 addendum, ADR-0016).

A Lovelace card, a script or an automation cannot originate a
`mobile_app_notification_action` event: it has no device registration and no
webhook. Everything the Companion buttons can do — and one thing they cannot,
a temporary person-wide silence — is therefore also a domain service here.

The behavioural difference with the Companion callback path is deliberate and
is the whole point of ADR-0016: an event handler has nobody to answer to and
logs a refusal, while a service call has a caller and raises
`ServiceValidationError` (`homeassistant/exceptions.py`). The validation
itself is not duplicated: every handler below delegates to the `Switchboard`
methods that the Companion path already uses.

Home Assistant APIs used here (paths in home-assistant/core 2026.9.1):
- homeassistant/core.py: `ServiceRegistry.async_register` (schema=), ServiceCall
- homeassistant/core.py: `ServiceRegistry.async_remove`, `has_service`
- homeassistant/helpers/config_validation.py: entity_id, positive_int
- homeassistant/exceptions.py: ServiceValidationError (raised by the Switchboard)

Voluptuous schemas here are deliberately permissive about *values* and strict
only about *shapes*: `hass.services.async_call` re-raises a `vol.Invalid` from
a service schema as-is (`homeassistant/core.py`, `ServiceRegistry.async_call`),
which is not a `ServiceValidationError`. Anything the contract says must be
refused with a `ServiceValidationError` — `minutes: 0`, a duration the row does
not offer, an unknown target or person — is therefore checked in the handler,
not in the schema.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import voluptuous as vol
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.helpers import config_validation as cv

from .const import (
    ATTR_MINUTES,
    ATTR_PERSON,
    ATTR_TARGET,
    DOMAIN,
    SERVICE_ACKNOWLEDGE,
    SERVICE_SILENCE,
    SERVICE_SNOOZE,
    SERVICE_UNSILENCE,
    SERVICE_UNSNOOZE,
    UI_SERVICES,
)

if TYPE_CHECKING:
    from .dispatcher import Switchboard

ACKNOWLEDGE_SCHEMA = vol.Schema({vol.Required(ATTR_TARGET): cv.string})

SNOOZE_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_TARGET): cv.string,
        vol.Required(ATTR_MINUTES): vol.Coerce(int),
        vol.Optional(ATTR_PERSON): cv.entity_id,
    }
)

UNSNOOZE_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_TARGET): cv.string,
        vol.Optional(ATTR_PERSON): cv.entity_id,
    }
)

SILENCE_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_PERSON): cv.entity_id,
        vol.Required(ATTR_MINUTES): vol.Coerce(int),
    }
)

UNSILENCE_SCHEMA = vol.Schema({vol.Required(ATTR_PERSON): cv.entity_id})


@callback
def async_register_services(hass: HomeAssistant, switchboard: Switchboard) -> None:
    """Register the five UI services for the (single) config entry.

    `manifest.json` declares `single_config_entry: true`, so one switchboard
    owns the domain's services outright and no per-entry dispatch is needed.
    """

    async def _acknowledge(call: ServiceCall) -> None:
        # `call.context` is forwarded, not just its `user_id`: the logbook
        # attributes `alert.turn_off` to whoever owns the context, so a card
        # tap shows up as that person acknowledging rather than as the
        # integration doing it on its own.
        await switchboard.async_service_acknowledge(
            call.data[ATTR_TARGET], call.context.user_id, call.context
        )

    async def _snooze(call: ServiceCall) -> None:
        await switchboard.async_service_snooze(
            call.data[ATTR_TARGET],
            call.data[ATTR_MINUTES],
            call.data.get(ATTR_PERSON),
            call.context.user_id,
            call.context,
        )

    async def _unsnooze(call: ServiceCall) -> None:
        await switchboard.async_service_unsnooze(
            call.data[ATTR_TARGET], call.data.get(ATTR_PERSON)
        )

    async def _silence(call: ServiceCall) -> None:
        await switchboard.async_service_silence(
            call.data[ATTR_PERSON], call.data[ATTR_MINUTES]
        )

    async def _unsilence(call: ServiceCall) -> None:
        await switchboard.async_service_unsilence(call.data[ATTR_PERSON])

    hass.services.async_register(
        DOMAIN, SERVICE_ACKNOWLEDGE, _acknowledge, schema=ACKNOWLEDGE_SCHEMA
    )
    hass.services.async_register(DOMAIN, SERVICE_SNOOZE, _snooze, schema=SNOOZE_SCHEMA)
    hass.services.async_register(
        DOMAIN, SERVICE_UNSNOOZE, _unsnooze, schema=UNSNOOZE_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, SERVICE_SILENCE, _silence, schema=SILENCE_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, SERVICE_UNSILENCE, _unsilence, schema=UNSILENCE_SCHEMA
    )


@callback
def async_unregister_services(hass: HomeAssistant) -> None:
    """Remove the five UI services, so an unload leaves none dangling.

    The closures above hold the unloaded entry's `Switchboard`; a service left
    behind would keep writing to a store nothing reloads.
    """
    for service in UI_SERVICES:
        hass.services.async_remove(DOMAIN, service)
