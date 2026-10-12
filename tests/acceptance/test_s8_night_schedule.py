""" "Create a night schedule for {person}": a core helper, made once, owned by the user.

Written before the Sprint 8 implementation exists, against:

- `docs/contract.md` §"v0.8 addendum (ADR-0022)" → "`person_outputs` shows two
  checkboxes that store nothing"
- `docs/ADR/0022-a-first-alert-without-code.md` §5
- `docs/history/sprints/sprint-8-brief.md` item 5

Up to 0.7.1 a night had to be built in **Settings → Helpers** before the
person screen could use it. From 0.8.0 one checkbox on that screen creates a
core `schedule` helper, 22:00 to 07:00 every day, and lists it as the person's
silence. The helper is the user's from then on: the router reads it like any
schedule they made by hand, and never edits or deletes it.

What is pinned is what a user can observe — the entity, its weekly blocks, the
person's `silence_entities`, and that it outlives the person and the entry.
How the flow reaches core's schedule collection is ADR-0022 §5's business.
"""

from __future__ import annotations

from typing import Any

import pytest
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers.entity_component import DATA_INSTANCES

from .conftest import make_entry, make_person, make_target, schema_field

DAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")


@pytest.fixture
async def cleanup_schedules(hass):
    """Remove every schedule entity at teardown, which cancels its timer.

    A `Schedule` always arms a timer for its next event and cancels it only
    through the `async_on_remove` its `async_added_to_hass` registers (see
    `schedule_silence` in `conftest.py`).
    """
    yield
    component = hass.data.get(DATA_INSTANCES, {}).get("schedule")
    if component is not None:
        for entity in list(component.entities):
            await component.async_remove_entity(entity.entity_id)
    await hass.async_block_till_done()


def _person(entry, entity_id: str) -> dict[str, Any]:
    return next(
        row for row in entry.options["persons"] if row["entity_id"] == entity_id
    )


def _schedules(hass) -> list[str]:
    return sorted(hass.states.async_entity_ids("schedule"))


async def _weekly_blocks(hass, entity_id: str) -> dict[str, list[tuple[str, str]]]:
    response = await hass.services.async_call(
        "schedule",
        "get_schedule",
        {"entity_id": entity_id},
        blocking=True,
        return_response=True,
    )
    days = response[entity_id]
    return {
        day: [(str(block["from"]), str(block["to"])) for block in days[day]]
        for day in DAYS
    }


async def test_the_person_screen_offers_the_checkbox_off_by_default(
    hass, enable_custom_integrations, install, options_flow, mock_outputs
):
    mock_outputs("mobile_app_alice")
    entry = await install(make_entry(hass, persons=[], targets=[], default_target=None))

    result = await options_flow(entry, "person", {"entity_id": "person.alice"})

    marker, _validator = schema_field(result, "night_schedule")
    assert marker.default() is False, "nothing is created unless asked for"


async def test_ticking_it_creates_the_helper_and_lists_it_as_a_silence(
    hass,
    enable_custom_integrations,
    install,
    options_flow,
    mock_outputs,
    cleanup_schedules,
):
    """One `schedule.*`, 22:00 → 07:00 every day, in `silence_entities`."""
    mock_outputs("mobile_app_alice")
    hass.states.async_set("person.alice", "home", {"friendly_name": "Alice"})
    entry = await install(make_entry(hass, persons=[], targets=[], default_target=None))

    result = await options_flow(
        entry,
        "person",
        {"entity_id": "person.alice"},
        {"outputs": ["mobile_app_alice"], "night_schedule": True},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY

    (schedule,) = _schedules(hass)
    assert _person(entry, "person.alice")["silence_entities"] == [schedule], (
        "the new helper is the person's silence (ADR-0022 §5)"
    )
    assert "night_schedule" not in _person(entry, "person.alice"), (
        "the checkbox is an action, never a stored setting (contract v0.8)"
    )
    state = hass.states.get(schedule)
    assert "Alice" in state.attributes["friendly_name"], (
        "the helper is named after the person, so the user recognises it in "
        "Settings → Helpers"
    )

    blocks = await _weekly_blocks(hass, schedule)
    for day in DAYS:
        assert blocks[day] == [
            ("00:00:00", "07:00:00"),
            ("22:00:00", "23:59:59.999999"),
        ], (
            f"{day}: 22:00 → 07:00, as two blocks because a schedule block "
            f"cannot cross midnight; got {blocks[day]}"
        )


async def test_ticking_it_twice_gives_one_night(
    hass,
    enable_custom_integrations,
    install,
    options_flow,
    mock_outputs,
    cleanup_schedules,
):
    """A helper already named that way is reused, not duplicated."""
    mock_outputs("mobile_app_alice")
    hass.states.async_set("person.alice", "home", {"friendly_name": "Alice"})
    entry = await install(make_entry(hass, persons=[], targets=[], default_target=None))

    for step in ("person", "edit_person"):
        await options_flow(
            entry,
            step,
            {"entity_id": "person.alice"},
            {
                "outputs": ["mobile_app_alice"],
                "silence_entities": list(
                    _person(entry, "person.alice")["silence_entities"]
                )
                if entry.options["persons"]
                else [],
                "night_schedule": True,
            },
        )

    assert len(_schedules(hass)) == 1
    assert _person(entry, "person.alice")["silence_entities"] == _schedules(hass), (
        "the same helper, listed once"
    )


async def test_the_helper_belongs_to_the_user(
    hass,
    enable_custom_integrations,
    install,
    options_flow,
    mock_outputs,
    cleanup_schedules,
):
    """Removing the person, then the whole entry, leaves the helper where it is."""
    mock_outputs("mobile_app_alice", "mobile_app_bob")
    hass.states.async_set("person.alice", "home", {"friendly_name": "Alice"})
    entry = await install(
        make_entry(
            hass,
            persons=[make_person("person.bob", ["mobile_app_bob"])],
            targets=[make_target("leak", "Leak", audience=["person.bob"])],
            default_target="leak",
        )
    )
    await options_flow(
        entry,
        "person",
        {"entity_id": "person.alice"},
        {"outputs": ["mobile_app_alice"], "night_schedule": True},
    )
    (schedule,) = _schedules(hass)

    await options_flow(
        entry, "remove_person", {"entity_id": "person.alice"}, {"confirm": True}
    )
    await hass.async_block_till_done()
    assert hass.states.get(schedule) is not None, (
        "removing the person does not remove a helper the user owns"
    )

    assert await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get(schedule) is not None, (
        "deleting the router entry leaves the helper (ADR-0022 §5)"
    )


async def test_an_invalid_person_screen_creates_nothing(
    hass,
    enable_custom_integrations,
    install,
    options_flow,
    mock_outputs,
    cleanup_schedules,
):
    """The helper is made only when the person is actually saved."""
    entry = await install(make_entry(hass, persons=[], targets=[], default_target=None))

    result = await options_flow(
        entry,
        "person",
        {"entity_id": "person.alice"},
        {"outputs": [], "night_schedule": True},
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"outputs": "no_outputs"}
    assert _schedules(hass) == []
