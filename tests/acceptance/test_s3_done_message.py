"""The `done_message` fallback order, pinned once and for all (ADR-0017 §6).

Written against:

- `docs/contract.md` §"Per-row texts (v0.2, ADR-0016)" and §"v0.3 addendum
  (ADR-0017)" → "Per-row texts: the `done_message` order is the one written
  above"
- `docs/ADR/0017-debts-and-robustness.md` §6
- `docs/sprints/sprint-3-brief.md` item 6

`docs/known-issues.md` (2026-09-07, "the contract and the tests' README order
`done_message` differently") records that four documents describe two
different orders and that no test pins either, because no scenario in the S2
suite has both a row template and an alert attribute at once. Every scenario
below has exactly that, so the order is observable.

The order is the contract's, and it is deliberately not the same as
`message`'s:

| Transition | Order |
|---|---|
| `idle -> on` | alert's `message` attribute -> row's `message` template -> row's `name` |
| `on\\|off -> idle` | row's `done_message` template -> alert's `done_message` attribute -> translated `common.back_to_normal` |

Unlike the other Sprint 3 files, this one is expected to pass against the
0.2.0 implementation: the code already does the right thing and it is two
*documents* that are wrong (`tests/acceptance/README.md` and
`docs/sprints/sprint-2-brief.md`, both corrected by the coding agent). Its
job is to make the order un-drift-able from here on, so nobody "fixes" the
code to match the wrong document.

As in `test_s1_observer.py` and `test_s2_row_texts.py`, the `alert.*` here is
synthetic: a real `AlertEntity` exposes no state attributes at all
(`homeassistant/components/alert/entity.py`), so the attribute branch would
otherwise be untestable.
"""

from __future__ import annotations

import pytest
from homeassistant.helpers import translation

from custom_components.notify_switchboard.const import DOMAIN

from .conftest import make_entry, make_person, make_target

ALERT = "alert.observed"


async def _install_observer_row(
    hass,
    install,
    *,
    message: str | None = None,
    done_message: str | None = None,
):
    """Set up one observer-mode row watching `ALERT`."""
    entry = make_entry(
        hass,
        persons=[make_person("person.alice", ["mobile_app_alice"])],
        targets=[
            make_target(
                "observed",
                "Observed target",
                alert_entity=ALERT,
                observer_mode=True,
                audience=["person.alice"],
                message=message,
                done_message=done_message,
            )
        ],
        default_target="observed",
    )
    return await install(entry)


async def _drive_to_idle(hass, *, attributes: dict | None = None) -> None:
    """Take the observed alert idle -> on -> idle, ending on `attributes`."""
    hass.states.async_set(ALERT, "idle")
    await hass.async_block_till_done()
    hass.states.async_set(ALERT, "on", attributes or {})
    await hass.async_block_till_done()
    hass.states.async_set(ALERT, "idle", attributes or {})
    await hass.async_block_till_done()


async def test_the_rows_done_message_template_wins_over_the_alerts_attribute(
    hass, enable_custom_integrations, install, mock_outputs, set_person
):
    """The one scenario the S2 suite never had: both sources present at once."""
    calls = mock_outputs("mobile_app_alice")
    set_person("person.alice", "home")
    await _install_observer_row(hass, install, done_message="From the row")

    await _drive_to_idle(hass, attributes={"done_message": "From the alert"})

    # idle -> on, then on -> idle: the second message is the done one.
    assert len(calls["mobile_app_alice"]) == 2
    assert calls["mobile_app_alice"][-1].data["message"] == "From the row", (
        "docs/contract.md orders the row's `done_message` template ahead of "
        "the alert's own attribute; ADR-0017 §6 settles it"
    )


async def test_the_alerts_done_message_attribute_is_used_when_the_row_has_none(
    hass, enable_custom_integrations, install, mock_outputs, set_person
):
    """Second in the chain, and still ahead of the translated fallback."""
    calls = mock_outputs("mobile_app_alice")
    set_person("person.alice", "home")
    await _install_observer_row(hass, install)

    await _drive_to_idle(hass, attributes={"done_message": "From the alert"})

    assert calls["mobile_app_alice"][-1].data["message"] == "From the alert"


@pytest.mark.parametrize("language", ["en", "fr"])
async def test_the_translated_back_to_normal_is_the_last_resort(
    hass, enable_custom_integrations, install, mock_outputs, set_person, language
):
    """Neither source: the `common.back_to_normal` string, in the instance language."""
    hass.config.language = language
    calls = mock_outputs("mobile_app_alice")
    set_person("person.alice", "home")
    await _install_observer_row(hass, install)

    await _drive_to_idle(hass)

    strings = await translation.async_get_translations(
        hass, language, "common", {DOMAIN}
    )
    expected = strings[f"component.{DOMAIN}.common.back_to_normal"]
    assert calls["mobile_app_alice"][-1].data["message"] == expected


async def test_the_row_template_is_rendered_with_the_alert_state(
    hass, enable_custom_integrations, install, mock_outputs, set_person
):
    """The template still sees the alert as `alert`, attribute or not."""
    calls = mock_outputs("mobile_app_alice")
    set_person("person.alice", "home")
    await _install_observer_row(
        hass, install, done_message="Cleared, was {{ alert.attributes.level }}"
    )

    await _drive_to_idle(
        hass, attributes={"level": "high", "done_message": "From the alert"}
    )

    assert calls["mobile_app_alice"][-1].data["message"] == "Cleared, was high"


async def test_message_keeps_the_opposite_order(
    hass, enable_custom_integrations, install, mock_outputs, set_person
):
    """The asymmetry is intentional: for `message`, the alert's attribute wins.

    Pinned here next to `done_message` so the two orders are read together and
    nobody "harmonises" them by accident (ADR-0016 §3, ADR-0017 §6).
    """
    calls = mock_outputs("mobile_app_alice")
    set_person("person.alice", "home")
    await _install_observer_row(
        hass, install, message="From the row", done_message="From the row (done)"
    )

    hass.states.async_set(ALERT, "idle")
    await hass.async_block_till_done()
    hass.states.async_set(ALERT, "on", {"message": "From the alert"})
    await hass.async_block_till_done()

    assert calls["mobile_app_alice"][-1].data["message"] == "From the alert"
