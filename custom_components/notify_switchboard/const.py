"""Constants for the Notify Switchboard integration.

Everything public here is frozen by `docs/contract.md` (ADR-011): the domain,
the legacy service name, the `notify.switchboard_<slug>` scheme and the
`data.*` keys. Renaming any of them breaks every `alert:` a user has written.
"""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "notify_switchboard"

# The legacy `notify.*` service name exposed by this integration, so that
# `notify.switchboard` can be listed under `alert.notifiers:`.
LEGACY_SERVICE_NAME: Final = "switchboard"

# `homeassistant.helpers.storage.Store` key and version (doctrine: nothing in
# RAM only -- snoozes and night deferrals survive a restart).
STORAGE_KEY: Final = f"{DOMAIN}.data"
STORAGE_VERSION: Final = 1

# ---------------------------------------------------------------------------
# Options shape (`entry.options`), normative -- see tests/acceptance/README.md
# ---------------------------------------------------------------------------

CONF_PERSONS: Final = "persons"
CONF_TARGETS: Final = "targets"
CONF_DEFAULT_TARGET: Final = "default_target"

# Person row keys.
CONF_OUTPUTS: Final = "outputs"
CONF_SILENCE_ENTITIES: Final = "silence_entities"
CONF_WAKE_TIME: Final = "wake_time"

# Target (routing table) row keys.
CONF_SLUG: Final = "slug"
CONF_CLASS: Final = "class"
CONF_DEFAULT_PRIORITY: Final = "default_priority"
CONF_ALERT_ENTITY: Final = "alert_entity"
CONF_AUDIENCE: Final = "audience"
CONF_PRESENCE_RULE: Final = "presence_rule"
CONF_ALLOW_ACKNOWLEDGE: Final = "allow_acknowledge"
CONF_SNOOZE_MINUTES: Final = "snooze_minutes"
CONF_DEFAULT_DATA: Final = "default_data"
CONF_OBSERVER_MODE: Final = "observer_mode"

# ---------------------------------------------------------------------------
# `data` payload attributes (contract "Input")
# ---------------------------------------------------------------------------

ATTR_CLASS: Final = "class"
ATTR_PRIORITY: Final = "priority"
ATTR_SOURCE_ENTITY: Final = "source_entity"
ATTR_TAG: Final = "tag"

# Companion-specific keys the router adds to `data` (contract "Buttons").
ATTR_ACTIONS: Final = "actions"
ATTR_AUTHENTICATION_REQUIRED: Final = "authenticationRequired"

# Attribute of `sensor.switchboard_dropped_today`.
ATTR_REASONS: Final = "reasons"

# ---------------------------------------------------------------------------
# Priorities
# ---------------------------------------------------------------------------

PRIORITY_INFO: Final = "info"
PRIORITY_NORMAL: Final = "normal"
PRIORITY_HIGH: Final = "high"
PRIORITY_CRITICAL: Final = "critical"

DEFAULT_PRIORITY: Final = PRIORITY_NORMAL

VALID_PRIORITIES: Final[tuple[str, ...]] = (
    PRIORITY_INFO,
    PRIORITY_NORMAL,
    PRIORITY_HIGH,
    PRIORITY_CRITICAL,
)

# Priorities that require unlocking the phone before an action runs.
AUTHENTICATED_PRIORITIES: Final[frozenset[str]] = frozenset(
    {PRIORITY_HIGH, PRIORITY_CRITICAL}
)

# ---------------------------------------------------------------------------
# Presence rules
# ---------------------------------------------------------------------------

PRESENCE_ALWAYS: Final = "always"
PRESENCE_HOME_ONLY: Final = "home_only"
PRESENCE_AWAY_ONLY: Final = "away_only"

DEFAULT_PRESENCE_RULE: Final = PRESENCE_ALWAYS

VALID_PRESENCE_RULES: Final[tuple[str, ...]] = (
    PRESENCE_ALWAYS,
    PRESENCE_HOME_ONLY,
    PRESENCE_AWAY_ONLY,
)

# ---------------------------------------------------------------------------
# Drop reasons (contract "Routing decision": nothing is silently lost)
# ---------------------------------------------------------------------------

DROP_NOT_IN_AUDIENCE: Final = "not_in_audience"
DROP_UNKNOWN_PERSON: Final = "unknown_person"
DROP_PRESENCE: Final = "presence"
DROP_SILENCED: Final = "silenced"
DROP_SNOOZED: Final = "snoozed"
DROP_RECURSION: Final = "recursion"
DROP_UNKNOWN_TARGET: Final = "unknown_target"
DROP_NO_OUTPUTS: Final = "no_outputs"
DROP_DELIVERY_FAILED: Final = "delivery_failed"

# `not_in_audience` is recorded in the decision for diagnostics but is not a
# drop for the user: the contract says such a person is "not considered".
UNCOUNTED_DROP_REASONS: Final[frozenset[str]] = frozenset({DROP_NOT_IN_AUDIENCE})

# ---------------------------------------------------------------------------
# `event.switchboard_delivery` (contract "Names": fixed event types)
# ---------------------------------------------------------------------------

EVENT_TYPE_ROUTED: Final = "routed"
EVENT_TYPE_DROPPED: Final = "dropped"
EVENT_TYPE_ACKNOWLEDGED: Final = "acknowledged"
EVENT_TYPE_SNOOZED: Final = "snoozed"

DELIVERY_EVENT_TYPES: Final[list[str]] = [
    EVENT_TYPE_ROUTED,
    EVENT_TYPE_DROPPED,
    EVENT_TYPE_ACKNOWLEDGED,
    EVENT_TYPE_SNOOZED,
]

# ---------------------------------------------------------------------------
# Companion callbacks (contract "Buttons and callbacks")
# ---------------------------------------------------------------------------

EVENT_MOBILE_APP_NOTIFICATION_ACTION: Final = "mobile_app_notification_action"

ACTION_NAMESPACE: Final = "switchboard"
ACTION_ACKNOWLEDGE: Final = "ack"
ACTION_SNOOZE: Final = "snooze"

# Only outputs whose legacy service name starts with this prefix get buttons
# (brief item 5). See docs/known-issues.md: modern `mobile_app` no longer
# registers legacy per-device notify services.
COMPANION_OUTPUT_PREFIX: Final = "mobile_app_"

# ---------------------------------------------------------------------------
# Robustness
# ---------------------------------------------------------------------------

# An output missing for more than this many consecutive calls raises a repair.
MAX_CONSECUTIVE_OUTPUT_MISSES: Final = 3

# Number of decisions kept in memory for diagnostics.
DIAGNOSTICS_DECISION_LOG_SIZE: Final = 20

SIGNAL_STATE_UPDATED: Final = f"{DOMAIN}_state_updated"
