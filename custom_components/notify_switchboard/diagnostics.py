"""Diagnostics for Notify Switchboard.

Message bodies are the only thing worth hiding here: they can quote sensor
names, addresses or anything an `alert` template rendered. They go through
`homeassistant.components.diagnostics.async_redact_data`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

if TYPE_CHECKING:
    from . import SwitchboardConfigEntry

TO_REDACT = {"message", "title"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: SwitchboardConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    switchboard = entry.runtime_data.switchboard
    now = dt_util.utcnow()

    return {
        "entry": {
            "version": entry.version,
            "minor_version": entry.minor_version,
            "options": dict(entry.options),
        },
        "counters": {
            "routed_today": switchboard.routed_today,
            "dropped_today": switchboard.dropped_today,
            "reasons": dict(switchboard.drop_reasons),
        },
        "snoozes": [
            {
                "person": person,
                "target": slug,
                "expires_at": expiry.isoformat(),
                "active": expiry > now,
            }
            for (person, slug), expiry in switchboard.store.snoozes.items()
        ],
        "deferrals": [
            async_redact_data(deferral.as_dict(), TO_REDACT)
            for deferral in switchboard.store.deferrals.values()
        ],
        "missing_outputs": dict(switchboard.missing_outputs),
        "last_decisions": [
            async_redact_data(decision, TO_REDACT)
            for decision in switchboard.decision_log
        ],
    }
