"""Diagnostics support for Notify Switchboard.

Nothing routed through this integration is sensitive (no secrets, no
external network calls), so nothing is redacted.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.core import HomeAssistant

from . import SwitchboardConfigEntry


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: SwitchboardConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    last_decision = entry.runtime_data.router.last_decision
    return {
        "options": dict(entry.options),
        "last_decision": asdict(last_decision) if last_decision is not None else None,
    }
