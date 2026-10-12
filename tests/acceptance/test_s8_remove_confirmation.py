"""A removal says what will be lost, and asks before doing it.

Written before the Sprint 8 implementation exists, against:

- `docs/ADR/0022-a-first-alert-without-code.md` §4
- `docs/history/sprints/sprint-8-brief.md` item 4

Up to 0.7.1, picking somebody in "Remove somebody" and pressing Submit removed
them from the people of the house and from every target's audience, in one
click and without a word about it. From 0.8.0 the picker leads to a
confirmation that names what will be lost and that needs a ticked "Yes,
remove".
"""

from __future__ import annotations

from typing import Any

from homeassistant.data_entry_flow import FlowResultType

from .conftest import make_entry, make_person, make_target


def _household(hass):
    hass.states.async_set("person.alice", "home", {"friendly_name": "Alice"})
    hass.states.async_set("person.bob", "home", {"friendly_name": "Bob"})
    return make_entry(
        hass,
        persons=[
            make_person("person.alice", ["mobile_app_alice"]),
            make_person("person.bob", ["mobile_app_bob"]),
        ],
        targets=[
            make_target(
                "leak", "Water leak", audience=["person.alice", "person.bob"]
            ),
            make_target("gate", "Gate left open", audience=["person.alice"]),
            make_target("mail", "Mail", audience=["person.bob"]),
        ],
        default_target="leak",
    )


def _persons(entry) -> list[str]:
    return [row["entity_id"] for row in entry.options["persons"]]


def _slugs(entry) -> list[str]:
    return [row["slug"] for row in entry.options["targets"]]


def _audience(entry, slug: str) -> list[str]:
    row: dict[str, Any] = next(
        row for row in entry.options["targets"] if row["slug"] == slug
    )
    return list(row["audience"])


async def test_removing_somebody_first_says_which_alerts_they_lose(
    hass, enable_custom_integrations, install, options_flow
):
    """"Alice will no longer be told by: Water leak, Gate left open"."""
    entry = await install(_household(hass))

    result = await options_flow(entry, "remove_person", {"entity_id": "person.alice"})

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "remove_person_confirm"
    placeholders = result["description_placeholders"] or {}
    assert placeholders.get("person") == "Alice"
    assert "Water leak" in placeholders.get("targets", "")
    assert "Gate left open" in placeholders.get("targets", "")
    assert "Mail" not in placeholders.get("targets", ""), (
        "only the alerts that tell this person are listed"
    )
    assert _persons(entry) == ["person.alice", "person.bob"], (
        "nothing is removed by picking"
    )


async def test_an_unticked_confirmation_removes_nobody(
    hass, enable_custom_integrations, install, options_flow
):
    """Pressing Submit without ticking "Yes, remove" is refused, not obeyed."""
    entry = await install(_household(hass))

    result = await options_flow(
        entry, "remove_person", {"entity_id": "person.alice"}, {"confirm": False}
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"confirm": "not_confirmed"}
    assert _persons(entry) == ["person.alice", "person.bob"]
    assert _audience(entry, "leak") == ["person.alice", "person.bob"]


async def test_a_ticked_confirmation_removes_them_everywhere(
    hass, enable_custom_integrations, install, options_flow
):
    """…exactly as 0.7.1 did in one click."""
    entry = await install(_household(hass))

    result = await options_flow(
        entry, "remove_person", {"entity_id": "person.alice"}, {"confirm": True}
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert _persons(entry) == ["person.bob"]
    assert _audience(entry, "leak") == ["person.bob"]
    assert _audience(entry, "gate") == []


async def test_removing_an_alert_first_says_who_stops_being_told(
    hass, enable_custom_integrations, install, options_flow
):
    """The people it tells, and the service that will stop doing anything."""
    entry = await install(_household(hass))

    result = await options_flow(entry, "remove_target", {"slug": "leak"})

    assert result["step_id"] == "remove_target_confirm"
    placeholders = result["description_placeholders"] or {}
    assert placeholders.get("target") == "Water leak"
    assert "Alice" in placeholders.get("persons", "")
    assert "Bob" in placeholders.get("persons", "")
    assert placeholders.get("service") == "notify.switchboard_leak"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"confirm": False}
    )
    assert result["errors"] == {"confirm": "not_confirmed"}
    assert "leak" in _slugs(entry)

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"confirm": True}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert _slugs(entry) == ["gate", "mail"]
