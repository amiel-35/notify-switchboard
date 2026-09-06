"""Shared fixtures and options-shape builders for the Notify Switchboard acceptance suite.

The options shape built by `make_person` / `make_target` / `make_entry` below is
NORMATIVE — see ../../README.md. The implementation's config flow / options flow
must read `entry.options` in exactly this shape.

Only three names are imported from the integration itself: `DOMAIN`,
`ATTR_PRIORITY` and `ATTR_SOURCE_ENTITY` (frozen contract names, see
docs/notify-switchboard-contract-v0.md). Every other key used below is a plain
string literal defined by this test suite, not a constant owned by the
implementation.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_mock_service,
)

from custom_components.notify_switchboard.const import (  # noqa: F401  (import-cleanliness check)
    ATTR_PRIORITY,
    ATTR_SOURCE_ENTITY,
    DOMAIN,
)

DEFAULT_ENTRY_ID = "ns_acceptance_entry"
DEFAULT_TITLE = "Notify Switchboard (acceptance)"


# ---------------------------------------------------------------------------
# Options-shape builders (see README.md "Options shape")
# ---------------------------------------------------------------------------


def make_person(
    entity_id: str,
    outputs: list[str],
    *,
    silence_entities: list[str] | None = None,
    wake_time: str | None = None,
) -> dict[str, Any]:
    """Build one row of `entry.options["persons"]`."""
    return {
        "entity_id": entity_id,
        "outputs": list(outputs),
        "silence_entities": list(silence_entities or []),
        "wake_time": wake_time,
    }


def make_target(
    slug: str,
    name: str,
    *,
    klass: str = "test",
    default_priority: str = "normal",
    alert_entity: str | None = None,
    audience: list[str] | None = None,
    presence_rule: str = "always",
    allow_acknowledge: bool = False,
    snooze_minutes: list[int] | None = None,
    default_data: dict[str, Any] | None = None,
    observer_mode: bool = False,
    message: str | None = None,
    done_message: str | None = None,
    default_title: str | None = None,
) -> dict[str, Any]:
    """Build one row of `entry.options["targets"]` (the routing table).

    `message`, `done_message` and `default_title` are the v0.2 addendum
    (ADR-0016, `docs/contract.md` "Per-row texts"): optional per-row texts,
    `None` by default so every Sprint 1 target keeps building the exact same
    row it always has.
    """
    return {
        "slug": slug,
        "name": name,
        "class": klass,
        "default_priority": default_priority,
        "alert_entity": alert_entity,
        "audience": list(audience or []),
        "presence_rule": presence_rule,
        "allow_acknowledge": allow_acknowledge,
        "snooze_minutes": list(snooze_minutes or []),
        "default_data": dict(default_data or {}),
        "observer_mode": observer_mode,
        "message": message,
        "done_message": done_message,
        "default_title": default_title,
    }


def make_options(
    *,
    persons: list[dict[str, Any]],
    targets: list[dict[str, Any]],
    default_target: str,
) -> dict[str, Any]:
    """Build the full `entry.options` dict."""
    return {
        "persons": persons,
        "targets": targets,
        "default_target": default_target,
    }


def make_entry(
    hass,
    *,
    persons: list[dict[str, Any]],
    targets: list[dict[str, Any]],
    default_target: str,
    entry_id: str = DEFAULT_ENTRY_ID,
) -> MockConfigEntry:
    """Create and register (add_to_hass) a MockConfigEntry with the given options."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id=entry_id,
        title=DEFAULT_TITLE,
        version=1,
        minor_version=1,
        options=make_options(
            persons=persons, targets=targets, default_target=default_target
        ),
    )
    entry.add_to_hass(hass)
    return entry


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def install(hass) -> Callable[[MockConfigEntry], Any]:
    """Return an async helper that sets up a MockConfigEntry and drains the loop."""

    async def _install(entry: MockConfigEntry) -> MockConfigEntry:
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        return entry

    return _install


@pytest.fixture
def mock_outputs(hass) -> Callable[..., dict[str, list]]:
    """Register fake `notify.<name>` services and return their captured-calls lists.

    Usage: calls = mock_outputs("mobile_app_alice", "mobile_app_bob")
           calls["mobile_app_alice"] -> list[ServiceCall]
    """

    def _mock(*names: str, raise_exception: Exception | None = None) -> dict[str, list]:
        return {
            name: async_mock_service(
                hass, "notify", name, raise_exception=raise_exception
            )
            for name in names
        }

    return _mock


@pytest.fixture
def set_person(hass) -> Callable[[str, str], None]:
    """Set a `person.*` entity's state (home / not_home / anything else)."""

    def _set(entity_id: str, state: str) -> None:
        hass.states.async_set(entity_id, state)

    return _set


@pytest.fixture
def dropped_sensor(hass):
    """Return the current `sensor.switchboard_dropped_today` state object."""

    def _get():
        return hass.states.get("sensor.switchboard_dropped_today")

    return _get


@pytest.fixture
def routed_sensor(hass):
    """Return the current `sensor.switchboard_routed_today` state object."""

    def _get():
        return hass.states.get("sensor.switchboard_routed_today")

    return _get
