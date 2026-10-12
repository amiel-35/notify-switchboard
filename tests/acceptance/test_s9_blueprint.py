"""One click from "this alert needs an automation" to an automation (ADR-0023 §1).

Written before the Sprint 9 implementation exists, against:

- `docs/contract.md` §"v0.9 addendum (ADR-0023)" → "The blueprint
  `notify_switchboard/alert_from_a_sensor.yaml`"
- `docs/ADR/0023-one-click-automation-and-a-quiet-all-clear.md` §1
- `docs/history/sprints/sprint-9-brief.md` item 1

Home Assistant APIs relied upon (2026.9.1):

- `$HA_CORE_SRC/homeassistant/components/blueprint/models.py`: `Blueprint`
  (validated against a domain's schema) and `DomainBlueprints`, whose
  `_load_blueprints` globs `<config>/blueprints/automation/**/*.yaml` on every
  listing -- which is why a copied file needs no reload;
- `$HA_CORE_SRC/homeassistant/components/automation/config.py`:
  `AUTOMATION_BLUEPRINT_SCHEMA`; `automation/helpers.py`:
  `async_get_blueprints`;
- an automation configured with `use_blueprint: {path, input}`, as the
  frontend's blueprint list creates one.

Every test runs in a configuration directory of its own (`tests/conftest.py`,
`hass_config_dir`), so the file one test installs is never seen by another.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.parse import quote

import pytest
from homeassistant.components.automation.config import AUTOMATION_BLUEPRINT_SCHEMA
from homeassistant.components.automation.helpers import async_get_blueprints
from homeassistant.components.blueprint.models import Blueprint
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.setup import async_setup_component
from homeassistant.util.yaml import load_yaml_dict

from .conftest import make_entry, make_person

COMPONENT = (
    Path(__file__).resolve().parents[2] / "custom_components" / "notify_switchboard"
)
LANGUAGES = ("en", "fr", "es")
FILE_NAME = "alert_from_a_sensor.yaml"
BLUEPRINT_PATH = f"notify_switchboard/{FILE_NAME}"
INPUTS = [
    "trigger_entity",
    "trigger_to",
    "alert_name",
    "message",
    "done_message",
    "priority",
]
RAW_BASE = (
    "https://raw.githubusercontent.com/amiel-35/notify-switchboard/main/"
    "custom_components/notify_switchboard/blueprints"
)
SENSOR = "binary_sensor.doorbell_button"
TABLET = "family_tablet"


def _packaged(language: str) -> Path:
    return COMPONENT / "blueprints" / language / FILE_NAME


def _installed(hass) -> Path:
    return Path(hass.config.path("blueprints", "automation", BLUEPRINT_PATH))


def _load(path: Path) -> Blueprint:
    return Blueprint(
        load_yaml_dict(str(path)),
        expected_domain="automation",
        schema=AUTOMATION_BLUEPRINT_SCHEMA,
    )


def _household(hass):
    return make_entry(
        hass,
        persons=[make_person("person.alice", [TABLET])],
        targets=[],
        default_target=None,
    )


async def _manual_screen(hass, install, options_flow) -> dict[str, Any]:
    """Add "Doorbell", tied to nothing, and stop on its confirmation."""
    entry = await install(_household(hass))
    result = await options_flow(
        entry, "target", {"name": "Doorbell", "audience": ["person.alice"]}
    )
    assert result["step_id"] == "target_ready_manual"
    return result


# ---------------------------------------------------------------------------
# What ships
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_packaged_blueprint_is_a_valid_automation_blueprint(language):
    """Each language file loads with core's own automation blueprint schema."""
    blueprint = _load(_packaged(language))

    assert blueprint.domain == "automation"
    assert list(blueprint.inputs) == INPUTS, (
        "the six inputs are frozen (contract v0.9): automations name them"
    )
    assert blueprint.metadata["source_url"] == f"{RAW_BASE}/{language}/{FILE_NAME}"
    assert "Notify Switchboard" in blueprint.name


def test_the_three_languages_differ_only_in_their_words():
    """Same triggers, conditions, actions, variables, mode and defaults."""
    loaded = {
        language: load_yaml_dict(str(_packaged(language))) for language in LANGUAGES
    }
    reference = loaded["en"]
    for language, data in loaded.items():
        for key in ("triggers", "conditions", "actions", "variables", "mode"):
            assert data.get(key) == reference.get(key), (
                f"{language}: `{key}` must be the English file's, word for word"
            )
        for name in INPUTS:
            ours = data["blueprint"]["input"][name]
            theirs = reference["blueprint"]["input"][name]
            assert ours.get("default") == theirs.get("default"), (language, name)
            if "select" in theirs["selector"]:
                values = [
                    option["value"]
                    for option in theirs["selector"]["select"]["options"]
                ]
                assert [
                    option["value"] for option in ours["selector"]["select"]["options"]
                ] == values, (language, name)
            else:
                assert ours["selector"] == theirs["selector"], (language, name)


def test_the_priority_input_defaults_to_the_alerts_own():
    """`default` sends no `data.priority`, so the target's own applies."""
    data = load_yaml_dict(str(_packaged("en")))
    priority = data["blueprint"]["input"]["priority"]
    assert priority["default"] == "default"
    assert [
        option["value"] for option in priority["selector"]["select"]["options"]
    ] == [
        "default",
        "info",
        "normal",
        "high",
        "critical",
    ]
    assert data["blueprint"]["input"]["trigger_to"]["default"] == "on"


# ---------------------------------------------------------------------------
# The confirmation installs it, once
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("language", LANGUAGES)
async def test_the_manual_confirmation_installs_the_blueprint_in_the_instance_language(
    hass, enable_custom_integrations, install, options_flow, language
):
    """The screen that says "needs an automation" brings the automation's model."""
    hass.config.language = language
    assert not _installed(hass).exists()

    await _manual_screen(hass, install, options_flow)

    assert _installed(hass).read_text(encoding="utf-8") == _packaged(
        language
    ).read_text(encoding="utf-8"), (
        "a copy of the packaged file, in the instance language (ADR-0023 §1)"
    )


async def test_an_unknown_language_gets_the_english_blueprint(
    hass, enable_custom_integrations, install, options_flow
):
    hass.config.language = "de"

    await _manual_screen(hass, install, options_flow)

    assert _installed(hass).read_text(encoding="utf-8") == _packaged("en").read_text(
        encoding="utf-8"
    )


async def test_a_blueprint_already_there_is_never_overwritten(
    hass, enable_custom_integrations, install, options_flow
):
    """From the moment it exists, the file is the user's (ADR-0023 §1)."""
    _installed(hass).parent.mkdir(parents=True, exist_ok=True)
    _installed(hass).write_text("# edited by the household\n", encoding="utf-8")

    result = await _manual_screen(hass, install, options_flow)

    assert _installed(hass).read_text(encoding="utf-8") == (
        "# edited by the household\n"
    )
    assert (
        "/config/blueprint/dashboard" in result["description_placeholders"]["blueprint"]
    ), "the household's file is still the one to open"


async def test_the_other_confirmations_install_nothing(
    hass, enable_custom_integrations, install, options_flow
):
    """Only the screen that ends on "this needs an automation" writes the file."""
    entry = await install(_household(hass))

    result = await options_flow(
        entry,
        "target",
        {
            "name": "Leak",
            "alert_entity": "alert.leak",
            "audience": ["person.alice"],
        },
    )
    assert result["step_id"] == "target_ready"
    assert not _installed(hass).exists()


# ---------------------------------------------------------------------------
# What the screen says
# ---------------------------------------------------------------------------


async def test_the_screen_links_to_the_installed_blueprint_and_names_the_alert(
    hass, enable_custom_integrations, install, options_flow
):
    result = await _manual_screen(hass, install, options_flow)

    placeholders = result["description_placeholders"]
    assert "](/config/blueprint/dashboard)" in placeholders["blueprint"], (
        "a same-host link to the blueprint list, where one click on the row "
        "opens the automation editor on it (ADR-0023 §1)"
    )
    assert placeholders["slug"] == "doorbell", (
        "the automation name to type into the blueprint's `alert_name`"
    )
    assert placeholders["service"] == "notify.switchboard_doorbell", (
        "the manual path stays, as the fallback"
    )
    assert "alert:" in placeholders["snippet"], "and so does the `alert:` block"


async def test_a_failed_copy_falls_back_to_the_import_link(
    hass, enable_custom_integrations, install, options_flow
):
    """A configuration directory the flow cannot write to still gets a link."""
    hass.config.language = "fr"
    blocker = Path(hass.config.path("blueprints", "automation", "notify_switchboard"))
    blocker.parent.mkdir(parents=True, exist_ok=True)
    blocker.write_text("not a directory", encoding="utf-8")

    result = await _manual_screen(hass, install, options_flow)

    link = result["description_placeholders"]["blueprint"]
    assert "https://my.home-assistant.io/redirect/blueprint_import/" in link
    assert quote(f"{RAW_BASE}/fr/{FILE_NAME}", safe="") in link, (
        "the same file, on GitHub, in the instance language"
    )
    assert blocker.read_text(encoding="utf-8") == "not a directory"


@pytest.mark.parametrize("language", LANGUAGES)
def test_every_language_explains_the_blueprint_then_the_manual_way(language):
    """`{blueprint}` and `{slug}` first; `{service}` and `{snippet}` stay."""
    strings = json.loads(
        (COMPONENT / "translations" / f"{language}.json").read_text(encoding="utf-8")
    )
    manual = strings["options"]["step"]["target_ready_manual"]["description"]
    for placeholder in ("{blueprint}", "{slug}", "{service}", "{snippet}"):
        assert placeholder in manual, (language, placeholder)
    assert manual.index("{blueprint}") < manual.index("{snippet}"), (
        "the blueprint is the way; the `alert:` block the other one"
    )

    common = strings["common"]
    name = load_yaml_dict(str(_packaged(language)))["blueprint"]["name"]
    assert name in common["blueprint_ready"], (
        f"{language}: the screen names the blueprint as the list shows it"
    )
    assert "(/config/blueprint/dashboard)" in common["blueprint_ready"]
    assert "{url}" in common["blueprint_import"]


# ---------------------------------------------------------------------------
# And it works: an automation built from the installed blueprint
# ---------------------------------------------------------------------------


async def _automation_from_blueprint(hass, **inputs) -> None:
    assert await async_setup_component(
        hass,
        "automation",
        {
            "automation": [
                {
                    "alias": "Doorbell",
                    "use_blueprint": {"path": BLUEPRINT_PATH, "input": inputs},
                }
            ]
        },
    )
    await hass.async_block_till_done()


async def test_an_automation_from_the_installed_blueprint_sets_the_alert_off(
    hass, enable_custom_integrations, install, options_flow, mock_outputs, set_person
):
    """The sensor goes `on`: the alert's people are told, through the router."""
    calls = mock_outputs(TABLET)
    set_person("person.alice", "home")
    hass.states.async_set(SENSOR, "off", {"friendly_name": "Doorbell button"})
    result = await _manual_screen(hass, install, options_flow)
    result = await hass.config_entries.options.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()

    blueprint = await async_get_blueprints(hass).async_get_blueprint(BLUEPRINT_PATH)
    assert list(blueprint.inputs) == INPUTS

    await _automation_from_blueprint(hass, trigger_entity=SENSOR, alert_name="doorbell")

    hass.states.async_set(SENSOR, "on", {"friendly_name": "Doorbell button"})
    await hass.async_block_till_done()

    (call,) = calls[TABLET]
    assert call.data["message"] == "Doorbell button", (
        "an empty `message` means the sensor's name (contract v0.9)"
    )
    assert call.data["data"]["source_entity"] == SENSOR
    assert "priority" not in call.data["data"], (
        "`priority: default` sends none: the target's own applies"
    )

    hass.states.async_set(SENSOR, "off", {"friendly_name": "Doorbell button"})
    await hass.async_block_till_done()
    assert len(calls[TABLET]) == 1, "no `done_message`: nothing is sent at the end"


async def test_the_blueprints_done_message_is_a_quiet_done_message(
    hass, enable_custom_integrations, install, options_flow, mock_outputs, set_person
):
    """`done_message` set: the end is a `switchboard_done` call, capped."""
    calls = mock_outputs(TABLET)
    set_person("person.alice", "home")
    hass.states.async_set(SENSOR, "off")
    result = await _manual_screen(hass, install, options_flow)
    await hass.config_entries.options.async_configure(result["flow_id"], {})
    await hass.async_block_till_done()

    await _automation_from_blueprint(
        hass,
        trigger_entity=SENSOR,
        alert_name="doorbell",
        message="Somebody at the door",
        done_message="Nobody at the door any more",
        priority="critical",
    )

    hass.states.async_set(SENSOR, "on")
    await hass.async_block_till_done()
    hass.states.async_set(SENSOR, "off")
    await hass.async_block_till_done()

    start, done = calls[TABLET]
    assert start.data["message"] == "Somebody at the door"
    assert start.data["data"]["priority"] == "critical"
    assert done.data["message"] == "Nobody at the door any more"
    assert done.data["data"]["switchboard_done"] is True
    state = hass.states.get("event.switchboard_delivery")
    assert state.attributes.get("priority") == "normal", (
        "a done message never rings louder than `done_priority` (contract v0.9)"
    )


async def test_the_blueprint_ignores_a_sensor_that_drops_off_the_network(
    hass, enable_custom_integrations, install, options_flow, mock_outputs, set_person
):
    """`unavailable` neither sets the alert off nor announces its end."""
    calls = mock_outputs(TABLET)
    set_person("person.alice", "home")
    hass.states.async_set(SENSOR, "on")
    result = await _manual_screen(hass, install, options_flow)
    await hass.config_entries.options.async_configure(result["flow_id"], {})
    await hass.async_block_till_done()
    await _automation_from_blueprint(
        hass,
        trigger_entity=SENSOR,
        alert_name="doorbell",
        done_message="Back to normal",
    )

    for state in ("unavailable", "on", "unknown"):
        hass.states.async_set(SENSOR, state)
        await hass.async_block_till_done()

    assert calls[TABLET] == []
