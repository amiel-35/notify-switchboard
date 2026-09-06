"""Diagnostics for Notify Switchboard.

Everything a human typed is hidden here: message bodies (they can quote sensor
names, addresses or anything an `alert` template rendered) and the `default_data`
of every routing-table row (it can hold a push channel, a URL, a phone-specific
payload). Message bodies go through
`homeassistant.components.diagnostics.async_redact_data`; `default_data` is
redacted value by value so the *shape* of the row stays readable, which is the
whole point of a diagnostics dump.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.components.diagnostics import REDACTED, async_redact_data
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .const import CONF_DEFAULT_DATA, CONF_TARGETS

if TYPE_CHECKING:
    from . import SwitchboardConfigEntry

TO_REDACT = {"message", "title"}


def _redact_options(options: dict[str, Any]) -> dict[str, Any]:
    """Return the entry options with every `default_data` value redacted."""
    redacted = dict(options)
    rows = redacted.get(CONF_TARGETS)
    if not isinstance(rows, list):
        return redacted

    redacted[CONF_TARGETS] = [
        {
            **row,
            CONF_DEFAULT_DATA: {key: REDACTED for key in row[CONF_DEFAULT_DATA]},
        }
        if isinstance(row, dict) and isinstance(row.get(CONF_DEFAULT_DATA), dict)
        else row
        for row in rows
    ]
    return redacted


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
            "options": _redact_options(dict(entry.options)),
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
        "failing_outputs": dict(switchboard.failing_outputs),
        "last_decisions": [
            async_redact_data(decision, TO_REDACT)
            for decision in switchboard.decision_log
        ],
    }
