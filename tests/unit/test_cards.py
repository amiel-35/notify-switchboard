"""The dashboard cards served by the integration itself (ADR-0024).

The bundle ships in `www/`; the integration serves it at `/notify_switchboard`
and keeps one `module` resource for it in the dashboards' resources, at the
current version. An old `/hacsfiles/notify-switchboard-cards/` resource raises
a repair instead of being touched.
"""

from __future__ import annotations

import json
from http import HTTPStatus
from pathlib import Path
from typing import Any
from unittest.mock import patch

import homeassistant.helpers.issue_registry as ir
import pytest
from homeassistant.components.http.server import StaticPathConfig
from homeassistant.components.lovelace.const import LOVELACE_DATA
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_mock_service,
)

from custom_components.notify_switchboard import cards
from custom_components.notify_switchboard.const import DOMAIN

PACKAGE = Path(cards.__file__).parent
REPO = PACKAGE.parent.parent
VERSION = json.loads((PACKAGE / "manifest.json").read_text(encoding="utf-8"))["version"]
# One person, one phone, one target for everybody: enough to see a message go
# through (the routing itself is `test_dispatcher.py`'s business).
ROUTING_TABLE: dict[str, Any] = {
    "persons": [
        {
            "entity_id": "person.alice",
            "outputs": ["notify.mobile_app_alice"],
            "silence_entities": [],
            "wake_time": None,
        }
    ],
    "targets": [
        {
            "slug": "default",
            "name": "Default",
            "default_priority": "normal",
            "alert_entity": None,
            "audience": ["person.alice"],
            "presence_rule": "always",
            "allow_acknowledge": False,
            "snooze_minutes": [],
            "default_data": {},
            "observer_mode": False,
            "message": None,
            "done_message": None,
            "default_title": None,
        }
    ],
    "default_target": "default",
}
URL = f"/notify_switchboard/notify-switchboard-cards.js?v={VERSION}"
LEGACY_URL = "/hacsfiles/notify-switchboard-cards/notify-switchboard-cards.js"


def seed_resources(hass_storage: dict[str, Any], *urls: str) -> None:
    """Put resources in storage before `lovelace` loads them."""
    hass_storage["lovelace_resources"] = {
        "version": 1,
        "minor_version": 1,
        "key": "lovelace_resources",
        "data": {
            "items": [
                {"id": f"res{index}", "type": "module", "url": url}
                for index, url in enumerate(urls)
            ]
        },
    }


async def install(
    hass: HomeAssistant, options: dict[str, Any] | None = None
) -> MockConfigEntry:
    """Create and set up an entry, with an empty routing table by default."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id="ns_cards_entry",
        title="Notify Switchboard",
        version=1,
        minor_version=1,
        options=options or {"persons": [], "targets": [], "default_target": None},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def resource_urls(hass: HomeAssistant) -> list[str]:
    return [item["url"] for item in hass.data[LOVELACE_DATA].resources.async_items()]


# ---------------------------------------------------------------------------
# The bundle itself
# ---------------------------------------------------------------------------


def test_the_built_bundle_ships_in_the_integration() -> None:
    assert (PACKAGE / "www" / cards.CARDS_FILENAME).is_file()


def test_the_cards_carry_the_integrations_version() -> None:
    """One version for both: they are released together or not at all."""
    package = json.loads((REPO / "cards" / "package.json").read_text("utf-8"))
    assert package["version"] == VERSION


async def test_the_bundle_is_served(hass: HomeAssistant, hass_client: Any) -> None:
    assert await async_setup_component(hass, "http", {})
    await install(hass)
    client = await hass_client()

    response = await client.get(URL)

    assert response.status == HTTPStatus.OK
    assert "switchboard-alerts-card" in await response.text()


# ---------------------------------------------------------------------------
# Resources managed from the UI (storage mode)
# ---------------------------------------------------------------------------


async def test_a_module_resource_is_added(
    hass: HomeAssistant, hass_storage: dict[str, Any]
) -> None:
    assert await async_setup_component(hass, "lovelace", {})
    await install(hass)

    items = hass.data[LOVELACE_DATA].resources.async_items()
    assert [(item["type"], item["url"]) for item in items] == [("module", URL)]


async def test_an_older_version_is_moved_to_this_one(
    hass: HomeAssistant, hass_storage: dict[str, Any]
) -> None:
    seed_resources(
        hass_storage,
        "/local/other-card.js",
        "/notify_switchboard/notify-switchboard-cards.js?v=0.9.9",
        "/notify_switchboard/notify-switchboard-cards.js",
    )
    assert await async_setup_component(hass, "lovelace", {})
    await install(hass)

    assert resource_urls(hass) == ["/local/other-card.js", URL]


async def test_a_resource_of_the_wrong_type_is_made_a_module(
    hass: HomeAssistant, hass_storage: dict[str, Any]
) -> None:
    """The bundle is an ES module; as a plain `js` resource it never loads."""
    hass_storage["lovelace_resources"] = {
        "version": 1,
        "minor_version": 1,
        "key": "lovelace_resources",
        "data": {"items": [{"id": "res0", "type": "js", "url": URL}]},
    }
    assert await async_setup_component(hass, "lovelace", {})
    await install(hass)

    items = hass.data[LOVELACE_DATA].resources.async_items()
    assert [(item["type"], item["url"]) for item in items] == [("module", URL)]


async def test_an_absolute_url_to_the_bundle_is_ours_not_a_legacy_copy(
    hass: HomeAssistant,
    hass_storage: dict[str, Any],
    issue_registry: ir.IssueRegistry,
) -> None:
    seed_resources(
        hass_storage,
        "http://homeassistant.local:8123/notify_switchboard/notify-switchboard-cards.js",
    )
    assert await async_setup_component(hass, "lovelace", {})
    await install(hass)

    assert resource_urls(hass) == [URL]
    assert issue_registry.async_get_issue(DOMAIN, cards.ISSUE_LEGACY_CARDS) is None


async def test_a_reload_adds_nothing(
    hass: HomeAssistant, hass_storage: dict[str, Any]
) -> None:
    assert await async_setup_component(hass, "lovelace", {})
    entry = await install(hass)

    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()

    assert resource_urls(hass) == [URL]


async def test_removing_the_entry_removes_the_resource(
    hass: HomeAssistant, hass_storage: dict[str, Any]
) -> None:
    seed_resources(hass_storage, "/local/other-card.js")
    assert await async_setup_component(hass, "lovelace", {})
    entry = await install(hass)

    assert await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()

    assert resource_urls(hass) == ["/local/other-card.js"]


# ---------------------------------------------------------------------------
# The former card repository
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "legacy_url",
    [
        "/local/community/notify-switchboard-cards/notify-switchboard-cards.js",
        "/local/notify-switchboard-cards.js",
    ],
)
async def test_any_other_copy_of_the_bundle_raises_the_repair(
    hass: HomeAssistant,
    hass_storage: dict[str, Any],
    issue_registry: ir.IssueRegistry,
    legacy_url: str,
) -> None:
    """HACS's other path, or a copy placed in `www/` by hand."""
    seed_resources(hass_storage, legacy_url)
    assert await async_setup_component(hass, "lovelace", {})
    await install(hass)

    issue = issue_registry.async_get_issue(DOMAIN, cards.ISSUE_LEGACY_CARDS)
    assert issue is not None
    assert issue.translation_placeholders == {"url": legacy_url}


async def test_the_old_hacs_resource_raises_a_repair(
    hass: HomeAssistant,
    hass_storage: dict[str, Any],
    issue_registry: ir.IssueRegistry,
) -> None:
    seed_resources(hass_storage, f"{LEGACY_URL}?hacstag=123")
    assert await async_setup_component(hass, "lovelace", {})
    entry = await install(hass)

    issue = issue_registry.async_get_issue(DOMAIN, cards.ISSUE_LEGACY_CARDS)
    assert issue is not None
    assert issue.translation_placeholders == {"url": LEGACY_URL}
    # HACS owns that resource: it is reported, never deleted.
    assert f"{LEGACY_URL}?hacstag=123" in resource_urls(hass)

    # Uninstalling the old cards from HACS removes the resource; the repair
    # goes with it on the next reload.
    resources = hass.data[LOVELACE_DATA].resources
    await resources.async_delete_item("res0")
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()

    assert issue_registry.async_get_issue(DOMAIN, cards.ISSUE_LEGACY_CARDS) is None


# ---------------------------------------------------------------------------
# Resources written in YAML, and no dashboards at all
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("frontend_loaded", [True, False])
async def test_yaml_resources_load_the_bundle_as_an_extra_module(
    hass: HomeAssistant,
    issue_registry: ir.IssueRegistry,
    frontend_loaded: bool,
) -> None:
    assert await async_setup_component(
        hass,
        "lovelace",
        {
            "lovelace": {
                "resource_mode": "yaml",
                "resources": [{"type": "module", "url": LEGACY_URL}],
            }
        },
    )
    if frontend_loaded:
        hass.config.components.add("frontend")

    with (
        patch.object(cards, "add_extra_js_url") as add_extra,
        patch.object(cards, "remove_extra_js_url") as remove_extra,
    ):
        entry = await install(hass)
        assert await hass.config_entries.async_remove(entry.entry_id)
        await hass.async_block_till_done()

    if frontend_loaded:
        add_extra.assert_called_once_with(hass, URL)
        remove_extra.assert_called_once_with(hass, URL)
    else:
        add_extra.assert_not_called()
        remove_extra.assert_not_called()
    # The YAML stays the user's: nothing written, and the repair raised while
    # the entry existed is gone with it.
    assert resource_urls(hass) == [LEGACY_URL]
    assert issue_registry.async_get_issue(DOMAIN, cards.ISSUE_LEGACY_CARDS) is None


async def test_without_dashboards_or_http_nothing_breaks(
    hass: HomeAssistant,
) -> None:
    entry = await install(hass)

    assert await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()

    assert LOVELACE_DATA not in hass.data


# ---------------------------------------------------------------------------
# The cards never take the router down with them
# ---------------------------------------------------------------------------


async def test_a_failing_resource_registration_does_not_fail_the_entry(
    hass: HomeAssistant,
    hass_storage: dict[str, Any],
    caplog: pytest.LogCaptureFixture,
) -> None:
    assert await async_setup_component(hass, "lovelace", {})
    resources = hass.data[LOVELACE_DATA].resources

    phone = async_mock_service(hass, "notify", "mobile_app_alice")
    with patch.object(
        type(resources), "async_create_item", side_effect=RuntimeError("disk full")
    ):
        entry = await install(hass, ROUTING_TABLE)

    assert entry.state is ConfigEntryState.LOADED
    assert "Could not add the dashboard cards" in caplog.text
    # Not only registered: a message still reaches the person's phone.
    await hass.services.async_call(
        "notify", "switchboard", {"message": "Leak in the kitchen"}, blocking=True
    )
    await hass.async_block_till_done()
    assert [call.data["message"] for call in phone] == ["Leak in the kitchen"]

    # And the next reload, which a broken entry would trip over, works.
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    assert resource_urls(hass) == [URL]


async def test_a_path_already_served_is_reported_not_shadowed(
    hass: HomeAssistant,
    hass_storage: dict[str, Any],
    caplog: pytest.LogCaptureFixture,
    tmp_path: Path,
) -> None:
    """aiohttp keeps the first static resource on a prefix, silently."""
    assert await async_setup_component(hass, "http", {})
    assert await async_setup_component(hass, "lovelace", {})
    await hass.http.async_register_static_paths(
        [StaticPathConfig("/notify_switchboard", str(tmp_path), cache_headers=False)]
    )

    entry = await install(hass)

    assert entry.state is ConfigEntryState.LOADED
    assert hass.services.has_service("notify", "switchboard")
    assert "/notify_switchboard is already served by something else" in caplog.text
    # No resource pointing at a file this integration does not serve.
    assert resource_urls(hass) == []


async def test_a_failing_static_path_does_not_fail_the_setup(
    hass: HomeAssistant,
    hass_storage: dict[str, Any],
    caplog: pytest.LogCaptureFixture,
) -> None:
    assert await async_setup_component(hass, "http", {})
    assert await async_setup_component(hass, "lovelace", {})

    with patch.object(
        hass.http, "async_register_static_paths", side_effect=OSError("boom")
    ):
        entry = await install(hass)

    assert entry.state is ConfigEntryState.LOADED
    assert "Could not serve the dashboard cards" in caplog.text
    # Nothing serves the bundle, so no dashboard is told to load it.
    assert resource_urls(hass) == []
