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

From v0.3 (ADR-0017 §5) the five are registered in `async_setup`, once, for the
integration -- the quality-scale rule `action-setup`. An automation that names
one of them should fail its own validation only when the action genuinely does
not exist, not because a config entry happened to be unloaded. The handlers
therefore look the loaded entry up at call time instead of capturing a
`Switchboard` in a closure, and refuse with a translated
`ServiceValidationError` (`no_loaded_entry`) when there is none.

Home Assistant APIs used here (paths in home-assistant/core 2026.9.1):
- homeassistant/core.py: `ServiceRegistry.async_register` (schema=), ServiceCall
- homeassistant/core.py: `ServiceRegistry.has_service`
- homeassistant/config_entries.py: `ConfigEntries.async_loaded_entries` (line 2227)
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
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv

from .const import (
    ATTR_MINUTES,
    ATTR_PERSON,
    ATTR_TARGET,
    DOMAIN,
    ERROR_NO_LOADED_ENTRY,
    SERVICE_ACKNOWLEDGE,
    SERVICE_SILENCE,
    SERVICE_SNOOZE,
    SERVICE_UNSILENCE,
    SERVICE_UNSNOOZE,
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
def async_loaded_switchboard(hass: HomeAssistant) -> Switchboard:
    """Return the loaded entry's `Switchboard`, or refuse the call.

    `manifest.json` declares `single_config_entry: true`, so there is never
    more than one to choose from and no per-entry dispatch is needed. Looking it
    up here rather than capturing it in a closure is what lets the services live
    in `async_setup`: an unloaded entry removes their ability to act, not their
    existence (ADR-0017 §5).
    """
    for entry in hass.config_entries.async_loaded_entries(DOMAIN):
        return entry.runtime_data.switchboard  # type: ignore[no-any-return]
    raise ServiceValidationError(
        translation_domain=DOMAIN,
        translation_key=ERROR_NO_LOADED_ENTRY,
    )


@callback
def async_register_services(hass: HomeAssistant) -> None:
    """Register the five UI services, once, for the integration.

    Called from `async_setup`, so an automation referencing one of them
    validates at startup whether or not a config entry is loaded
    (quality-scale rule `action-setup`).
    """

    async def _acknowledge(call: ServiceCall) -> None:
        # `call.context` is forwarded, not just its `user_id`: the logbook
        # attributes `alert.turn_off` to whoever owns the context, so a card
        # tap shows up as that person acknowledging rather than as the
        # integration doing it on its own.
        await async_loaded_switchboard(hass).async_service_acknowledge(
            call.data[ATTR_TARGET], call.context.user_id, call.context
        )

    async def _snooze(call: ServiceCall) -> None:
        await async_loaded_switchboard(hass).async_service_snooze(
            call.data[ATTR_TARGET],
            call.data[ATTR_MINUTES],
            call.data.get(ATTR_PERSON),
            call.context.user_id,
            call.context,
        )

    async def _unsnooze(call: ServiceCall) -> None:
        await async_loaded_switchboard(hass).async_service_unsnooze(
            call.data[ATTR_TARGET], call.data.get(ATTR_PERSON)
        )

    async def _silence(call: ServiceCall) -> None:
        await async_loaded_switchboard(hass).async_service_silence(
            call.data[ATTR_PERSON], call.data[ATTR_MINUTES]
        )

    async def _unsilence(call: ServiceCall) -> None:
        await async_loaded_switchboard(hass).async_service_unsilence(
            call.data[ATTR_PERSON]
        )

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
