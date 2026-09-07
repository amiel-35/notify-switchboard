"""The target editor in two steps: five fields, then everything else.

Written before the Sprint 6 implementation exists, against:

- `docs/contract.md` §"v0.6 addendum (ADR-0020)" → "Four options-flow step ids
  are public"
- `docs/ADR/0020-consolidation.md` §1
- `docs/sprints/sprint-6-brief.md` item 1

Up to 0.5.1 the first form somebody meets when they create a target asks for
fifteen things at once, twelve of which have a default that is right for
almost everybody. From 0.6.0 the `target` step asks for exactly five — the
identity of the target, the alert it is about, the people it is for, and
whether the router watches that alert itself — and a second step,
`target_advanced`, holds the rest with the same selectors and the same
defaults.

Two properties matter more than the split itself, and each has a test of its
own below:

- a target created through the basic step alone must be **the row 0.5 wrote**
  for the same five answers (minus `class`, ADR-0020 §4), and must route the
  same way;
- opening the advanced step must not be able to reset a basic value. That is
  the 0.2.0 data-loss bug (`docs/known-issues.md`, "the options flow edits one
  row at a time") re-introduced by a split, and it is the first thing a
  careless implementation does.
"""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.data_entry_flow import FlowResultType

from .conftest import (
    make_entry,
    make_person,
    make_target,
    schema_field,
    suggested_value,
)

# ADR-0020 §1: the five, in the order the form shows them.
BASIC_FIELDS = ["slug", "name", "alert_entity", "audience", "observer_mode"]

# ADR-0020 §1: everything else, with the defaults 0.5.1 already used.
ADVANCED_FIELDS = [
    "default_priority",
    "presence_rule",
    "allow_acknowledge",
    "snooze_minutes",
    "default_data",
    "message",
    "done_message",
    "default_title",
    "clear_done",
]
ADVANCED_DEFAULTS = {
    "default_priority": "normal",
    "presence_rule": "always",
    "allow_acknowledge": False,
    "snooze_minutes": "",
    "default_data": {},
    "clear_done": False,
}


def _field_names(result) -> list[str]:
    """Return the keys of a flow step's schema, in declaration order."""
    return [str(marker) for marker in result["data_schema"].schema]


def _default(result, key: str) -> Any:
    """Return the default declared for one field, or None when it has none."""
    marker, _validator = schema_field(result, key)
    default = marker.default
    if default is vol.UNDEFINED:
        return None
    return default()


def _row(entry, slug: str) -> dict[str, Any]:
    """Return one target of the stored options."""
    rows = [row for row in entry.options["targets"] if row["slug"] == slug]
    assert rows, (
        f"no target {slug!r}; got {[row['slug'] for row in entry.options['targets']]}"
    )
    return rows[0]


def _household(hass, *, targets: list[dict[str, Any]] | None = None):
    return make_entry(
        hass,
        persons=[
            make_person("person.alice", ["mobile_app_alice"]),
            make_person("person.bob", ["mobile_app_bob"]),
        ],
        targets=targets if targets is not None else [],
        default_target=targets[0]["slug"] if targets else None,
    )


# ---------------------------------------------------------------------------
# The shape of the two steps
# ---------------------------------------------------------------------------


async def test_the_target_step_asks_exactly_five_things(
    hass, enable_custom_integrations, install, options_flow
):
    """Five fields, that is all: the whole point of the release (ADR-0020 §1)."""
    entry = await install(_household(hass))

    result = await options_flow(entry, "target")

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "target", (
        "`target` is a public step id (contract v0.6): documents link to it"
    )
    assert _field_names(result) == BASIC_FIELDS, (
        "the first form a newcomer meets asks for the identity of the target, "
        "the alert, the audience and observer mode — and nothing else "
        "(ADR-0020 §1)"
    )


async def test_target_advanced_holds_everything_else_with_unchanged_defaults(
    hass, enable_custom_integrations, install, options_flow
):
    """The nine fields that left the basic form, with the selectors they had."""
    entry = await install(
        _household(
            hass,
            targets=[
                make_target("leak", "Leak", audience=["person.alice"]),
            ],
        )
    )

    result = await options_flow(entry, "edit_target_advanced", {"slug": "leak"})

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "target_advanced", (
        "`target_advanced` is a public step id (contract v0.6), reached from "
        "the 'Advanced settings of a target' menu entry (ADR-0020 §1)"
    )
    assert _field_names(result) == ADVANCED_FIELDS
    for key, expected in ADVANCED_DEFAULTS.items():
        assert _default(result, key) == expected, (
            f"the default of {key!r} is what 0.5.1 already used: moving a "
            "field between steps must not change what it means"
        )
    assert _default(result, "message") is None, (
        "an absent per-target text stays absent (contract v0.2): an empty "
        "template is not the same as no template"
    )
    assert suggested_value(result, "default_priority") == "normal", (
        "the advanced step opens on the stored target, like every other editor "
        "since 0.2.0"
    )


# ---------------------------------------------------------------------------
# A target created through the basic step alone
# ---------------------------------------------------------------------------


async def test_a_target_created_through_the_basic_step_is_the_0_5_row(
    hass, enable_custom_integrations, install, options_flow
):
    """Same five answers, same stored row — minus `class` (ADR-0020 §4)."""
    entry = await install(_household(hass))

    result = await options_flow(
        entry,
        "target",
        {
            "slug": "leak",
            "name": "Leak",
            "alert_entity": "alert.water",
            "audience": ["person.alice", "person.bob"],
            "observer_mode": True,
        },
        {},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY, (
        "`target_saved` still follows the basic step and is still what writes "
        "the row (ADR-0018 §7, kept by ADR-0020 §1)"
    )

    assert _row(entry, "leak") == make_target(
        "leak",
        "Leak",
        alert_entity="alert.water",
        audience=["person.alice", "person.bob"],
        observer_mode=True,
    ), (
        "the five basic answers plus the documented defaults are exactly the "
        "row 0.5 wrote; a split that changes the stored shape is not a split"
    )


async def test_a_basic_target_routes_exactly_as_a_0_5_target_with_defaults(
    hass, enable_custom_integrations, install, options_flow, mock_outputs, set_person
):
    """Stated as a delivery rather than as options: `normal`, `always`, no buttons."""
    calls = mock_outputs("mobile_app_alice", "mobile_app_bob")
    set_person("person.alice", "home")
    set_person("person.bob", "not_home")
    entry = await install(_household(hass))

    await options_flow(
        entry,
        "target",
        {
            "slug": "leak",
            "name": "Leak",
            "audience": ["person.alice", "person.bob"],
            "observer_mode": False,
        },
        {},
    )

    await hass.services.async_call(
        "notify", "switchboard_leak", {"message": "water"}, blocking=True
    )
    await hass.async_block_till_done()

    assert [call.data["message"] for call in calls["mobile_app_alice"]] == ["water"]
    assert [call.data["message"] for call in calls["mobile_app_bob"]] == ["water"], (
        "the default presence rule is `always`, so somebody away is notified "
        "too — unchanged by the split (ADR-0020 §1)"
    )
    payload = calls["mobile_app_alice"][0].data["data"]
    assert "actions" not in payload, (
        "no alert and no snooze durations means no buttons, exactly as a 0.5 "
        "target created with defaults"
    )


# ---------------------------------------------------------------------------
# The split must not lose anything
# ---------------------------------------------------------------------------


async def test_editing_through_advanced_keeps_the_basic_values(
    hass, enable_custom_integrations, install, options_flow
):
    """Changing the priority of a target must not be able to empty its audience."""
    entry = await install(
        _household(
            hass,
            targets=[
                make_target(
                    "leak",
                    "Leak",
                    alert_entity="alert.water",
                    audience=["person.alice", "person.bob"],
                    observer_mode=True,
                )
            ],
        )
    )

    result = await options_flow(
        entry,
        "edit_target_advanced",
        {"slug": "leak"},
        {
            "default_priority": "high",
            "presence_rule": "home_only",
            "allow_acknowledge": True,
            "snooze_minutes": "15, 60",
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY

    row = _row(entry, "leak")
    assert row["default_priority"] == "high"
    assert row["presence_rule"] == "home_only"
    assert row["allow_acknowledge"] is True
    assert row["snooze_minutes"] == [15, 60], (
        "`snooze_minutes` is still typed as comma-separated text and stored as "
        "a list of integers; only the step it lives in moved"
    )

    assert row["name"] == "Leak"
    assert row["alert_entity"] == "alert.water"
    assert row["audience"] == ["person.alice", "person.bob"]
    assert row["observer_mode"] is True, (
        "the advanced step writes its own nine fields and touches none of the "
        "five (ADR-0020 §1) — resetting them is the 0.2.0 data-loss bug"
    )
