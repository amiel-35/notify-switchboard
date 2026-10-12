"""Observer mode does not carry reminders -- and now the screens say so (ADR-0023 §3).

Written before the Sprint 9 implementation exists, against:

- `docs/ADR/0023-one-click-automation-and-a-quiet-all-clear.md` §3
- `docs/history/sprints/sprint-9-brief.md` item 3
- `docs/contract.md` §"Observer mode (plan B, ADR-007)", unchanged

A core alert's `repeat` changes no state: its timer calls `_notify`, which
calls the alert's `notifiers:` and nothing else
(`$HA_CORE_SRC/homeassistant/components/alert/entity.py`). Observer mode reads
state transitions, so it never sees one. The first two tests pin that
behaviour on a real alert, both ways; the others pin that every screen
recommending observer mode says what it does not do, in the three languages.
"""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path
from typing import Any

import homeassistant.util.dt as dt_util
import pytest
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from .conftest import make_entry, make_person, make_target

COMPONENT = (
    Path(__file__).resolve().parents[2] / "custom_components" / "notify_switchboard"
)
SOURCE = "binary_sensor.leak_source"
PHONE = "mobile_app_alice"

# The word each language uses for a reminder, in the help texts.
REMINDER = {"en": "reminder", "fr": "rappel", "es": "recordatorio"}


async def _alert(hass, *, notifiers: list[str]) -> None:
    hass.states.async_set(SOURCE, "off")
    assert await async_setup_component(
        hass,
        "alert",
        {
            "alert": {
                "leak": {
                    "name": "Leak",
                    "entity_id": SOURCE,
                    "state": "on",
                    "repeat": [1],
                    "skip_first": False,
                    "message": "Leak!",
                    "notifiers": notifiers,
                }
            }
        },
    )
    await hass.async_block_till_done()


async def _three_reminders_then_end(hass) -> None:
    hass.states.async_set(SOURCE, "on")
    await hass.async_block_till_done()
    for minutes in (1, 2, 3):
        async_fire_time_changed(
            hass, dt_util.utcnow() + timedelta(minutes=minutes, seconds=5)
        )
        await hass.async_block_till_done()
    hass.states.async_set(SOURCE, "off")
    await hass.async_block_till_done()


def _messages(calls) -> list[str]:
    return [
        call.data["message"]
        for call in calls
        if call.data["message"] != "clear_notification"
    ]


def _entry(hass, *, observer_mode: bool):
    return make_entry(
        hass,
        persons=[make_person("person.alice", [PHONE])],
        targets=[
            make_target(
                "leak",
                "Leak",
                alert_entity="alert.leak",
                audience=["person.alice"],
                observer_mode=observer_mode,
            )
        ],
        default_target="leak",
    )


async def test_observer_mode_routes_the_start_and_the_end_and_no_reminder(
    hass, enable_custom_integrations, install, mock_outputs, set_person
):
    """What observer mode is, and what 0.9 now says on screen."""
    calls = mock_outputs(PHONE)
    set_person("person.alice", "home")
    await _alert(hass, notifiers=[])
    await install(_entry(hass, observer_mode=True))

    await _three_reminders_then_end(hass)

    messages = _messages(calls[PHONE])
    assert len(messages) == 2, (
        "one message when the alert goes off, one when it ends; the alert's "
        f"reminders change no state, so observer mode never sees them: {messages}"
    )


async def test_the_notifiers_path_routes_every_reminder(
    hass, enable_custom_integrations, install, mock_outputs, set_person
):
    """The way the screens recommend for somebody who wants reminders."""
    calls = mock_outputs(PHONE)
    set_person("person.alice", "home")
    await _alert(hass, notifiers=["switchboard_leak"])
    await install(_entry(hass, observer_mode=False))

    await _three_reminders_then_end(hass)

    assert _messages(calls[PHONE]) == ["Leak!"] * 4, (
        "the first message and three reminders, each one routed"
    )


def _steps(language: str) -> dict[str, Any]:
    return json.loads(
        (COMPONENT / "translations" / f"{language}.json").read_text(encoding="utf-8")
    )["options"]["step"]


@pytest.mark.parametrize("language", ["en", "fr", "es"])
def test_the_observer_mode_help_says_it_sends_no_reminders(language):
    """On both screens where the box is ticked or unticked."""
    steps = _steps(language)
    for step_id in ("target", "target_edit"):
        help_text = steps[step_id]["data_description"]["observer_mode"]
        assert REMINDER[language] in help_text.lower(), (
            f"{language}/{step_id}: the help of the recommended box must say "
            "it carries no reminders (ADR-0023 §3)"
        )
        assert "notifiers" in help_text, (
            f"{language}/{step_id}: and name the way that does"
        )


@pytest.mark.parametrize("language", ["en", "fr", "es"])
def test_the_confirmations_say_which_way_carries_reminders(language):
    """`target_ready` (observer on) and `target_saved` (observer off)."""
    steps = _steps(language)
    assert REMINDER[language] in steps["target_ready"]["description"].lower(), (
        f"{language}: the 'nothing else to do' screen says what observer mode "
        "does not do"
    )
    assert REMINDER[language] in steps["target_saved"]["description"].lower(), (
        f"{language}: the `notifiers:` screen says that this way carries them"
    )
