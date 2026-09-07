"""Acknowledgement authorship — who turned the alert off, in the event and nowhere else.

Written before the Sprint 7 implementation exists, against:

- `docs/contract.md` §"v0.7 addendum (ADR-0021)" → "The `acknowledged` event payload"
- `docs/ADR/0021-escalation-and-places-reduced.md` §4
- `docs/sprints/sprint-7-brief.md` item 4

0.6.0 already knows who acted: `context.user_id` reaches both entry points
(`$HA_CORE_SRC/homeassistant/core.py`, `ServiceCall.context` and
`Context.user_id`) and is already in the `acknowledged` payload. What it throws
away is the `person.*` it resolved in order to decide the action.

`person` is resolved through the canonical link only — the `user_id` state
attribute of a `person.*`
(`$HA_CORE_SRC/homeassistant/components/person/const.py`,
`PersonEntityStateAttribute.USER_ID`), which is contract v0.3's step 1. The
`device_id` fallback is deliberately not used: for an author, a guess derived
from a device name is worse than `null`.

Sprint 7 adds **no entity and no store** for this, which is the other half of
the decision and is pinned below.

The alerts here are never `begin()`-run, so no repeat is ever armed and
`alert.turn_off` — which only sets `_ack` — leaves nothing behind
(`docs/known-issues.md`, 2026-09-07 S1, "two `alert` limitations").
"""

from __future__ import annotations

import pytest
from homeassistant.core import Context
from homeassistant.exceptions import ServiceValidationError

from custom_components.notify_switchboard.const import DOMAIN

from .conftest import make_entry, make_person, make_target


def _person(hass, entity_id: str, *, user_id: str | None = None) -> None:
    attributes = {"user_id": user_id} if user_id else {}
    hass.states.async_set(entity_id, "home", attributes)


def _entry(hass, *, allow_acknowledge: bool = True):
    return make_entry(
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
                allow_acknowledge=allow_acknowledge,
                audience=["person.alice", "person.bob"],
            )
        ],
        default_target="leak",
    )


async def _acknowledge(hass, slug: str, *, user_id: str | None) -> None:
    await hass.services.async_call(
        DOMAIN,
        "acknowledge",
        {"target": slug},
        blocking=True,
        context=Context(user_id=user_id),
    )
    await hass.async_block_till_done()


def _delivery(hass):
    state = hass.states.get("event.switchboard_delivery")
    assert state is not None
    return state.attributes


async def test_the_acknowledged_event_payload_carries_the_user_id_and_the_person(
    hass, enable_custom_integrations, install, mock_outputs, real_alert
):
    """The `acknowledged` event says who, not just what."""
    mock_outputs("mobile_app_alice", "mobile_app_bob")
    _person(hass, "person.alice", user_id="user-alice")
    _person(hass, "person.bob", user_id="user-bob")
    await real_alert("leak")
    await install(_entry(hass))

    await _acknowledge(hass, "leak", user_id="user-alice")

    payload = _delivery(hass)
    assert payload["event_type"] == "acknowledged"
    assert payload["target"] == "leak"
    assert payload["alert_entity"] == "alert.leak"
    assert payload["user_id"] == "user-alice", (
        "`user_id` was already in the payload; v0.7 freezes it (ADR-0021 §4)"
    )
    assert payload["person"] == "person.alice", (
        "`person` joins the frozen `acknowledged` payload in v0.7: the acting "
        "user resolved through the canonical `user_id` state attribute "
        "(contract v0.3 §'Callback resolution order', step 1)"
    )


async def test_the_companion_button_path_carries_the_same_two_keys(
    hass, enable_custom_integrations, install, mock_outputs, real_alert
):
    """One rule, two entry points: the button says who tapped it too."""
    mock_outputs("mobile_app_alice", "mobile_app_bob")
    _person(hass, "person.alice", user_id="user-alice")
    _person(hass, "person.bob", user_id="user-bob")
    await real_alert("leak")
    await install(_entry(hass))

    hass.bus.async_fire(
        "mobile_app_notification_action",
        {"action": "switchboard:ack:leak"},
        context=Context(user_id="user-bob"),
    )
    await hass.async_block_till_done()

    payload = _delivery(hass)
    assert payload["event_type"] == "acknowledged"
    assert payload["user_id"] == "user-bob"
    assert payload["person"] == "person.bob"


async def test_the_person_is_null_when_the_user_id_does_not_resolve(
    hass, enable_custom_integrations, install, mock_outputs, real_alert
):
    """A script's own user, or a person with no linked account: `null`, not a guess."""
    mock_outputs("mobile_app_alice", "mobile_app_bob")
    _person(hass, "person.alice")  # linked to no Home Assistant user
    _person(hass, "person.bob", user_id="user-bob")
    await real_alert("leak")
    await install(_entry(hass))

    await _acknowledge(hass, "leak", user_id="an-automation-account")

    payload = _delivery(hass)
    assert payload["user_id"] == "an-automation-account"
    assert payload["person"] is None, (
        "the `device_id` fallback of contract v0.3 step 2 is not used for "
        "authorship: a guess is worse than `null` (ADR-0021 §4)"
    )


async def test_no_acknowledgements_entity_and_no_new_event_type_are_added(
    hass, enable_custom_integrations, install, mock_outputs, real_alert
):
    """The other half of the decision: authorship lives in the event, and only there.

    `sensor.switchboard_acknowledgements` — a daily count with a `last` record
    and a `by_target` mapping, persisted next to the episodes — was in the
    first draft of this sprint and was cut (ADR-0021 §9). A household that
    wants the history writes a trigger-based template sensor on
    `event.switchboard_delivery`, which is recorder-backed and theirs.
    """
    mock_outputs("mobile_app_alice", "mobile_app_bob")
    _person(hass, "person.alice", user_id="user-alice")
    _person(hass, "person.bob", user_id="user-bob")
    await real_alert("leak")
    await install(_entry(hass))

    await _acknowledge(hass, "leak", user_id="user-alice")

    assert hass.states.get("sensor.switchboard_acknowledgements") is None, (
        "no entity is added for acknowledgement authorship (ADR-0021 §4 and §9)"
    )
    assert set(_delivery(hass)["event_types"]) == {
        "routed",
        "dropped",
        "acknowledged",
        "snoozed",
    }, "the four event types are unchanged"


async def test_a_refused_acknowledgement_reports_no_authorship(
    hass, enable_custom_integrations, install, mock_outputs, real_alert
):
    """The event is of what happened, not of what was attempted."""
    mock_outputs("mobile_app_alice", "mobile_app_bob")
    _person(hass, "person.alice", user_id="user-alice")
    _person(hass, "person.bob", user_id="user-bob")
    await real_alert("leak")
    await install(_entry(hass, allow_acknowledge=False))

    assert hass.services.has_service(DOMAIN, "acknowledge")
    with pytest.raises(ServiceValidationError):
        await _acknowledge(hass, "leak", user_id="user-alice")

    assert _delivery(hass).get("event_type") != "acknowledged", (
        "a refusal fires no `acknowledged` event, so it names no author"
    )
