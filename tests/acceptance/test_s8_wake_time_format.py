"""A wake time is typed the way people say it, and stored the way it always was.

Written before the Sprint 8 implementation exists, against:

- `docs/contract.md` §"v0.8 addendum (ADR-0022)" → "`wake_time` without
  seconds"
- `docs/ADR/0022-a-first-alert-without-code.md` §6
- `docs/history/sprints/sprint-8-brief.md` item 6

`TimeSelector` renders `HH:MM:SS` and its 2026.9.1 backend schema accepts no
option to hide the seconds. From 0.8.0 the field is plain text that accepts
`7:30`, and what is stored is still the `"HH:MM:SS"` string the routing-table
entity reports.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from homeassistant.data_entry_flow import FlowResultType

from .conftest import make_entry, make_person, make_target, suggested_value

COMPONENT = (
    Path(__file__).resolve().parents[2] / "custom_components" / "notify_switchboard"
)
FILES = [
    COMPONENT / "strings.json",
    *(COMPONENT / "translations" / f"{lang}.json" for lang in ("en", "fr", "es")),
]


def _household(hass, wake_time: str | None = None):
    return make_entry(
        hass,
        persons=[
            make_person("person.alice", ["mobile_app_alice"], wake_time=wake_time)
        ],
        targets=[make_target("leak", "Leak", audience=["person.alice"])],
        default_target="leak",
    )


async def _night_step(options_flow, entry, *inputs):
    """Open `person_advanced` the 0.8 way: the person screen's checkbox."""
    return await options_flow(
        entry,
        "edit_person",
        {"entity_id": "person.alice"},
        {"outputs": ["mobile_app_alice"], "silence_entities": [], "advanced": True},
        *inputs,
    )


@pytest.mark.parametrize(
    ("typed", "stored"),
    [
        ("7:30", "07:30:00"),
        ("07:30", "07:30:00"),
        ("7h30", "07:30:00"),
        ("7 h 30", "07:30:00"),
        ("07:30:00", "07:30:00"),
        ("23:05", "23:05:00"),
    ],
)
async def test_a_wake_time_without_seconds_is_accepted_and_stored_in_full(
    hass, enable_custom_integrations, install, options_flow, mock_outputs, typed, stored
):
    mock_outputs("mobile_app_alice")
    entry = await install(_household(hass))

    result = await _night_step(options_flow, entry, {"wake_time": typed})

    assert result["type"] is FlowResultType.CREATE_ENTRY, result.get("errors")
    (person,) = entry.options["persons"]
    assert person["wake_time"] == stored, (
        "the stored value keeps the `HH:MM:SS` shape the contract documents"
    )


@pytest.mark.parametrize("typed", ["25:00", "7:75", "seven", "7"])
async def test_an_unreadable_wake_time_is_refused(
    hass, enable_custom_integrations, install, options_flow, mock_outputs, typed
):
    mock_outputs("mobile_app_alice")
    entry = await install(_household(hass))

    result = await _night_step(options_flow, entry, {"wake_time": typed})

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"wake_time": "invalid_time"}


async def test_an_empty_wake_time_is_still_no_wake_time(
    hass, enable_custom_integrations, install, options_flow, mock_outputs
):
    mock_outputs("mobile_app_alice")
    entry = await install(_household(hass, wake_time="07:00:00"))

    result = await _night_step(options_flow, entry, {"wake_time": ""})

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options["persons"][0]["wake_time"] is None


async def test_the_field_opens_on_the_stored_time_without_seconds(
    hass, enable_custom_integrations, install, options_flow, mock_outputs
):
    mock_outputs("mobile_app_alice")
    entry = await install(_household(hass, wake_time="07:30:00"))

    result = await _night_step(options_flow, entry)

    assert result["step_id"] == "person_advanced"
    assert suggested_value(result, "wake_time") == "07:30"


async def test_the_routing_table_still_reports_hh_mm_ss(
    hass, enable_custom_integrations, install, options_flow, mock_outputs
):
    mock_outputs("mobile_app_alice")
    entry = await install(_household(hass))

    await _night_step(options_flow, entry, {"wake_time": "6:45"})
    await hass.async_block_till_done()

    state = hass.states.get("sensor.switchboard_routing_table")
    (person,) = state.attributes["persons"]
    assert person["wake_time"] == "06:45:00"


@pytest.mark.parametrize("file", FILES, ids=lambda path: path.name)
def test_the_help_text_shows_an_example_without_seconds(file: Path):
    steps = json.loads(file.read_text(encoding="utf-8"))["options"]["step"]
    help_text = steps["person_advanced"]["data_description"]["wake_time"]
    assert "7:30" in help_text, f"{file.name}: the help text gives `7:30` as example"
