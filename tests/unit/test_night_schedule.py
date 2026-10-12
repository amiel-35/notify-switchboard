"""Unit tests for the night schedule helper (ADR-0022 §5) and the 0.8 parsing rules."""

from __future__ import annotations

from typing import Any

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers.entity_component import DATA_INSTANCES
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_mock_service

from custom_components.notify_switchboard import config_flow
from custom_components.notify_switchboard.night_schedule import (
    DAYS,
    LIST_COMMAND,
    WEBSOCKET_DOMAIN,
    async_ensure_night_schedule,
    night_schedule_item,
)
from custom_components.notify_switchboard.store import (
    DeferredMessage,
    Episode,
    SwitchboardStore,
)
from custom_components.notify_switchboard.validation import (
    derive_slug,
    normalise_wake_time,
)

from .test_config_flow import (
    _add_person,
    _add_target,
    _create_entry,
    _open_person_advanced,
    _options_step,
    _person_outputs_input,
    suggested_value,
)


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

    async def _fail(_hass: HomeAssistant, _name: str, _taken: Any = None) -> None:
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


# ---------------------------------------------------------------------------
# Review round on 0.8.0: no orphan helper, no shared helper, no lost seconds,
# no inherited state
# ---------------------------------------------------------------------------


def _schedules(hass: HomeAssistant) -> list[str]:
    return sorted(hass.states.async_entity_ids("schedule"))


async def test_closing_the_night_screen_leaves_no_helper_behind(
    hass: HomeAssistant, cleanup_schedules: None
) -> None:
    """Night + advanced ticked, then the dialog closed: nothing exists."""
    entry = await _create_entry(hass)

    result = await _options_step(
        hass,
        entry,
        "person",
        {"entity_id": "person.alice"},
        _person_outputs_input(night_schedule=True, advanced=True),
    )
    assert result["step_id"] == "person_advanced"
    assert _schedules(hass) == [], "nothing is created before the last step"

    hass.config_entries.options.async_abort(result["flow_id"])
    await hass.async_block_till_done()
    assert _schedules(hass) == []
    assert entry.options["persons"] == []


async def test_the_night_is_created_when_the_last_screen_is_submitted(
    hass: HomeAssistant, cleanup_schedules: None
) -> None:
    entry = await _create_entry(hass)

    result = await _options_step(
        hass,
        entry,
        "person",
        {"entity_id": "person.alice"},
        _person_outputs_input(night_schedule=True, advanced=True),
        {"wake_time": "7:00"},
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    (schedule,) = _schedules(hass)
    (person,) = entry.options["persons"]
    assert person["silence_entities"] == [schedule]
    assert person["wake_time"] == "07:00:00"


async def test_two_people_with_the_same_name_get_two_nights(
    hass: HomeAssistant, cleanup_schedules: None
) -> None:
    """A helper that is somebody else's silence is never shared."""
    hass.states.async_set("person.bob_senior", "home", {"friendly_name": "Bob"})
    hass.states.async_set("person.bob_junior", "home", {"friendly_name": "Bob"})
    entry = await _create_entry(hass)

    for person in ("person.bob_senior", "person.bob_junior"):
        await _options_step(
            hass,
            entry,
            "person",
            {"entity_id": person},
            _person_outputs_input(night_schedule=True),
        )

    nights = {
        row["entity_id"]: row["silence_entities"] for row in entry.options["persons"]
    }
    assert len(_schedules(hass)) == 2
    assert nights["person.bob_senior"] != nights["person.bob_junior"]
    names = sorted(
        hass.states.get(entity_id).attributes["friendly_name"]
        for entity_id in _schedules(hass)
    )
    assert names == ["Bob's night", "Bob's night 2"]


async def test_a_schedule_of_that_name_with_other_hours_is_not_reused(
    hass: HomeAssistant, cleanup_schedules: None
) -> None:
    """The user's own "Bob's night", 23:00-06:00, is left alone."""
    assert await async_setup_component(hass, "schedule", {})
    collection = hass.data[WEBSOCKET_DOMAIN][LIST_COMMAND][0].__self__
    await collection.storage_collection.async_create_item(
        {"name": "Bob's night", "monday": [{"from": "23:00:00", "to": "24:00:00"}]}
    )
    await hass.async_block_till_done()
    (own,) = _schedules(hass)

    night = await async_ensure_night_schedule(hass, "Bob's night")

    assert night is not None and night != own
    assert hass.states.get(night).attributes["friendly_name"] == "Bob's night 2"


async def test_a_wake_time_with_seconds_is_shown_and_kept(
    hass: HomeAssistant,
) -> None:
    """A 0.7 value `07:30:15` is neither rounded on screen nor on save."""
    entry = await _create_entry(hass)
    await _options_step(
        hass,
        entry,
        "person",
        {"entity_id": "person.alice"},
        _person_outputs_input(advanced=True),
        {"wake_time": "07:30:15"},
    )
    assert entry.options["persons"][0]["wake_time"] == "07:30:15"

    form = await _open_person_advanced(hass, entry, "person.alice")
    assert suggested_value(form, "wake_time") == "07:30:15"
    await hass.config_entries.options.async_configure(
        form["flow_id"], {"wake_time": suggested_value(form, "wake_time")}
    )
    await hass.async_block_till_done()
    assert entry.options["persons"][0]["wake_time"] == "07:30:15"


async def test_a_re_created_target_does_not_inherit_the_old_ones_state(
    hass: HomeAssistant,
) -> None:
    """Remove "Leak", add "Leak" again: same slug, no stale snooze or episode."""
    async_mock_service(hass, "notify", "mobile_app_alice")
    hass.states.async_set("person.alice", "home")
    entry = await _create_entry(hass)
    await _add_person(hass, entry)
    await _add_target(hass, entry)
    await hass.services.async_call(
        "notify_switchboard",
        "snooze",
        {"target": "leak", "minutes": 15},
        blocking=True,
    )
    store = entry.runtime_data.switchboard.store
    assert ("person.alice", "leak") in store.snoozes
    store.episodes["leak"] = Episode(slug="leak", persons={"person.alice"})
    await store.async_save()

    await _options_step(
        hass, entry, "remove_target", {"slug": "leak"}, {"confirm": True}
    )
    await _add_target(hass, entry)

    store = entry.runtime_data.switchboard.store
    assert [row["slug"] for row in entry.options["targets"]].count("leak") == 1
    assert ("person.alice", "leak") not in store.snoozes
    assert "leak" not in store.episodes


def test_the_store_purges_every_kind_of_state_of_an_unknown_slug() -> None:
    store = SwitchboardStore.__new__(SwitchboardStore)
    now = dt_util.utcnow()
    store.snoozes = {("person.a", "gone"): now, ("person.a", "kept"): now}
    store.deferrals = {
        ("person.a", "gone", "t"): DeferredMessage(
            person="person.a",
            slug="gone",
            tag="t",
            message="m",
            title=None,
            data={},
            priority="normal",
            queued_at=now,
        ),
    }
    store.episodes = {"gone": Episode(slug="gone"), "kept": Episode(slug="kept")}

    assert store.purge_unknown_slugs({"kept"}) is True
    assert list(store.snoozes) == [("person.a", "kept")]
    assert store.deferrals == {}
    assert list(store.episodes) == ["kept"]
    assert store.purge_unknown_slugs({"kept"}) is False


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
