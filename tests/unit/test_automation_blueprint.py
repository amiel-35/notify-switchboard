"""Unit tests for the 0.9 additions: the shipped blueprint and the alert's done call.

The behaviour is pinned end to end by `tests/acceptance/test_s9_*.py`; these
cover the branches the acceptance suite cannot reach cheaply -- a copy that
races another writer, a copy that fails half-way, a language with a region, an
alert component that is not loaded -- and run in the unit job CI measures.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import patch
from urllib.parse import quote

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_mock_service,
)

from custom_components.notify_switchboard import automation_blueprint
from custom_components.notify_switchboard.automation_blueprint import (
    BLUEPRINT_FILE,
    InstallResult,
    _copy,
    async_install_blueprint,
    blueprint_language,
    import_url,
    installed_blueprint,
    packaged_blueprint,
)
from custom_components.notify_switchboard.const import DOMAIN
from custom_components.notify_switchboard.store import DeferredMessage

# ---------------------------------------------------------------------------
# The blueprint file
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("language", "expected"),
    [
        ("fr", "fr"),
        ("fr-CA", "fr"),
        ("es-419", "es"),
        ("en-GB", "en"),
        ("pt-BR", "en"),
        ("de", "en"),
        ("", "en"),
        (None, "en"),
    ],
)
def test_blueprint_language(language: str | None, expected: str) -> None:
    """A region is dropped; a language with no file of its own gets English."""
    assert blueprint_language(language) == expected


def test_every_packaged_language_exists() -> None:
    for language in automation_blueprint.BLUEPRINT_LANGUAGES:
        assert packaged_blueprint(language).is_file(), language


def test_import_url_points_at_the_language_file_on_github() -> None:
    url = import_url("es")
    assert url.startswith("https://my.home-assistant.io/redirect/blueprint_import/")
    source = (
        "https://raw.githubusercontent.com/amiel-35/notify-switchboard/v0.9.0/"
        f"custom_components/notify_switchboard/blueprints/es/{BLUEPRINT_FILE}"
    )
    assert url.endswith(f"?blueprint_url={quote(source, safe='')}")


def test_copy_installs_then_leaves_the_file_alone(tmp_path: Path) -> None:
    destination = tmp_path / "blueprints" / "automation" / DOMAIN / BLUEPRINT_FILE
    source = packaged_blueprint("en")

    assert _copy(source, destination) is InstallResult.INSTALLED
    assert destination.read_bytes() == source.read_bytes()

    destination.write_text("# mine\n", encoding="utf-8")
    assert _copy(source, destination) is InstallResult.PRESENT
    assert destination.read_text(encoding="utf-8") == "# mine\n"


def test_copy_never_replaces_a_file_that_appeared_meanwhile(tmp_path: Path) -> None:
    """`exists()` said no, then somebody wrote it: the exclusive open says yes."""
    destination = tmp_path / BLUEPRINT_FILE
    destination.write_text("# written in between\n", encoding="utf-8")

    with patch.object(Path, "exists", return_value=False):
        result = _copy(packaged_blueprint("en"), destination)

    assert result is InstallResult.PRESENT
    assert destination.read_text(encoding="utf-8") == "# written in between\n"


def test_a_failed_copy_leaves_nothing_behind(tmp_path: Path) -> None:
    """A half-written file would read as "present" for ever after."""
    destination = tmp_path / BLUEPRINT_FILE

    assert _copy(tmp_path / "missing.yaml", destination) is InstallResult.FAILED
    assert not destination.exists()


def test_a_folder_that_cannot_be_made_fails_cleanly(tmp_path: Path) -> None:
    blocker = tmp_path / "blueprints"
    blocker.write_text("a file, not a folder", encoding="utf-8")

    result = _copy(packaged_blueprint("en"), blocker / "automation" / BLUEPRINT_FILE)

    assert result is InstallResult.FAILED
    assert blocker.read_text(encoding="utf-8") == "a file, not a folder"


async def test_async_install_uses_the_instance_language(hass: HomeAssistant) -> None:
    hass.config.language = "fr"

    assert await async_install_blueprint(hass) is InstallResult.INSTALLED
    assert await async_install_blueprint(hass) is InstallResult.PRESENT
    assert installed_blueprint(hass).read_bytes() == (
        packaged_blueprint("fr").read_bytes()
    )


# ---------------------------------------------------------------------------
# The options flow falls back to the import link
# ---------------------------------------------------------------------------


async def _entry(hass: HomeAssistant, targets: list[dict[str, Any]]) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id="ns_unit_entry",
        title="Notify Switchboard",
        version=1,
        minor_version=1,
        options={
            "persons": [
                {
                    "entity_id": "person.alice",
                    "outputs": ["mobile_app_alice"],
                    "silence_entities": [],
                    "wake_time": None,
                }
            ],
            "targets": targets,
            "default_target": targets[0]["slug"] if targets else None,
        },
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_the_manual_screen_falls_back_to_the_import_link(
    hass: HomeAssistant,
) -> None:
    async_mock_service(hass, "notify", "mobile_app_alice")
    entry = await _entry(hass, [])
    hass.config.language = "es"

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "target"}
    )
    with patch(
        "custom_components.notify_switchboard.config_flow.async_install_blueprint",
        return_value=InstallResult.FAILED,
    ):
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {"name": "Doorbell", "audience": ["person.alice"]}
        )

    assert result["step_id"] == "target_ready_manual"
    sentence = result["description_placeholders"]["blueprint"]
    assert import_url("es") in sentence
    assert "{url}" not in sentence
    assert result["description_placeholders"]["slug"] == "doorbell"


# ---------------------------------------------------------------------------
# The done call of a Home Assistant alert
# ---------------------------------------------------------------------------


def _target(alert_entity: str | None) -> dict[str, Any]:
    return {
        "slug": "leak",
        "name": "Leak",
        "default_priority": "critical",
        "alert_entity": alert_entity,
        "audience": ["person.alice"],
        "presence_rule": "always",
        "allow_acknowledge": False,
        "snooze_minutes": [],
        "default_data": {},
        "observer_mode": False,
    }


async def test_alert_is_ending_needs_the_alert_component(hass: HomeAssistant) -> None:
    """A synthetic `alert.*` state with no `alert` integration is never ending."""
    entry = await _entry(hass, [_target("alert.leak")])
    switchboard = entry.runtime_data.switchboard
    hass.states.async_set("alert.leak", "on")

    assert switchboard.alert_is_ending("alert.leak") is False


async def test_alert_is_ending_reads_the_live_entity(hass: HomeAssistant) -> None:
    """Stored `on`/`off` and a live `idle`: that is the instant, and only it."""
    hass.states.async_set("binary_sensor.source", "off")
    assert await async_setup_component(
        hass,
        "alert",
        {
            "alert": {
                "leak": {
                    "name": "Leak",
                    "entity_id": "binary_sensor.source",
                    "state": "on",
                    "repeat": [60],
                    "notifiers": [],
                }
            }
        },
    )
    await hass.async_block_till_done()
    entry = await _entry(hass, [_target("alert.leak")])
    switchboard = entry.runtime_data.switchboard

    # The real alert is idle and stored idle: between two episodes.
    assert switchboard.alert_is_ending("alert.leak") is False
    # The stored state still says `on` (or `off`, acknowledged) while the live
    # entity -- not firing -- says `idle`: what `end_alerting` looks like from
    # inside its done-message await.
    for stored in ("on", "off"):
        hass.states.async_set("alert.leak", stored)
        assert switchboard.alert_is_ending("alert.leak") is True
    # A state the `alert` component does not own.
    hass.states.async_set("alert.other", "on")
    assert switchboard.alert_is_ending("alert.other") is False
    hass.states.async_set("alert.leak", "idle")


def test_a_deferred_done_message_round_trips_its_flag() -> None:
    """Written only when true; absent reads as false (ADR-0023 §2.5)."""
    done = DeferredMessage(person="person.alice", slug="leak", tag="t", message="m")
    assert "done" not in done.as_dict()

    flagged = DeferredMessage(
        person="person.alice", slug="leak", tag="t", message="m", done=True
    )
    raw = flagged.as_dict()
    assert raw["done"] is True
    restored = DeferredMessage.from_dict(raw)
    assert restored is not None
    assert restored.done is True
    assert DeferredMessage.from_dict(done.as_dict()).done is False  # type: ignore[union-attr]


async def test_a_suspected_end_is_confirmed_only_by_a_stored_idle(
    hass: HomeAssistant,
) -> None:
    """ADR-0023 §2.2, amended: the suspicion, then the proof after one yield."""
    hass.states.async_set("binary_sensor.source", "off")
    assert await async_setup_component(
        hass,
        "alert",
        {
            "alert": {
                "leak": {
                    "name": "Leak",
                    "entity_id": "binary_sensor.source",
                    "state": "on",
                    "repeat": [60],
                    "notifiers": [],
                }
            }
        },
    )
    await hass.async_block_till_done()
    entry = await _entry(hass, [_target("alert.leak")])
    switchboard = entry.runtime_data.switchboard

    # Stuck apart (a done template that failed): never confirmed.
    hass.states.async_set("alert.leak", "on")
    assert await switchboard._async_closing_slugs(("leak",)) == frozenset()

    # Core writes `idle` while the handler yields: confirmed.
    hass.loop.call_soon(hass.states.async_set, "alert.leak", "idle")
    assert await switchboard._async_closing_slugs(("leak",)) == frozenset({"leak"})

    # Nothing suspected: no yield, nothing confirmed.
    assert await switchboard._async_closing_slugs(("unknown",)) == frozenset()


def test_the_blueprint_ref_is_this_versions_release_tag() -> None:
    """`source_url` and the import link follow the manifest, never `main`."""
    import json  # noqa: PLC0415

    manifest = json.loads(
        (Path(automation_blueprint.__file__).parent / "manifest.json").read_text(
            encoding="utf-8"
        )
    )
    assert f"v{manifest['version']}" == automation_blueprint.BLUEPRINT_REF
    for language in automation_blueprint.BLUEPRINT_LANGUAGES:
        text = packaged_blueprint(language).read_text(encoding="utf-8")
        assert f"/{automation_blueprint.BLUEPRINT_REF}/" in text
        assert "/main/" not in text
