"""Diagnostics for Notify Switchboard.

Everything a human typed is hidden here: message bodies (they can quote sensor
names, addresses or anything an `alert` template rendered) and the `default_data`
of every target (it can hold a push channel, a URL, a phone-specific
payload). Message bodies go through
`homeassistant.components.diagnostics.async_redact_data`; `default_data` is
redacted value by value so the *shape* of the target stays readable, which is
the whole point of a diagnostics dump. Both spell the placeholder the same way,
because both use core's own `REDACTED`: a reader of a dump should never have to
wonder whether two different spellings mean two different things.

One key is not redacted but **dropped**: `class` (ADR-0020 §4). A target stored
by 0.5 may still carry it; the router never reads it, so showing it in a bug
report would invite somebody to explain what it does.

The three per-row texts of ADR-0016 (`message`, `done_message`,
`default_title`) are deliberately **not** redacted. They are configuration, not
content: a Jinja template and a fixed title the user wrote in the options flow,
the same kind of thing as `presence_rule` or `snooze_minutes`, and unreadable
without them the dump cannot explain what observer mode actually sent. What is
redacted is the *rendered* result — it appears as the `message` of a decision
or of a deferral, and both go through `TO_REDACT` below.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.components.diagnostics import REDACTED, async_redact_data
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .const import CONF_DEFAULT_DATA, CONF_TARGETS

# The dead routing-table key of 0.1 -> 0.5.1 (ADR-0020 §4). It is not a
# constant of `const.py` any more, on purpose: nothing in the integration reads
# it, and the one place it is still spelled is the one place it is removed.
DEAD_TARGET_KEY = "class"

if TYPE_CHECKING:
    from . import SwitchboardConfigEntry

TO_REDACT = {"message", "title"}


def _dump_target(row: Any) -> Any:
    """Return one target as a dump shows it: `default_data` hidden, `class` gone."""
    if not isinstance(row, dict):
        return row
    dumped = {key: value for key, value in row.items() if key != DEAD_TARGET_KEY}
    if isinstance(dumped.get(CONF_DEFAULT_DATA), dict):
        dumped[CONF_DEFAULT_DATA] = {key: REDACTED for key in dumped[CONF_DEFAULT_DATA]}
    return dumped


def _redact_options(options: dict[str, Any]) -> dict[str, Any]:
    """Return the entry options with every `default_data` value redacted."""
    redacted = dict(options)
    targets = redacted.get(CONF_TARGETS)
    if not isinstance(targets, list):
        return redacted

    redacted[CONF_TARGETS] = [_dump_target(row) for row in targets]
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
        # The router-owned temporary silences (ADR-0016), next to the snoozes
        # they sit beside in the store. Nothing here needs redacting that is not
        # already redacted: a silence is a `person.*` entity id and an instant.
        "silences": [
            {
                "person": person,
                "until": until.isoformat(),
                "active": until > now,
            }
            for person, until in switchboard.store.silences.items()
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
