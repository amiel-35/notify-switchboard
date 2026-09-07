"""Shared entity plumbing for Notify Switchboard.

Contract §"Names" fixes the `unique_id` scheme (`<entry_id>:<person entity_id>:
<kind>`) and the entity ids; `tests/acceptance/README.md` fixes how the
per-person ones are derived from the person's object_id.

Both halves of contract v0.3 §"Names" (ADR-0017 §2) live here:

- the **friendly name** is translated, through `_attr_translation_key` plus an
  `entity.<platform>.<key>.name` string in `strings.json` and every
  `translations/*.json`. The `kind` a class already passes for its `unique_id`
  is reused verbatim as the translation key, so the id, the key and the word
  all say the same thing;
- the **entity id** stays the frozen English one **in every instance
  language**, by setting `self.entity_id` in `__init__`.

The second point is not a formality. `EntityPlatform.async_load_translations`
(`homeassistant/helpers/entity_platform.py`, lines 222-244) builds object ids
from `hass.config.language` whenever that language is in `NATIVE_ENTITY_IDS`
(`homeassistant/generated/languages.py`, line 75) -- `fr` and `es` both are.
The default `Entity.suggested_object_id`
(`homeassistant/helpers/entity.py`, line 747) returns the *localized* name, so
adding a translation key and nothing else renames every entity of the
integration on exactly the installs the translation was added for.

Which override actually freezes the id is worth spelling out, because the two
candidates do **not** behave the same in 2026.9.1 and only one of them works
for an entity that has both `has_entity_name` and a device:

- overriding the `suggested_object_id` **property** feeds
  `object_id_base` -- `_async_derive_object_ids`
  (`homeassistant/helpers/entity_platform.py`, lines 1296-1329) leaves
  `is_base` True on that path -- and `object_id_base` is composed with the
  device name (`homeassistant/helpers/entity_registry.py`,
  `_async_generate_entity_id` -> `_async_get_full_entity_name`, lines
  1364-1387). Every entity here belongs to a device ("Switchboard", or the
  person), so that route yields `sensor.switchboard_switchboard_routed_today`;
- setting `self.entity_id` makes the platform record
  `internal_integration_suggested_object_id`
  (`homeassistant/helpers/entity_platform.py`, lines 886-909), which
  `_async_derive_object_ids` passes as the registry's `suggested_object_id`
  -- the value that "has priority over `object_id_base`" and "will not be
  prefixed with the device name"
  (`homeassistant/helpers/entity_registry.py`, lines 1357-1361).

So the second route is the one used, exactly as 0.1.0/0.2.0 already did;
ADR-0017 §2 explicitly allows it ("Either way the requirement is behavioural")
and `tests/acceptance/test_s3_entities.py` asserts the behaviour, not the
mechanism. `_frozen_object_id` names the value in one place so the intent is
readable rather than hidden in an f-string.
"""

from __future__ import annotations

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import Entity

from .const import DOMAIN, LEGACY_SERVICE_NAME, SIGNAL_STATE_UPDATED
from .dispatcher import Switchboard
from .router import PersonConfig

ROUTER_DEVICE_NAME = "Switchboard"


def router_device_info(entry_id: str) -> DeviceInfo:
    """Return the service device representing the router itself."""
    return DeviceInfo(
        identifiers={(DOMAIN, entry_id)},
        name=ROUTER_DEVICE_NAME,
        entry_type=DeviceEntryType.SERVICE,
        manufacturer="Notify Switchboard",
    )


def person_device_name(hass: HomeAssistant, person: PersonConfig) -> str:
    """Return the name to give one person's virtual device.

    A `person.*` entity is renamed in the UI without its entity id following,
    so the object_id is not the person's name -- `person.alice` may well be
    "Alice Martin". `State.name` is the friendly name when there is one and
    the titled object_id otherwise (`homeassistant/core.py`, `State.name`),
    which is exactly what is wanted here.

    The titled object_id remains the fallback for the case there is no state
    at all: at setup a restart can reach this before the `person` integration
    has written its states.
    """
    if (state := hass.states.get(person.entity_id)) is not None:
        return state.name
    return person.object_id.replace("_", " ").title()


def person_device_info(
    hass: HomeAssistant, entry_id: str, person: PersonConfig
) -> DeviceInfo:
    """Return the virtual device grouping one person's entities."""
    return DeviceInfo(
        identifiers={(DOMAIN, f"{entry_id}:{person.entity_id}")},
        name=person_device_name(hass, person),
        entry_type=DeviceEntryType.SERVICE,
        manufacturer="Notify Switchboard",
    )


class SwitchboardEntity(Entity):
    """Base entity: no polling, refreshed by the switchboard's signal.

    `_frozen_object_id` is the object id the contract froze for this entity.
    It is returned by `suggested_object_id` so the id never follows the
    instance language; see the module docstring.
    """

    _attr_has_entity_name = True
    _attr_should_poll = False

    platform_domain = "sensor"

    def __init__(self, switchboard: Switchboard) -> None:
        """Store the switchboard this entity reports on."""
        self._switchboard = switchboard
        self._entry_id = switchboard.entry.entry_id

    def _freeze_object_id(self, object_id: str) -> None:
        """Pin the entity id to the English form the contract froze."""
        self._frozen_object_id = object_id
        self.entity_id = f"{self.platform_domain}.{object_id}"

    async def async_added_to_hass(self) -> None:
        """Subscribe to the switchboard's state-updated signal."""
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                f"{SIGNAL_STATE_UPDATED}_{self._entry_id}",
                self._handle_update,
            )
        )

    @callback
    def _handle_update(self) -> None:
        """Write the new state after a routing decision."""
        self.async_write_ha_state()


class SwitchboardGlobalEntity(SwitchboardEntity):
    """A router-wide entity (`*.switchboard_*`)."""

    def __init__(self, switchboard: Switchboard, kind: str) -> None:
        """Initialise a global entity of the given kind."""
        super().__init__(switchboard)
        self._attr_unique_id = f"{self._entry_id}:{kind}"
        self._attr_translation_key = kind
        self._attr_device_info = router_device_info(self._entry_id)
        self._freeze_object_id(f"{LEGACY_SERVICE_NAME}_{kind}")


class SwitchboardPersonEntity(SwitchboardEntity):
    """A per-person entity (`*.<person object_id>_*`)."""

    def __init__(
        self,
        switchboard: Switchboard,
        person: PersonConfig,
        kind: str,
    ) -> None:
        """Initialise a per-person entity of the given kind."""
        super().__init__(switchboard)
        self._person = person
        self._attr_unique_id = f"{self._entry_id}:{person.entity_id}:{kind}"
        self._attr_translation_key = kind
        self._attr_device_info = person_device_info(
            switchboard.hass, self._entry_id, person
        )
        self._freeze_object_id(f"{person.object_id}_{kind}")
