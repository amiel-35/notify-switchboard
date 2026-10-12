"""Observer mode is on by default, and the YAML block only appears when it is needed.

Written before the Sprint 8 implementation exists, against:

- `docs/contract.md` §"v0.8 addendum (ADR-0022)"
- `docs/ADR/0022-a-first-alert-without-code.md` §2
- `docs/history/sprints/sprint-8-brief.md` item 2

0.7.1 called observer mode "the recommended way" and shipped it off, then
showed an `alert:` block to paste — and a restart to do — after every target,
including the observer ones that need neither. From 0.8.0 a new target starts
in observer mode, and the confirmation only shows YAML when observer mode is
off; otherwise it is one sentence.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import voluptuous as vol
from homeassistant.data_entry_flow import FlowResultType

from .conftest import make_entry, make_person, schema_field

COMPONENT = (
    Path(__file__).resolve().parents[2] / "custom_components" / "notify_switchboard"
)
FILES = [
    COMPONENT / "strings.json",
    *(COMPONENT / "translations" / f"{lang}.json" for lang in ("en", "fr", "es")),
]


def _household(hass):
    return make_entry(
        hass,
        persons=[
            make_person("person.alice", ["mobile_app_alice"]),
            make_person("person.bob", ["mobile_app_bob"]),
        ],
        targets=[],
        default_target=None,
    )


def _default(result, key: str):
    marker, _validator = schema_field(result, key)
    return None if marker.default is vol.UNDEFINED else marker.default()


async def test_a_new_target_starts_in_observer_mode(
    hass, enable_custom_integrations, install, options_flow
):
    """The recommended switch is in the recommended position."""
    entry = await install(_household(hass))

    result = await options_flow(entry, "target")

    assert _default(result, "observer_mode") is True, (
        "`observer_mode` defaults to true on `target` (contract v0.8)"
    )


async def test_observer_mode_on_ends_on_one_sentence_without_yaml(
    hass, enable_custom_integrations, install, options_flow
):
    """"As soon as “Leak” goes off, these people are told: Alice, Bob."""
    hass.states.async_set("person.alice", "home", {"friendly_name": "Alice"})
    hass.states.async_set("person.bob", "home", {"friendly_name": "Bob"})
    entry = await install(_household(hass))

    result = await options_flow(
        entry,
        "target",
        {
            "name": "Leak",
            "alert_entity": "alert.water",
            "audience": ["person.alice", "person.bob"],
        },
    )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "target_ready", (
        "an observer target ends on a confirmation without YAML (ADR-0022 §2)"
    )
    placeholders = result["description_placeholders"] or {}
    assert "snippet" not in placeholders, "no `alert:` block for an observer target"
    assert placeholders.get("name") == "Leak"
    assert "Alice" in placeholders.get("audience", "")
    assert "Bob" in placeholders.get("audience", ""), (
        "the sentence names the people who will be told, by name"
    )

    result = await hass.config_entries.options.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    (row,) = entry.options["targets"]
    assert row["observer_mode"] is True
    assert row["alert_entity"] == "alert.water"


async def test_observer_mode_off_still_shows_the_alert_block(
    hass, enable_custom_integrations, install, options_flow
):
    """Turning the switch off is a choice that needs the YAML, so it gets it."""
    entry = await install(_household(hass))

    result = await options_flow(
        entry,
        "target",
        {
            "name": "Leak",
            "alert_entity": "alert.water",
            "audience": ["person.alice"],
            "observer_mode": False,
        },
    )

    assert result["step_id"] == "target_saved"
    snippet = (result["description_placeholders"] or {}).get("snippet", "")
    assert "alert:" in snippet
    assert "notifiers:" in snippet
    assert "switchboard_leak" in snippet


async def test_an_observer_target_without_an_alert_is_explained_as_a_service(
    hass, enable_custom_integrations, install, options_flow
):
    """Nothing will go off by itself: say it is a service for automations."""
    entry = await install(_household(hass))

    result = await options_flow(
        entry, "target", {"name": "Doorbell", "audience": ["person.alice"]}
    )

    assert result["step_id"] == "target_ready_manual", (
        "observer on and no alert watched: a hint, not a promise (ADR-0022 §2)"
    )
    placeholders = result["description_placeholders"] or {}
    assert placeholders.get("service") == "notify.switchboard_doorbell"
    assert "snippet" not in placeholders


@pytest.mark.parametrize("file", FILES, ids=lambda path: path.name)
def test_the_observer_confirmations_mention_no_yaml_and_no_restart(file: Path):
    """The two observer confirmations are sentences, in every language."""
    steps = json.loads(file.read_text(encoding="utf-8"))["options"]["step"]
    for step_id in ("target_ready", "target_ready_manual"):
        text = steps[step_id]["description"]
        assert "```" not in text, f"{file.name}: {step_id} must not carry YAML"
        assert "{snippet}" not in text
    assert "{audience}" in steps["target_ready"]["description"]
    assert "{name}" in steps["target_ready"]["description"]
    assert "{service}" in steps["target_ready_manual"]["description"]
