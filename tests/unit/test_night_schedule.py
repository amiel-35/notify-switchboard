"""Unit tests for the night schedule helper (ADR-0022 §5) and the 0.8 parsing rules."""

from __future__ import annotations

from typing import Any

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers.entity_component import DATA_INSTANCES
from homeassistant.setup import async_setup_component

from custom_components.notify_switchboard import config_flow
from custom_components.notify_switchboard.night_schedule import (
    DAYS,
    LIST_COMMAND,
    WEBSOCKET_DOMAIN,
    async_ensure_night_schedule,
    night_schedule_item,
)
from custom_components.notify_switchboard.validation import (
    derive_slug,
    normalise_wake_time,
)

from .test_config_flow import _create_entry, _options_step, _person_outputs_input


@pytest.fixture
async def cleanup_schedules(hass: HomeAssistant):
    """Remove every schedule entity at teardown, which cancels its timer."""
    yield
    component = hass.data.get(DATA_INSTANCES, {}).get("schedule")
    if component is not None:
        for entity in list(component.entities):
            await component.async_remove_entity(entity.entity_id)
    await hass.async_block_till_done()


def test_the_night_is_two_blocks_every_day() -> None:
    """A schedule block cannot cross midnight, so 22:00-07:00 is two of them."""
    item = night_schedule_item("Bob's night")
    assert item["name"] == "Bob's night"
    for day in DAYS:
        assert item[day] == [
            {"from": "00:00:00", "to": "07:00:00"},
            {"from": "22:00:00", "to": "24:00:00"},
        ]


async def test_a_night_is_created_once_and_then_reused(
    hass: HomeAssistant, cleanup_schedules: None
) -> None:
    first = await async_ensure_night_schedule(hass, "Bob's night")
    second = await async_ensure_night_schedule(hass, "Bob's night")

    assert first is not None
    assert first.startswith("schedule.")
    assert second == first
    assert hass.states.async_entity_ids("schedule") == [first]


async def test_no_collection_means_no_night(
    hass: HomeAssistant, cleanup_schedules: None
) -> None:
    """If core ever moves the collection, the checkbox fails and nothing else."""
    assert await async_setup_component(hass, "schedule", {})
    hass.data[WEBSOCKET_DOMAIN].pop(LIST_COMMAND)

    assert await async_ensure_night_schedule(hass, "Bob's night") is None
    assert hass.states.async_entity_ids("schedule") == []


@pytest.mark.parametrize(
    "registry",
    [None, "not a dict", {LIST_COMMAND: "not a tuple"}, {LIST_COMMAND: (object(),)}],
)
async def test_an_unexpected_registry_shape_means_no_night(
    hass: HomeAssistant, cleanup_schedules: None, registry: Any
) -> None:
    assert await async_setup_component(hass, "schedule", {})
    if registry is None:
        hass.data.pop(WEBSOCKET_DOMAIN)
    else:
        hass.data[WEBSOCKET_DOMAIN] = registry

    assert await async_ensure_night_schedule(hass, "Bob's night") is None


async def test_a_refused_item_creates_nothing(
    hass: HomeAssistant, cleanup_schedules: None
) -> None:
    """The collection validates before it stores: an empty name is refused."""
    assert await async_ensure_night_schedule(hass, "") is None
    assert hass.states.async_entity_ids("schedule") == []


async def test_the_person_screen_says_when_the_night_could_not_be_made(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The error sits on the checkbox, and the person is not saved half-done."""

    async def _fail(_hass: HomeAssistant, _name: str) -> None:
        return None

    monkeypatch.setattr(config_flow, "async_ensure_night_schedule", _fail)
    entry = await _create_entry(hass)

    result = await _options_step(
        hass,
        entry,
        "person",
        {"entity_id": "person.alice"},
        _person_outputs_input(night_schedule=True),
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"night_schedule": "night_schedule_failed"}
    assert entry.options["persons"] == []


@pytest.mark.parametrize(
    ("typed", "stored"),
    [
        ("7:30", "07:30:00"),
        ("7h30", "07:30:00"),
        ("7H", "07:00:00"),
        (" 07 : 05 ", "07:05:00"),
        ("23:59:59", "23:59:59"),
        ("", None),
        (None, None),
        ("7", None),
        ("7:30:00:00", None),
        ("24:00", None),
        ("noon", None),
    ],
)
def test_normalise_wake_time(typed: Any, stored: str | None) -> None:
    assert normalise_wake_time(typed) == stored


@pytest.mark.parametrize(
    ("name", "existing", "slug"),
    [
        ("Water leak", [], "water_leak"),
        ("Fuite d'eau à l'étage", [], "fuite_d_eau_a_l_etage"),
        ("Leak", ["leak"], "leak_2"),
        ("Leak", ["leak", "leak_2"], "leak_3"),
        ("!!!", [], "alert"),
        ("", [], "alert"),
        ("   ", ["alert"], "alert_2"),
    ],
)
def test_derive_slug(name: str, existing: list[str], slug: str) -> None:
    assert derive_slug(name, existing) == slug
