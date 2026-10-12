"""Create a person's night as a core `schedule` helper the user owns (ADR-0022 §5).

The options flow offers "Create a night schedule for {person}". Ticking it
creates an ordinary `schedule` helper -- exactly what **Settings → Helpers →
Schedule** would create -- and the flow lists it as that person's silence.
From then on the helper is the user's: this module creates or finds one and
returns its entity id; nothing in the integration ever edits or deletes it.

Home Assistant APIs used here (paths in home-assistant/core 2026.9.1):

- homeassistant/components/schedule/__init__.py: `async_setup` keeps the
  UI-created schedules in a `ScheduleStorageCollection` (a
  `DictStorageCollection`) held in a local variable, and exposes it only
  through `DictStorageCollectionWebsocket(storage_collection, "schedule",
  "schedule", ...).async_setup(hass)`. `valid_schedule` refuses a block whose
  `from` is not before its `to`, so a night is two blocks a day; `24:00:00`
  is accepted as the end of a day (`deserialize_to_time`).
  `ScheduleStorageCollection._process_create_data` validates the item with
  `BASE_SCHEMA | STORAGE_SCHEDULE_SCHEMA`, as the websocket create does.
- homeassistant/helpers/collection.py: `StorageCollectionWebsocket.async_setup`
  registers `<prefix>/list` with the bound method `self.ws_list_item`, wrapped
  by `require_admin` only when `admin_only` is set (it is not for
  `schedule`); `StorageCollection.async_create_item(data)` is the method the
  `<prefix>/create` command calls, and its change listener
  (`_CollectionLifeCycle._collection_changed`) awaits `async_add_entities`
  before it returns; `StorageCollection.async_items()`.
- homeassistant/components/websocket_api/__init__.py: `async_register_command`
  stores `hass.data["websocket_api"][command] = (handler, schema)`.
- homeassistant/helpers/entity_registry.py: `EntityRegistry.async_get_entity_id
  (domain, platform, unique_id)`; a schedule's unique id is its item id
  (`Schedule.__init__`, `_attr_unique_id = self._config[CONF_ID]`).
- homeassistant/setup.py: `async_setup_component`.

The websocket registry is the only place core keeps a reference to the
collection, and following it is the one implementation detail this
integration leans on. Every step of that lookup is checked, and any surprise
returns None: the flow then shows an error on the checkbox and writes
nothing. A core that moves the collection breaks one checkbox, visibly, and
nothing else.
"""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.setup import async_setup_component

_LOGGER = logging.getLogger(__name__)

SCHEDULE_DOMAIN = "schedule"
WEBSOCKET_DOMAIN = "websocket_api"
LIST_COMMAND = f"{SCHEDULE_DOMAIN}/list"

DAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")

# ADR-0022 §5: 22:00 to 07:00 every day. A schedule block cannot cross
# midnight, so the night is the end of one day and the start of the next.
NIGHT_START = "22:00:00"
NIGHT_END = "07:00:00"
NIGHT_BLOCKS: tuple[dict[str, str], ...] = (
    {"from": "00:00:00", "to": NIGHT_END},
    {"from": NIGHT_START, "to": "24:00:00"},
)
NIGHT_ICON = "mdi:weather-night"


def night_schedule_item(name: str) -> dict[str, Any]:
    """Return the storage item of a night called `name`, every day 22:00-07:00."""
    return {
        "name": name,
        "icon": NIGHT_ICON,
        **{day: [dict(block) for block in NIGHT_BLOCKS] for day in DAYS},
    }


def _storage_collection(hass: HomeAssistant) -> Any | None:
    """Return core's schedule storage collection, or None when it cannot be found.

    See the module docstring: the `schedule/list` websocket handler is a bound
    method of the `StorageCollectionWebsocket` that owns the collection.
    """
    handlers = hass.data.get(WEBSOCKET_DOMAIN)
    if not isinstance(handlers, dict):
        return None
    registered = handlers.get(LIST_COMMAND)
    if not isinstance(registered, tuple) or not registered:
        return None
    owner = getattr(registered[0], "__self__", None)
    collection = getattr(owner, "storage_collection", None)
    if not callable(getattr(collection, "async_create_item", None)) or not callable(
        getattr(collection, "async_items", None)
    ):
        return None
    return collection


async def async_ensure_night_schedule(hass: HomeAssistant, name: str) -> str | None:
    """Return the entity id of the night called `name`, creating it if needed.

    A schedule already stored under that exact name is reused, so ticking the
    box twice gives one night. Returns None when the schedule collection
    cannot be reached or refuses the item; nothing has been created then.
    """
    if SCHEDULE_DOMAIN not in hass.config.components and not (
        await async_setup_component(hass, SCHEDULE_DOMAIN, {})
    ):
        _LOGGER.warning("The schedule integration could not be set up")
        return None

    collection = _storage_collection(hass)
    if collection is None:
        _LOGGER.warning(
            "Home Assistant's schedule helpers could not be reached; "
            "no night schedule was created"
        )
        return None

    item_id: str | None = None
    for item in collection.async_items():
        if isinstance(item, dict) and item.get("name") == name and item.get("id"):
            item_id = str(item["id"])
            break
    if item_id is None:
        try:
            created = await collection.async_create_item(night_schedule_item(name))
        except vol.Invalid, ValueError, HomeAssistantError:
            # `async_create_item` validates before it stores anything, so a
            # refusal leaves nothing behind.
            _LOGGER.warning("The night schedule %r could not be created", name)
            _LOGGER.debug("Refusal", exc_info=True)
            return None
        item_id = str(created["id"])

    entity_id = er.async_get(hass).async_get_entity_id(
        SCHEDULE_DOMAIN, SCHEDULE_DOMAIN, item_id
    )
    if entity_id is None:
        _LOGGER.warning("The night schedule %r has no entity", name)
    return entity_id
