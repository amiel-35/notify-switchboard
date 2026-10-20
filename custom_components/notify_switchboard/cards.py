"""The dashboard cards, served by the integration itself (ADR-0024).

The two cards (`switchboard-alerts-card`, `switchboard-silence-tile`) are
built from `cards/` into `www/` and ship in the integration's release, so a
single install brings both and their versions cannot drift apart.

Home Assistant APIs used (2026.9.1):

- homeassistant/components/http/server.py: `StaticPathConfig` (imported from
  there: the package re-exports it without `__all__`),
  `HomeAssistantHTTP.async_register_static_paths`
- homeassistant/components/lovelace/__init__.py: `LovelaceData`
  (`hass.data[LOVELACE_DATA].resources`)
- homeassistant/components/lovelace/resources.py:
  `ResourceStorageCollection` (`async_get_info` loads it,
  `async_create_item` takes `res_type`, `async_update_item`,
  `async_delete_item`), `ResourceYAMLCollection.async_items`
- homeassistant/components/frontend/__init__.py: `add_extra_js_url`,
  `remove_extra_js_url`
- homeassistant/helpers/issue_registry.py: `async_create_issue`,
  `async_delete_issue`
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from homeassistant.components.frontend import add_extra_js_url, remove_extra_js_url
from homeassistant.components.http.server import StaticPathConfig
from homeassistant.components.lovelace.const import LOVELACE_DATA
from homeassistant.components.lovelace.resources import ResourceStorageCollection
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from homeassistant.loader import async_get_integration

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

CARDS_FILENAME = "notify-switchboard-cards.js"
# The whole `www/` directory is served, so the source map resolves next to it.
CARDS_URL_BASE = f"/{DOMAIN}"
CARDS_URL = f"{CARDS_URL_BASE}/{CARDS_FILENAME}"
CARDS_DIR = Path(__file__).parent / "www"

# `False` once Home Assistant runs and the path is known not to be served by
# this integration: a dashboard resource would then only point at a 404.
DATA_CARDS_SERVED = f"{DOMAIN}_cards_served"

# While the cards had a repository of their own
# (`amiel-35/notify-switchboard-cards`, up to cards 0.2.0) the bundle had the
# same file name, served by HACS (`/hacsfiles/...`, `/local/community/...`) or
# copied by hand (`/local/...`). Any resource of that name but ours is it.
ISSUE_LEGACY_CARDS = "legacy_cards_resource"


def _url_path(url: str) -> str:
    """Return a resource URL's path: no scheme, host, query or fragment.

    A resource can be written as an absolute URL
    (`http://homeassistant.local:8123/notify_switchboard/...`); it is still
    this integration's bundle.
    """
    return urlsplit(url).path


async def _async_versioned_url(hass: HomeAssistant) -> str:
    """Return the cards URL, cache-busted by the integration's version.

    The static path is served with long-lived cache headers; a new version is a
    new URL, so a browser fetches the new bundle after an upgrade.
    """
    integration = await async_get_integration(hass, DOMAIN)
    return f"{CARDS_URL}?v={integration.version}"


def _is_legacy(url: str) -> bool:
    """Tell whether a resource loads the bundle of the former card repository."""
    path = _url_path(url)
    return path.endswith(f"/{CARDS_FILENAME}") and path != CARDS_URL


async def async_register_static_path(hass: HomeAssistant) -> None:
    """Serve `www/` at `/notify_switchboard`, once per Home Assistant run.

    Without `http` (a test instance, a headless setup) there is nothing to
    serve the file to, and nothing to do. A failure is logged, never raised:
    the cards are a convenience, the actions registered next to this are not.
    """
    if hass.http is None:
        return
    # aiohttp accepts a second static resource on a prefix already taken and
    # keeps serving the first one (`http/server.py`,
    # `_async_register_static_paths` -> `router.register_resource`): a clash
    # would pass silently and the bundle would answer 404. Look first.
    taken = any(
        resource.canonical == CARDS_URL_BASE
        or resource.canonical.startswith(f"{CARDS_URL_BASE}/")
        for resource in hass.http.app.router.resources()
    )
    if taken:
        hass.data[DATA_CARDS_SERVED] = False
        _LOGGER.warning(
            "Could not serve the dashboard cards: %s is already served by "
            "something else",
            CARDS_URL_BASE,
        )
        return
    try:
        await hass.http.async_register_static_paths(
            [StaticPathConfig(CARDS_URL_BASE, str(CARDS_DIR), cache_headers=True)]
        )
    except Exception:  # noqa: BLE001 - the cards must not take the actions down
        hass.data[DATA_CARDS_SERVED] = False
        _LOGGER.warning("Could not serve the dashboard cards", exc_info=True)


async def async_register_resource(hass: HomeAssistant) -> None:
    """Make every dashboard load the cards, never failing the entry's setup.

    It runs after the router is wired: an exception here would leave the entry
    in `SETUP_ERROR` with its platforms and services still registered, and the
    next reload would fail on them. Notifications matter more than the cards.
    """
    try:
        await _async_register_resource(hass)
    except Exception:  # noqa: BLE001 - storage, `ItemNotFound`, `vol.Invalid`
        _LOGGER.warning(
            "Could not add the dashboard cards to the dashboards' resources",
            exc_info=True,
        )


async def _async_register_resource(hass: HomeAssistant) -> None:
    """Make every dashboard load the cards; idempotent.

    Dashboards managed from the UI (resources in storage mode) get one
    `module` resource, kept at the current version. Resources written in YAML
    cannot be edited from here, so the bundle is loaded as an extra frontend
    module instead.
    """
    lovelace = hass.data.get(LOVELACE_DATA)
    if lovelace is None or hass.data.get(DATA_CARDS_SERVED) is False:
        return
    url = await _async_versioned_url(hass)
    resources = lovelace.resources

    if isinstance(resources, ResourceStorageCollection):
        await resources.async_get_info()  # loads the collection from storage
        ours = [
            item
            for item in resources.async_items()
            if _url_path(item["url"]) == CARDS_URL
        ]
        if not ours:
            await resources.async_create_item({"res_type": "module", "url": url})
        else:
            first, *duplicates = ours
            # The bundle is an ES module: loaded as a plain `js` resource it
            # fails on its first `export`, so the type is put back too.
            updates: dict[str, str] = {}
            if first["url"] != url:
                updates["url"] = url
            if first.get("type") != "module":
                updates["res_type"] = "module"
            if updates:
                await resources.async_update_item(first["id"], updates)
            for item in duplicates:
                await resources.async_delete_item(item["id"])
    elif "frontend" in hass.config.components:
        add_extra_js_url(hass, url)

    _async_check_legacy_resource(hass, resources.async_items())


async def async_unregister_resource(hass: HomeAssistant) -> None:
    """Remove what `async_register_resource` added; the entry is gone."""
    ir.async_delete_issue(hass, DOMAIN, ISSUE_LEGACY_CARDS)
    lovelace = hass.data.get(LOVELACE_DATA)
    if lovelace is None:
        return
    resources = lovelace.resources
    if isinstance(resources, ResourceStorageCollection):
        await resources.async_get_info()
        for item in list(resources.async_items()):
            if _url_path(item["url"]) == CARDS_URL:
                await resources.async_delete_item(item["id"])
    elif "frontend" in hass.config.components:
        remove_extra_js_url(hass, await _async_versioned_url(hass))


def _async_check_legacy_resource(
    hass: HomeAssistant, items: list[dict[str, Any]] | None
) -> None:
    """Raise a repair while the old card repository is still loaded.

    Both bundles then define the same elements, and whichever the browser loads
    first wins -- possibly the old one. The resource belongs to HACS, which
    removes it when the old repository is uninstalled, so it is reported rather
    than deleted here.
    """
    legacy = next(
        (item["url"] for item in items or [] if _is_legacy(item.get("url", ""))),
        None,
    )
    if legacy is None:
        ir.async_delete_issue(hass, DOMAIN, ISSUE_LEGACY_CARDS)
        return
    ir.async_create_issue(
        hass,
        DOMAIN,
        ISSUE_LEGACY_CARDS,
        is_fixable=False,
        severity=ir.IssueSeverity.WARNING,
        translation_key=ISSUE_LEGACY_CARDS,
        translation_placeholders={"url": _url_path(legacy)},
    )
