"""A menu in three blocks, one entry per thing, titles that match.

Written before the Sprint 8 implementation exists, against:

- `docs/ADR/0022-a-first-alert-without-code.md` §3 and §7
- `docs/history/sprints/sprint-8-brief.md` items 3 and 7

Home Assistant menus are flat — no heading, no separator — so order and
wording carry the grouping: three entries about people, three about alerts,
one "Settings" that opens a second menu. The three "advanced settings of …"
entries leave the menu and are reached from the edit screens by a checkbox.
Every entry is labelled exactly like the screen it opens.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from homeassistant.data_entry_flow import FlowResultType

from .conftest import make_entry, make_person, make_target, selector_options

COMPONENT = (
    Path(__file__).resolve().parents[2] / "custom_components" / "notify_switchboard"
)
FILES = [
    COMPONENT / "strings.json",
    *(COMPONENT / "translations" / f"{lang}.json" for lang in ("en", "fr", "es")),
]

TOP_MENU = [
    "person",
    "edit_person",
    "remove_person",
    "target",
    "edit_target",
    "remove_target",
    "general",
]
SETTINGS_MENU = [
    "default_target",
    "critical_payload",
    "ttl",
    "test_person",
    "test_target",
]
GONE = ["edit_person_advanced", "edit_target_advanced", "edit_target_escalation"]


def _household(hass, **kwargs: Any):
    return make_entry(
        hass,
        persons=[
            make_person(
                "person.alice",
                ["mobile_app_alice"],
                silence_entities=["input_boolean.alice_night"],
            )
        ],
        targets=[
            make_target(
                "leak",
                "Leak",
                alert_entity="alert.water",
                audience=["person.alice"],
                observer_mode=True,
            )
        ],
        default_target="leak",
        **kwargs,
    )


def _row(entry, slug: str) -> dict[str, Any]:
    return next(row for row in entry.options["targets"] if row["slug"] == slug)


# ---------------------------------------------------------------------------
# The two menus
# ---------------------------------------------------------------------------


async def test_the_menu_is_three_blocks_of_one_entry_per_thing(
    hass, enable_custom_integrations, install
):
    """People, alerts, settings — seven entries, in that order."""
    entry = await install(_household(hass))

    result = await hass.config_entries.options.async_init(entry.entry_id)

    assert result["type"] is FlowResultType.MENU
    assert list(result["menu_options"]) == TOP_MENU, (
        "three entries about people, three about alerts, then Settings (ADR-0022 §3)"
    )
    for entry_id in GONE:
        assert entry_id not in result["menu_options"], (
            f"{entry_id!r} left the menu: it is reached from an edit screen"
        )


async def test_settings_is_a_second_menu(hass, enable_custom_integrations, install):
    """Default target, critical push, time to live, and the two tests."""
    entry = await install(_household(hass))

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "general"}
    )

    assert result["type"] is FlowResultType.MENU
    assert result["step_id"] == "general"
    assert list(result["menu_options"]) == SETTINGS_MENU


@pytest.mark.parametrize("file", FILES, ids=lambda path: path.name)
def test_every_menu_entry_is_titled_like_the_screen_it_opens(file: Path):
    """Click "Add an alert", land on "Add an alert" — in every language."""
    steps = json.loads(file.read_text(encoding="utf-8"))["options"]["step"]
    for menu_id, entries in (("init", TOP_MENU), ("general", SETTINGS_MENU)):
        labels = steps[menu_id]["menu_options"]
        assert sorted(labels) == sorted(entries), (
            f"{file.name}: the {menu_id!r} menu labels exactly its entries"
        )
        for entry_id in entries:
            assert labels[entry_id] == steps[entry_id]["title"], (
                f"{file.name}: menu entry {entry_id!r} reads {labels[entry_id]!r} "
                f"but its screen is titled {steps[entry_id]['title']!r} "
                "(ADR-0022 §3)"
            )
    for entry_id in GONE:
        assert entry_id not in steps, f"{file.name}: {entry_id!r} is gone"


# ---------------------------------------------------------------------------
# What the removed entries opened, reached from the edit screens
# ---------------------------------------------------------------------------


async def test_the_target_edit_screen_opens_the_advanced_settings(
    hass, enable_custom_integrations, install, options_flow
):
    """A checkbox on the edit screen replaces "Advanced settings of a target"."""
    entry = await install(_household(hass))

    result = await options_flow(
        entry,
        "edit_target",
        {"slug": "leak"},
        {
            "name": "Leak",
            "alert_entity": "alert.water",
            "audience": ["person.alice"],
            "observer_mode": True,
            "advanced": True,
        },
    )
    assert result["step_id"] == "target_advanced"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"default_priority": "high", "presence_rule": "always"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert _row(entry, "leak")["default_priority"] == "high"
    assert _row(entry, "leak")["audience"] == ["person.alice"]


async def test_the_target_edit_screen_opens_the_empty_house_setting(
    hass, enable_custom_integrations, install, options_flow
):
    """…and another replaces "What happens when the house is empty"."""
    entry = await install(_household(hass))

    result = await options_flow(
        entry,
        "edit_target",
        {"slug": "leak"},
        {
            "name": "Leak",
            "alert_entity": "alert.water",
            "audience": ["person.alice"],
            "observer_mode": True,
            "escalation": True,
        },
    )
    assert result["step_id"] == "target_escalation"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"escalate_when_nobody_home": True}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert _row(entry, "leak")["escalate_when_nobody_home"] is True


async def test_both_boxes_open_both_screens_and_nothing_is_lost(
    hass, enable_custom_integrations, install, options_flow
):
    """Advanced first, then the empty house; one write at the end."""
    entry = await install(_household(hass))

    result = await options_flow(
        entry,
        "edit_target",
        {"slug": "leak"},
        {
            "name": "Water leak",
            "alert_entity": "alert.water",
            "audience": ["person.alice"],
            "observer_mode": True,
            "advanced": True,
            "escalation": True,
        },
        {"default_priority": "high", "presence_rule": "always"},
    )
    assert result["step_id"] == "target_escalation"
    assert _row(entry, "leak")["name"] == "Leak", "nothing is written mid-chain"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"escalate_when_nobody_home": True}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    row = _row(entry, "leak")
    assert row["name"] == "Water leak"
    assert row["default_priority"] == "high"
    assert row["escalate_when_nobody_home"] is True


async def test_the_person_screen_opens_the_night_settings(
    hass, enable_custom_integrations, install, options_flow, mock_outputs
):
    """A checkbox on `person_outputs` replaces "Set up somebody's night"."""
    mock_outputs("mobile_app_alice")
    entry = await install(_household(hass))

    result = await options_flow(
        entry,
        "edit_person",
        {"entity_id": "person.alice"},
        {
            "outputs": ["mobile_app_alice"],
            "silence_entities": ["input_boolean.alice_night"],
            "advanced": True,
        },
    )
    assert result["step_id"] == "person_advanced"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"wake_time": "07:00", "summary": False}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    (person,) = entry.options["persons"]
    assert person["wake_time"] == "07:00:00"
    assert person["summary"] is False
    assert "advanced" not in person, "a checkbox that opens a screen stores nothing"


async def test_critical_payload_has_a_screen_of_its_own(
    hass, enable_custom_integrations, install, options_flow
):
    """Moved out of the default-target screen; same option, same default."""
    entry = await install(_household(hass))

    result = await options_flow(entry, "critical_payload", {"critical_payload": False})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options["critical_payload"] is False

    result = await options_flow(entry, "critical_payload", {"critical_payload": True})
    assert "critical_payload" not in entry.options, (
        "written only when off, exactly as in 0.7 (ADR-0021 §7)"
    )


async def test_the_default_target_has_a_screen_of_its_own(
    hass, enable_custom_integrations, install, options_flow
):
    """The form `general` used to be, without the critical switch."""
    entry = await install(_household(hass))
    await options_flow(
        entry, "target", {"name": "Gate", "audience": ["person.alice"]}, {}
    )

    form = await options_flow(entry, "default_target")
    assert [str(marker) for marker in form["data_schema"].schema] == ["default_target"]
    await options_flow(entry, "default_target", {"default_target": "gate"})
    assert entry.options["default_target"] == "gate"


# ---------------------------------------------------------------------------
# Item 7: a person is understood from one line
# ---------------------------------------------------------------------------


async def test_the_person_pickers_describe_a_person_in_one_line(
    hass, enable_custom_integrations, install, options_flow, mobile_app_registration
):
    """ "Alice — Alice's iPhone, quiet: Alice's night"."""
    mobile_app_registration("Alice's iPhone", user_id="user-alice")
    hass.states.async_set(
        "input_boolean.alice_night", "off", {"friendly_name": "Alice's night"}
    )
    hass.states.async_set(
        "person.alice", "home", {"friendly_name": "Alice", "user_id": "user-alice"}
    )
    entry = await install(
        make_entry(
            hass,
            persons=[
                make_person(
                    "person.alice",
                    ["mobile_app_alice_s_iphone"],
                    silence_entities=["input_boolean.alice_night"],
                ),
                make_person("person.bob", []),
            ],
            targets=[],
            default_target=None,
        )
    )

    for step in ("edit_person", "remove_person"):
        form = await options_flow(entry, step)
        labels = {
            option["value"]: option["label"]
            for option in selector_options(form, "entity_id")
        }
        assert labels["person.alice"].startswith("Alice — "), labels
        assert "Alice's iPhone" in labels["person.alice"], (
            "the phone is named the way its owner named it"
        )
        assert "Alice's night" in labels["person.alice"], (
            "the silence is named by its friendly name"
        )
        assert labels["person.bob"].startswith("Bob — "), labels
