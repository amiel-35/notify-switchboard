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
# Minor 2 adds `queued_at` to every deferral, so a deferral whose wake time
# passed while Home Assistant was down can be delivered at the next start
# instead of waiting a whole day.
# Minor 3 (v0.2, ADR-0016) adds the `silences` list: the temporary, router-owned
# per-person silences set by `notify_switchboard.silence`.
STORAGE_MINOR_VERSION: Final = 3

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

# Per-row optional texts (v0.2 addendum, ADR-0016). All three default to None,
# so a Sprint 1 row keeps behaving exactly as it did.
CONF_MESSAGE: Final = "message"
CONF_DONE_MESSAGE: Final = "done_message"
CONF_DEFAULT_TITLE: Final = "default_title"

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

# State attribute of a `person.*` entity holding the Home Assistant user it is
# linked to (`homeassistant/components/person/const.py`,
# `PersonEntityStateAttribute.USER_ID`). Spelled out here rather than imported
# so the integration keeps no dependency on the `person` component.
ATTR_USER_ID: Final = "user_id"

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
# (brief item 5). `mobile_app` in core 2026.9.1 *does* register one legacy
# `notify.mobile_app_<device>` service per push registration
# (`homeassistant/components/mobile_app/__init__.py` line 110 loads the notify
# platform through discovery; `mobile_app/notify.py` line 177 `async_get_service`
# returns a `BaseNotificationService` whose `targets` property, line 192, is
# `push_registrations(hass)`), and core names each one
# `slugify(f"mobile_app_{device_name}")`
# (`homeassistant/components/notify/legacy.py` line 275). The prefix is
# therefore a reliable marker for "this output is a Companion push service".
COMPANION_OUTPUT_PREFIX: Final = "mobile_app_"

# ---------------------------------------------------------------------------
# UI services (contract §"UI services (v0.2, ADR-0016)")
# ---------------------------------------------------------------------------

SERVICE_ACKNOWLEDGE: Final = "acknowledge"
SERVICE_SNOOZE: Final = "snooze"
SERVICE_UNSNOOZE: Final = "unsnooze"
SERVICE_SILENCE: Final = "silence"
SERVICE_UNSILENCE: Final = "unsilence"

UI_SERVICES: Final[tuple[str, ...]] = (
    SERVICE_ACKNOWLEDGE,
    SERVICE_SNOOZE,
    SERVICE_UNSNOOZE,
    SERVICE_SILENCE,
    SERVICE_UNSILENCE,
)

# Service call fields.
ATTR_TARGET: Final = "target"
ATTR_MINUTES: Final = "minutes"
ATTR_PERSON: Final = "person"

# `ServiceValidationError` translation keys; each one has a matching entry
# under `exceptions` in `strings.json` and every `translations/*.json`.
ERROR_UNKNOWN_TARGET: Final = "unknown_target"
ERROR_ACKNOWLEDGE_NOT_ALLOWED: Final = "acknowledge_not_allowed"
ERROR_SNOOZE_MINUTES_NOT_OFFERED: Final = "snooze_minutes_not_offered"
ERROR_UNKNOWN_PERSON: Final = "unknown_person"
ERROR_PERSON_NOT_IN_AUDIENCE: Final = "person_not_in_audience"
ERROR_INVALID_SILENCE_MINUTES: Final = "invalid_silence_minutes"
ERROR_NO_AUDIENCE: Final = "no_audience"

# The smallest temporary silence that has a defined meaning (ADR-0016:
# `silence(minutes: 0)` is refused, zero has no meaning).
MIN_SILENCE_MINUTES: Final = 1

# ---------------------------------------------------------------------------
# Robustness
# ---------------------------------------------------------------------------

# An output missing for more than this many consecutive calls raises a repair.
MAX_CONSECUTIVE_OUTPUT_MISSES: Final = 3

# A UI service refused for the same unknown target/person this many times
# raises a `repairs` issue (sprint-2 brief item 7). One refused call is already
# reported to its caller as a `ServiceValidationError`; a card wired to a stale
# slug keeps hitting it, and that is what deserves a repair.
MAX_INVALID_SERVICE_CALLS: Final = 3

# Number of decisions kept in memory for diagnostics.
DIAGNOSTICS_DECISION_LOG_SIZE: Final = 20

SIGNAL_STATE_UPDATED: Final = f"{DOMAIN}_state_updated"
