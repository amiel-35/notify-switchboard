"""Acknowledgement authorship — who turned the alert off, and when.

Written before the Sprint 6 implementation exists, against:

- `docs/contract.md` §"v0.6 addendum (ADR-0020)" → "Acknowledgement records"
  and "The `acknowledged` event payload"
- `docs/ADR/0020-bounded-declarative-escalation.md` §4
- `docs/sprints/sprint-6-brief.md` item 4

0.5.0 already knows who acted: `context.user_id` reaches both entry points
(`$HA_CORE_SRC/homeassistant/core.py`, `ServiceCall.context` and
`Context.user_id`), and the Companion path resolves it to a `person.*` in order
to decide a snooze. It simply throws that away — the `acknowledged` event
carries the raw `user_id`, nothing carries the `person`, and no entity answers
"who acknowledged the leak?".

`person` is resolved through the canonical link only — the `user_id` state
attribute of a `person.*`
(`$HA_CORE_SRC/homeassistant/components/person/const.py`,
`PersonEntityStateAttribute.USER_ID`), which is contract v0.3's step 1. The
`device_id` fallback is deliberately not used: for an author, a guess derived
from a device name is worse than `null`.

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

RECORD_KEYS = frozenset({"target", "person", "user_id", "at"})


def _person(hass, entity_id: str, *, user_id: str | None = None) -> None:
    attributes = {"user_id": user_id} if user_id else {}
    hass.states.async_set(entity_id, "home", attributes)


def _entry(hass, *, allow_acknowledge: bool = True, slugs: tuple[str, ...] = ("leak",)):
    return make_entry(
        hass,
        persons=[
            make_person("person.alice", ["mobile_app_alice"]),
            make_person("person.bob", ["mobile_app_bob"]),
        ],
        targets=[
            make_target(
                slug,
                slug.title(),
                alert_entity=f"alert.{slug}",
                allow_acknowledge=allow_acknowledge,
                audience=["person.alice", "person.bob"],
            )
            for slug in slugs
        ],
        default_target=slugs[0],
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


async def test_the_entity_counts_todays_acknowledgements_and_names_the_last_one(
    hass,
    enable_custom_integrations,
    install,
    mock_outputs,
    real_alert,
    acknowledgements_sensor,
):
    """`sensor.switchboard_acknowledgements`: a count, and the record behind it."""
    mock_outputs("mobile_app_alice", "mobile_app_bob")
    _person(hass, "person.alice", user_id="user-alice")
    _person(hass, "person.bob", user_id="user-bob")
    await real_alert("leak")
    await install(_entry(hass))

    state = acknowledgements_sensor()
    assert state is not None, (
        "`sensor.switchboard_acknowledgements` is a frozen public name "
        "(contract v0.6, ADR-0020 §4)"
    )
    assert state.state == "0"

    await _acknowledge(hass, "leak", user_id="user-alice")

    state = acknowledgements_sensor()
    assert state.state == "1", "the state is the number of records since local midnight"
    record = state.attributes["last"]
    assert set(record) == RECORD_KEYS, (
        f"a record is exactly {sorted(RECORD_KEYS)}; got {sorted(record)}"
    )
    assert record["target"] == "leak"
    assert record["user_id"] == "user-alice"
    assert record["person"] == "person.alice", (
        "the acting user is resolved to a `person.*` through the canonical "
        "`user_id` state attribute (contract v0.3 §'Callback resolution order')"
    )
    assert record["at"], "`at` is an ISO 8601 instant and is always populated"


async def test_by_target_keeps_the_last_record_of_each_row(
    hass,
    enable_custom_integrations,
    install,
    mock_outputs,
    real_alert,
    acknowledgements_sensor,
):
    """One entry per row, always the most recent — which is what a card reads."""
    mock_outputs("mobile_app_alice", "mobile_app_bob")
    _person(hass, "person.alice", user_id="user-alice")
    _person(hass, "person.bob", user_id="user-bob")
    await real_alert("leak")
    await real_alert("garage")
    await install(_entry(hass, slugs=("leak", "garage")))

    await _acknowledge(hass, "leak", user_id="user-alice")
    await _acknowledge(hass, "garage", user_id="user-alice")
    await _acknowledge(hass, "leak", user_id="user-bob")

    state = acknowledgements_sensor()
    assert state.state == "3"
    by_target = state.attributes["by_target"]
    assert set(by_target) == {"leak", "garage"}
    assert by_target["leak"]["person"] == "person.bob", (
        "the second acknowledgement of a row replaces the first"
    )
    assert by_target["garage"]["person"] == "person.alice"
    assert state.attributes["last"]["target"] == "leak"


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

    event_state = hass.states.get("event.switchboard_delivery")
    assert event_state.attributes["event_type"] == "acknowledged"
    assert event_state.attributes["target"] == "leak"
    assert event_state.attributes["alert_entity"] == "alert.leak"
    assert event_state.attributes["user_id"] == "user-alice"
    assert event_state.attributes["person"] == "person.alice", (
        "`person` joins the frozen `acknowledged` payload in v0.6 (ADR-0020 §4)"
    )


async def test_the_person_is_null_when_the_user_id_does_not_resolve(
    hass,
    enable_custom_integrations,
    install,
    mock_outputs,
    real_alert,
    acknowledgements_sensor,
):
    """A script's own user, or a person with no linked account: `null`, not a guess."""
    mock_outputs("mobile_app_alice", "mobile_app_bob")
    _person(hass, "person.alice")  # linked to no Home Assistant user
    _person(hass, "person.bob", user_id="user-bob")
    await real_alert("leak")
    await install(_entry(hass))

    await _acknowledge(hass, "leak", user_id="an-automation-account")

    record = acknowledgements_sensor().attributes["last"]
    assert record["user_id"] == "an-automation-account"
    assert record["person"] is None, (
        "the `device_id` fallback of contract v0.3 step 2 is not used for "
        "authorship: a guess is worse than `null` (ADR-0020 §4)"
    )


async def test_the_records_survive_a_reload(
    hass,
    hass_storage,
    enable_custom_integrations,
    install,
    mock_outputs,
    real_alert,
    acknowledgements_sensor,
):
    """ "Who acknowledged the leak?" must not be forgotten by a restart.

    The config entry is unloaded and set up again on the same `hass_storage`,
    the same stand-in for a restart `test_s1_persistence.py` uses for snoozes
    and `test_s5_episode.py` for episode recipients.
    """
    mock_outputs("mobile_app_alice", "mobile_app_bob")
    _person(hass, "person.alice", user_id="user-alice")
    _person(hass, "person.bob", user_id="user-bob")
    await real_alert("leak")
    entry = await install(_entry(hass))

    await _acknowledge(hass, "leak", user_id="user-alice")
    before = acknowledgements_sensor().attributes["last"]

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    state = acknowledgements_sensor()
    assert state.state == "1", "the day's count is restored, not restarted"
    assert state.attributes["last"] == before
    assert state.attributes["by_target"]["leak"] == before


async def test_a_refused_acknowledgement_records_nothing(
    hass,
    enable_custom_integrations,
    install,
    mock_outputs,
    real_alert,
    acknowledgements_sensor,
):
    """The record is of what happened, not of what was attempted."""
    mock_outputs("mobile_app_alice", "mobile_app_bob")
    _person(hass, "person.alice", user_id="user-alice")
    _person(hass, "person.bob", user_id="user-bob")
    await real_alert("leak")
    await install(_entry(hass, allow_acknowledge=False))

    assert hass.services.has_service(DOMAIN, "acknowledge")
    with pytest.raises(ServiceValidationError):
        await _acknowledge(hass, "leak", user_id="user-alice")

    state = acknowledgements_sensor()
    assert state.state == "0"
    assert state.attributes["last"] is None
    assert state.attributes["by_target"] == {}
