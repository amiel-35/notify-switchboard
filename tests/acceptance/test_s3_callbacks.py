"""Companion callback resolution and the `person_without_user_id` repair.

Written before the Sprint 3 implementation exists, against:

- `docs/contract.md` §"v0.3 addendum (ADR-0017)" → "Callback resolution order"
- `docs/ADR/0017-debts-and-robustness.md` §4
- `docs/sprints/sprint-3-brief.md` item 4

`person.user_id` is the canonical link. `mobile_app` re-fires a Companion
action with the registration's own context
(`homeassistant/components/mobile_app/webhook.py`, `webhook_fire_event`,
`context=registration_context(config_entry.data)`, which is
`Context(user_id=...)` — `mobile_app/helpers.py`), and `person` publishes the
linked user as a state attribute
(`homeassistant/components/person/__init__.py`,
`PersonEntityStateAttribute.USER_ID`). The `device_id` path stays only as a
fallback: it has never been observed on a real device
(`docs/known-issues.md`), so it must not be reached when the exact link
resolves.

Because that exact link only exists when the user has connected their
`person.*` to a Home Assistant account, a person who is in the audience of a
row that adds Companion buttons but has no `user_id` raises a repair rather
than silently degrading to the "act on the whole audience" fallback.

Nothing here pins an `issue_id` string — the contract does not fix one, the
same way `test_s1_routing.py` does not pin the `unknown_target` one. What is
pinned is the `translation_key`, the severity, the fixability, *how many*
issues are raised, and which person each one names.
"""

from __future__ import annotations

import homeassistant.helpers.issue_registry as ir
import pytest
from homeassistant.core import Context
from homeassistant.helpers import device_registry as dr, translation
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_mock_service,
)

from custom_components.notify_switchboard.const import DOMAIN

from .conftest import make_entry, make_person, make_target

REPAIR_TRANSLATION_KEY = "person_without_user_id"

ACTION_EVENT = "mobile_app_notification_action"


def _set_person(hass, entity_id: str, state: str, user_id: str | None = None) -> None:
    """Set a `person.*` state, with or without the `user_id` link attribute."""
    attributes = {"user_id": user_id} if user_id is not None else {}
    hass.states.async_set(entity_id, state, attributes)


def _repairs(hass) -> list[ir.IssueEntry]:
    """Return this integration's `person_without_user_id` issues."""
    registry = ir.async_get(hass)
    return [
        issue
        for (domain, _issue_id), issue in registry.issues.items()
        if domain == DOMAIN and issue.translation_key == REPAIR_TRANSLATION_KEY
    ]


def _subject(issue: ir.IssueEntry) -> str:
    """Return everything an issue says about *who* it is about."""
    return f"{issue.issue_id} {issue.translation_placeholders or {}}"


# ---------------------------------------------------------------------------
# `context.user_id` is the canonical link
# ---------------------------------------------------------------------------


async def test_user_id_resolves_the_acting_person_without_any_device_id(
    hass, enable_custom_integrations, install, mock_outputs
):
    """No `device_id` at all: the linked person is still resolved exactly."""
    mock_outputs("mobile_app_alice", "mobile_app_bob")
    _set_person(hass, "person.alice", "home", user_id="user-alice")
    _set_person(hass, "person.bob", "home", user_id="user-bob")

    entry = make_entry(
        hass,
        persons=[
            make_person("person.alice", ["mobile_app_alice"]),
            make_person("person.bob", ["mobile_app_bob"]),
        ],
        targets=[
            make_target(
                "leak",
                "Leak",
                audience=["person.alice", "person.bob"],
                snooze_minutes=[15],
            )
        ],
        default_target="leak",
    )
    await install(entry)

    hass.bus.async_fire(
        ACTION_EVENT,
        {"action": "switchboard:snooze:leak:15"},
        context=Context(user_id="user-alice"),
    )
    await hass.async_block_till_done()

    assert hass.states.get("sensor.alice_active_snoozes").state == "1"
    assert hass.states.get("sensor.bob_active_snoozes").state == "0", (
        "the audience fallback must not be reached when `user_id` resolves"
    )


async def test_user_id_wins_over_a_device_id_pointing_at_somebody_else(
    hass, enable_custom_integrations, install, mock_outputs
):
    """A registered device belonging to another person does not override `user_id`.

    The `device_id` path is a fallback (ADR-0017 §4), not a competing source
    of truth: it has never been verified against a real Companion device.
    """
    mock_outputs("mobile_app_alice", "mobile_app_bob_phone")
    _set_person(hass, "person.alice", "home", user_id="user-alice")
    _set_person(hass, "person.bob", "home", user_id="user-bob")

    # A real device-registry entry whose name resolves to bob's output.
    companion_entry = MockConfigEntry(domain="mobile_app", entry_id="companion_bob")
    companion_entry.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=companion_entry.entry_id,
        identifiers={("mobile_app", "bob-registration")},
        name="bob phone",
    )

    entry = make_entry(
        hass,
        persons=[
            make_person("person.alice", ["mobile_app_alice"]),
            make_person("person.bob", ["mobile_app_bob_phone"]),
        ],
        targets=[
            make_target(
                "leak",
                "Leak",
                audience=["person.alice", "person.bob"],
                snooze_minutes=[15],
            )
        ],
        default_target="leak",
    )
    await install(entry)

    hass.bus.async_fire(
        ACTION_EVENT,
        {"action": "switchboard:snooze:leak:15", "device_id": device.id},
        context=Context(user_id="user-alice"),
    )
    await hass.async_block_till_done()

    assert hass.states.get("sensor.alice_active_snoozes").state == "1"
    assert hass.states.get("sensor.bob_active_snoozes").state == "0", (
        "the device_id fallback overrode the canonical person.user_id link"
    )


async def test_acknowledge_from_a_linked_person_is_attributed_to_that_user(
    hass, enable_custom_integrations, install, mock_outputs
):
    """The `acknowledged` event still carries the acting `user_id` (ADR-0009)."""
    mock_outputs("mobile_app_alice")
    # A synthetic `alert.*`, as `test_s1_observer.py` uses: what matters here
    # is who the router credits the acknowledgement to, not the real alert
    # component's own state machine.
    turn_off = async_mock_service(hass, "alert", "turn_off")
    _set_person(hass, "person.alice", "home", user_id="user-alice")
    hass.states.async_set("alert.leak", "on")

    entry = make_entry(
        hass,
        persons=[make_person("person.alice", ["mobile_app_alice"])],
        targets=[
            make_target(
                "leak",
                "Leak",
                alert_entity="alert.leak",
                audience=["person.alice"],
                allow_acknowledge=True,
            )
        ],
        default_target="leak",
    )
    await install(entry)

    hass.bus.async_fire(
        ACTION_EVENT,
        {"action": "switchboard:ack:leak"},
        context=Context(user_id="user-alice"),
    )
    await hass.async_block_till_done()

    assert len(turn_off) == 1
    assert turn_off[0].data["entity_id"] == "alert.leak"
    event_state = hass.states.get("event.switchboard_delivery")
    assert event_state.attributes["event_type"] == "acknowledged"
    assert event_state.attributes["user_id"] == "user-alice"


# ---------------------------------------------------------------------------
# The `person_without_user_id` repair
# ---------------------------------------------------------------------------


async def test_a_person_without_user_id_in_a_row_with_buttons_raises_one_repair(
    hass, enable_custom_integrations, install, mock_outputs
):
    """One issue, for the one person who cannot be resolved, and only that one."""
    mock_outputs("mobile_app_alice", "mobile_app_bob")
    _set_person(hass, "person.alice", "home")  # not linked to any user
    _set_person(hass, "person.bob", "home", user_id="user-bob")

    entry = make_entry(
        hass,
        persons=[
            make_person("person.alice", ["mobile_app_alice"]),
            make_person("person.bob", ["mobile_app_bob"]),
        ],
        targets=[
            make_target(
                "leak",
                "Leak",
                alert_entity="alert.leak",
                audience=["person.alice", "person.bob"],
                allow_acknowledge=True,
            )
        ],
        default_target="leak",
    )
    await install(entry)

    issues = _repairs(hass)
    assert len(issues) == 1, (
        "exactly one repair, for the one person in a button-bearing row who "
        f"has no user_id; got {[_subject(issue) for issue in issues]}"
    )
    issue = issues[0]
    assert "alice" in _subject(issue), (
        f"the repair must name the person it is about; got {_subject(issue)}"
    )
    assert issue.severity is ir.IssueSeverity.WARNING
    assert issue.is_fixable is False, (
        "nothing this integration can do fixes it: the link is made in "
        "Settings > People"
    )


async def test_one_repair_per_unlinked_person(
    hass, enable_custom_integrations, install, mock_outputs
):
    """ "Once per person", not once per row and not one aggregate issue."""
    mock_outputs("mobile_app_alice", "mobile_app_bob")
    _set_person(hass, "person.alice", "home")
    _set_person(hass, "person.bob", "home")

    entry = make_entry(
        hass,
        persons=[
            make_person("person.alice", ["mobile_app_alice"]),
            make_person("person.bob", ["mobile_app_bob"]),
        ],
        targets=[
            make_target(
                "leak",
                "Leak",
                audience=["person.alice", "person.bob"],
                snooze_minutes=[15, 60],
            ),
            make_target(
                "garage",
                "Garage",
                audience=["person.alice", "person.bob"],
                snooze_minutes=[15],
            ),
        ],
        default_target="leak",
    )
    await install(entry)

    issues = _repairs(hass)
    assert len(issues) == 2, (
        "two unlinked persons across two button-bearing rows must give two "
        f"repairs, not one per (person, row); got {len(issues)}"
    )
    subjects = " ".join(_subject(issue) for issue in issues)
    assert "alice" in subjects and "bob" in subjects


async def test_no_repair_when_the_rows_add_no_companion_buttons(
    hass, enable_custom_integrations, install, mock_outputs
):
    """Without buttons there is no callback to resolve, so nothing to warn about."""
    mock_outputs("mobile_app_alice")
    _set_person(hass, "person.alice", "home")

    entry = make_entry(
        hass,
        persons=[make_person("person.alice", ["mobile_app_alice"])],
        targets=[
            make_target(
                "leak",
                "Leak",
                audience=["person.alice"],
                allow_acknowledge=False,
                snooze_minutes=[],
            )
        ],
        default_target="leak",
    )
    await install(entry)

    assert _repairs(hass) == []


async def test_no_repair_for_a_person_who_is_linked(
    hass, enable_custom_integrations, install, mock_outputs
):
    """The nominal case raises nothing."""
    mock_outputs("mobile_app_alice")
    _set_person(hass, "person.alice", "home", user_id="user-alice")

    entry = make_entry(
        hass,
        persons=[make_person("person.alice", ["mobile_app_alice"])],
        targets=[
            make_target("leak", "Leak", audience=["person.alice"], snooze_minutes=[15])
        ],
        default_target="leak",
    )
    await install(entry)

    assert _repairs(hass) == []


async def test_linking_the_person_and_reloading_removes_the_repair(
    hass, enable_custom_integrations, install, mock_outputs
):
    """A `repairs` issue outlives the process that raised it; a reload clears it."""
    mock_outputs("mobile_app_alice")
    _set_person(hass, "person.alice", "home")

    entry = make_entry(
        hass,
        persons=[make_person("person.alice", ["mobile_app_alice"])],
        targets=[
            make_target("leak", "Leak", audience=["person.alice"], snooze_minutes=[15])
        ],
        default_target="leak",
    )
    await install(entry)
    assert len(_repairs(hass)) == 1

    _set_person(hass, "person.alice", "home", user_id="user-alice")
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()

    assert _repairs(hass) == [], (
        "the repair must be deleted once the condition that raised it is gone"
    )


@pytest.mark.parametrize("language", ["en", "fr", "es"])
async def test_the_repair_is_translated(
    hass, enable_custom_integrations, install, mock_outputs, language
):
    """`strings.json` and all three translation files carry the issue text."""
    mock_outputs("mobile_app_alice")
    _set_person(hass, "person.alice", "home")

    entry = make_entry(
        hass,
        persons=[make_person("person.alice", ["mobile_app_alice"])],
        targets=[
            make_target("leak", "Leak", audience=["person.alice"], snooze_minutes=[15])
        ],
        default_target="leak",
    )
    await install(entry)

    strings = await translation.async_get_translations(
        hass, language, "issues", {DOMAIN}
    )
    prefix = f"component.{DOMAIN}.issues.{REPAIR_TRANSLATION_KEY}"
    for part in ("title", "description"):
        assert strings.get(f"{prefix}.{part}"), (
            f"translations/{language}.json must define {prefix}.{part}"
        )
