"""Put the shipped automation blueprint where Home Assistant lists it (ADR-0023 §1).

An alert tied to no Home Assistant alert is set off by an automation. The
integration ships one blueprint for it -- "when this sensor reaches this state,
set this alert off" -- in three languages, because a blueprint's texts are not
translatable. When the options flow reaches the screen that says "this alert
needs an automation", it copies the file for the instance language into the
configuration directory, **only when no file is there**, so the screen can link
to it. From then on the file is the user's: nothing here overwrites or deletes
it.

Home Assistant APIs and behaviour relied upon (home-assistant/core 2026.9.1):

- homeassistant/components/blueprint/models.py: `DomainBlueprints.async_populate`
  copies core's own example blueprints with `shutil.copytree` into
  `<config>/blueprints/automation/homeassistant/` -- what this module does for
  its own folder, one file at a time; `DomainBlueprints._load_blueprints` globs
  `<config>/blueprints/automation/**/*.yaml` on every listing and loads any
  path it has not cached, so a copied file is listed without a reload;
- homeassistant/components/blueprint/const.py: `BLUEPRINT_FOLDER`
  (`"blueprints"`);
- homeassistant/core_config.py: `Config.path`, `Config.language`.

The frontend side (home-assistant/frontend 20260826.6, the version 2026.9.1
pins) is cited in ADR-0023 §1: the blueprint list at
`/config/blueprint/dashboard` opens the automation editor on a row in one click,
and `my.home-assistant.io/redirect/blueprint_import` imports from a URL.
"""

from __future__ import annotations

import logging
import shutil
from enum import StrEnum
from pathlib import Path
from urllib.parse import quote

from homeassistant.core import HomeAssistant

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

# `homeassistant/components/blueprint/const.py`, `BLUEPRINT_FOLDER`; the
# blueprint integration is not imported for one string.
BLUEPRINT_FOLDER = "blueprints"
AUTOMATION_DOMAIN = "automation"

# Contract v0.9: automations name this path, relative to
# `<config>/blueprints/automation/`.
BLUEPRINT_FILE = "alert_from_a_sensor.yaml"
BLUEPRINT_PATH = f"{DOMAIN}/{BLUEPRINT_FILE}"

# The languages the package ships a file for; anything else gets English.
BLUEPRINT_LANGUAGES = ("en", "fr", "es")
FALLBACK_LANGUAGE = "en"

PACKAGED_FOLDER = Path(__file__).parent / "blueprints"

# The same files on GitHub, for the import link when the copy fails. Each
# packaged file's `source_url` is this, so "Re-import" in the blueprint list
# fetches the file it came from. Pinned to the release tag of this version,
# never `main`: re-importing must not fetch a blueprint newer than the
# integration that installed it. A test keeps it equal to `v<manifest version>`.
BLUEPRINT_REF = "v0.10.0"
RAW_BASE_URL = (
    f"https://raw.githubusercontent.com/amiel-35/notify-switchboard/{BLUEPRINT_REF}/"
    f"custom_components/{DOMAIN}/{BLUEPRINT_FOLDER}"
)
MY_IMPORT_URL = "https://my.home-assistant.io/redirect/blueprint_import/"


class InstallResult(StrEnum):
    """What `async_install_blueprint` found or did."""

    INSTALLED = "installed"
    PRESENT = "present"
    FAILED = "failed"


def blueprint_language(language: str | None) -> str:
    """Return the packaged language for an instance language (`fr-CA` → `fr`)."""
    base = (language or "").split("-")[0].split("_")[0].lower()
    return base if base in BLUEPRINT_LANGUAGES else FALLBACK_LANGUAGE


def packaged_blueprint(language: str) -> Path:
    """Return the packaged file for one of `BLUEPRINT_LANGUAGES`."""
    return PACKAGED_FOLDER / language / BLUEPRINT_FILE


def installed_blueprint(hass: HomeAssistant) -> Path:
    """Return where Home Assistant looks for the blueprint."""
    return Path(
        hass.config.path(BLUEPRINT_FOLDER, AUTOMATION_DOMAIN, DOMAIN, BLUEPRINT_FILE)
    )


def import_url(language: str) -> str:
    """Return the My Home Assistant link that imports the file from GitHub."""
    source = f"{RAW_BASE_URL}/{language}/{BLUEPRINT_FILE}"
    return f"{MY_IMPORT_URL}?blueprint_url={quote(source, safe='')}"


def _copy(source: Path, destination: Path) -> InstallResult:
    """Copy one file unless the destination exists. Runs in the executor."""
    if destination.exists():
        return InstallResult.PRESENT
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
    except OSError as err:
        # Includes a *file* standing where the folder should be.
        _LOGGER.warning("Could not install the blueprint at %s: %s", destination, err)
        return InstallResult.FAILED
    try:
        # `x`: never replace a file that appeared between the check and here.
        with source.open("rb") as src, destination.open("xb") as dst:
            shutil.copyfileobj(src, dst)
    except FileExistsError:
        return InstallResult.PRESENT
    except OSError as err:
        _LOGGER.warning("Could not install the blueprint at %s: %s", destination, err)
        # A half-written file would be "present" for ever after; it is ours
        # until the copy succeeds, so it goes.
        destination.unlink(missing_ok=True)
        return InstallResult.FAILED
    return InstallResult.INSTALLED


async def async_install_blueprint(hass: HomeAssistant) -> InstallResult:
    """Copy the instance-language blueprint into the configuration, if absent."""
    language = blueprint_language(hass.config.language)
    return await hass.async_add_executor_job(
        _copy, packaged_blueprint(language), installed_blueprint(hass)
    )
