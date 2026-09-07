"""Constants for the Notify Switchboard integration.

Everything public here is frozen by `docs/contract.md` (ADR-011): the domain,
the legacy service name, the `notify.switchboard_<slug>` scheme and the
`data.*` keys. Renaming any of them breaks every `alert:` a user has written.
"""

from __future__ import annotations

from typing import Any, Final

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
# Minor 4 (v0.5, ADR-0019 §5) adds the `episodes` list: one record per routing
# table row whose `alert_entity` has fired, holding who was actually told, which
# outputs were called and under which tags. The migration inserts an empty list,
# because an upgrade must not invent an episode.
STORAGE_MINOR_VERSION: Final = 4

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

# v0.5 addendum (ADR-0019 §2): an optional per-person key whose default is
# **on**, so it is written into the row only when it is `False`. Every person
# row written before 0.5.0 keeps the exact dict it had and means "summarise".
CONF_SUMMARY: Final = "summary"

# Target (routing table) row keys.
CONF_SLUG: Final = "slug"
CONF_DEFAULT_PRIORITY: Final = "default_priority"
CONF_ALERT_ENTITY: Final = "alert_entity"
CONF_AUDIENCE: Final = "audience"
CONF_PRESENCE_RULE: Final = "presence_rule"
CONF_ALLOW_ACKNOWLEDGE: Final = "allow_acknowledge"
CONF_SNOOZE_MINUTES: Final = "snooze_minutes"
CONF_DEFAULT_DATA: Final = "default_data"
CONF_OBSERVER_MODE: Final = "observer_mode"

# v0.5 addendum (ADR-0019 §6): an optional row key, absent means false, written
# into the row only when true. When it is on, the row's `done` message is
# cleared from the Companion outputs that received it once the episode is
# closed, instead of living in the notification centre for a week.
CONF_CLEAR_DONE: Final = "clear_done"

# v0.7 addendum (ADR-0021 §1): an optional target key, absent means false,
# written into the row only when it is true -- so every target written before
# 0.7.0 keeps the exact dict it had. When it is true and no person of the
# target's audience is in the literal state `home` at decision time, the call's
# priority is raised one step, for that decision only.
CONF_ESCALATE_WHEN_NOBODY_HOME: Final = "escalate_when_nobody_home"

# v0.7 addendum (ADR-0021 §7): a *global* option, `entry.options`-level, whose
# default is **on**; absent means on, so no migration and no options rewrite.
# Turning it off stops the router adding the Companion critical keys; it never
# puts `data.priority` back.
CONF_CRITICAL_PAYLOAD: Final = "critical_payload"

# v0.4 addendum (ADR-0018 §4): the only new options key of 0.4.0. Optional on
# every row, absent means false, so no storage migration is needed. While it is
# true the router keeps the row's audience in sync with the configured persons;
# submitting the row editor clears it, permanently.
CONF_MANAGED: Final = "managed"

# Per-row optional texts (v0.2 addendum, ADR-0016). All three default to None,
# so a Sprint 1 row keeps behaving exactly as it did.
CONF_MESSAGE: Final = "message"
CONF_DONE_MESSAGE: Final = "done_message"
CONF_DEFAULT_TITLE: Final = "default_title"

# ---------------------------------------------------------------------------
# `data` payload attributes (contract "Input")
# ---------------------------------------------------------------------------

ATTR_PRIORITY: Final = "priority"
ATTR_SOURCE_ENTITY: Final = "source_entity"
ATTR_TAG: Final = "tag"

# v0.5 addendum (ADR-0019). `ttl_minutes` is both a global option key and a
# per-call `data` key -- deliberately the same string, because it is the same
# quantity read at two scopes. `switchboard_done` marks a "back to normal"
# message a caller sends itself (the blueprints will use it); `notification_id`
# is the key the legacy `notify.persistent_notification` service reads.
ATTR_TTL_MINUTES: Final = "ttl_minutes"
CONF_TTL_MINUTES: Final = ATTR_TTL_MINUTES
ATTR_SWITCHBOARD_DONE: Final = "switchboard_done"
ATTR_NOTIFICATION_ID: Final = "notification_id"

# Every `data` key in this namespace belongs to the switchboard itself, which
# is what makes a wake-time summary able to carry "only its own keys" without
# enumerating them (ADR-0019 §2).
SWITCHBOARD_DATA_PREFIX: Final = "switchboard_"

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

# State attribute a `schedule.*` publishes holding the instant its current
# block finishes (`homeassistant/components/schedule/const.py`,
# `ATTR_NEXT_EVENT` / `ScheduleEntityStateAttribute.NEXT_EVENT`). It is the one
# end a silence entity publishes in core 2026.9.1, and therefore the instant a
# deferral made for a person with no `wake_time` is bounded by (v0.6 addendum,
# ADR-0020 §3). Spelled out here rather than imported, exactly like
# `ATTR_USER_ID`, so the integration keeps no dependency on `schedule`.
ATTR_NEXT_EVENT: Final = "next_event"

# State attribute a silence entity may carry to narrow what it catches (v0.7
# addendum, ADR-0021 §2). A `schedule`'s per-block `data:` becomes state
# attributes -- `CUSTOM_DATA_SCHEMA` in
# `$HA_CORE_SRC/homeassistant/components/schedule/__init__.py` line 122, the key
# name `CONF_DATA` in `.../schedule/const.py` line 23, and
# `Schedule._update`'s `self._attr_extra_state_attributes.update(current_data)`
# at line 395 -- so a household publishes a floor with no automation of its own.
# The router reads the **attribute**, never the domain: anything that is `on`
# and exposes it is read the same way.
ATTR_MIN_PRIORITY: Final = "min_priority"

# Registration key `mobile_app` stores the device's operating system under
# (`$HA_CORE_SRC/homeassistant/components/mobile_app/const.py` line 36,
# `ATTR_OS_NAME`). Spelled out here rather than imported, exactly like
# `ATTR_USER_ID`, so the integration keeps no dependency on `mobile_app`.
ATTR_OS_NAME: Final = "os_name"

# The tag every message sent by the options flow's "test this person" /
# "test this target" steps carries under `data.tag` (contract v0.4,
# ADR-0018 §6). Public: a caller, an automation or a Companion channel may
# rely on it to tell a test from the real thing.
TEST_MESSAGE_TAG: Final = "switchboard-test"

# The deterministic identity every outgoing message acquires when the caller
# supplies no `data.tag` (contract v0.5, ADR-0019 §6). All three values are
# public: a Companion channel or an automation may key on them.
TAG_PREFIX: Final = "switchboard-"
DONE_TAG_SUFFIX: Final = "-done"
SUMMARY_TAG: Final = f"{TAG_PREFIX}summary"

# The literal `mobile_app` reads as "remove the notification bearing this tag"
# (`homeassistant/components/mobile_app/const.py`, `CLEAR_NOTIFICATION`).
# Spelled out here rather than imported, exactly like `ATTR_USER_ID`, so the
# integration keeps no dependency on the `mobile_app` component.
CLEAR_NOTIFICATION_MESSAGE: Final = "clear_notification"

# The bare legacy service name of the "write it on the dashboard" output, i.e.
# `notify.persistent_notification`. It is the one output core documents as
# reading `data.notification_id`, so it is the only one the router adds it for.
PERSISTENT_NOTIFICATION_OUTPUT: Final = "persistent_notification"

# The target the first person creates on an empty routing table
# (ADR-0018 §4). Its name is translated (`common.default_target_name`); its
# slug is not, because a slug is a public service name.
DEFAULT_TARGET_SLUG: Final = "default"

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

# `info < normal < high < critical`, which is the order `VALID_PRIORITIES`
# already declares (contract v0.7, ADR-0021 §1 and §2). Derived from that tuple
# rather than written out a second time: two lists of the same four strings in
# the same file is one list and one bug waiting for the day somebody edits only
# one of them.
PRIORITY_RANK: Final[dict[str, int]] = {
    priority: rank for rank, priority in enumerate(VALID_PRIORITIES)
}

# The value `explain`'s `escalated` key carries when an empty house raised this
# decision's priority (contract v0.7, ADR-0021 §8). It is `null` when nothing
# did -- including when the rule's condition held but the priority was already
# `critical`.
ESCALATED_NOBODY_HOME: Final = "nobody_home"

# Time-to-live defaults, in minutes, per priority (contract v0.5, ADR-0019 §1).
# `None` means "never expires", and so does an absent key of
# `entry.options["ttl_minutes"]`. `critical` has no entry and cannot be given
# one: a critical message bypasses silence everywhere, so it is never deferred,
# so it can never expire.
DEFAULT_TTL_MINUTES: Final[dict[str, int | None]] = {
    PRIORITY_INFO: 120,
    PRIORITY_NORMAL: 720,
    PRIORITY_HIGH: None,
}

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

# v0.5 addendum (ADR-0019). Two more reasons, no new event type: both travel in
# the existing `dropped` `event.switchboard_delivery` and both count towards
# `sensor.switchboard_dropped_today`.
DROP_EXPIRED: Final = "expired"
DROP_NOT_NOTIFIED: Final = "not_notified"

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
# The critical payload, translated per OS (contract v0.7, ADR-0021 §7)
# ---------------------------------------------------------------------------

# The keys the Companion documentation gives for a critical notification
# (<https://companion.home-assistant.io/docs/notifications/critical-notifications/>,
# fetched 2026-09-07): on iOS a sound that plays through Do Not Disturb, on
# Android the alarm stream plus an immediate, unbatched Firebase delivery.
# Written as builders rather than as module-level dicts because the iOS payload
# is nested: a shared nested mapping handed to `dict.setdefault` would end up
# in every message's `data`, one object for the whole process.
ATTR_PUSH: Final = "push"
ATTR_TTL: Final = "ttl"
ATTR_CHANNEL: Final = "channel"
CRITICAL_SOUND_NAME: Final = "default"
CRITICAL_CHANNEL: Final = "alarm_stream"


def critical_payload_apple() -> dict[str, Any]:
    """Return the Companion critical keys an Apple registration understands."""
    return {
        ATTR_PUSH: {
            "sound": {"name": CRITICAL_SOUND_NAME, "critical": 1, "volume": 1.0}
        }
    }


def critical_payload_android() -> dict[str, Any]:
    """Return the Companion critical keys an Android registration understands."""
    return {ATTR_TTL: 0, ATTR_PRIORITY: PRIORITY_HIGH, ATTR_CHANNEL: CRITICAL_CHANNEL}


# Matching is case-insensitive, and anything the router cannot identify -- an
# unknown string, an entry with no `os_name`, no matching registration at all --
# takes **both** sets: the keys of one OS are inert on the other, and a
# household whose registration predates the field should get a phone that rings
# rather than one that is quiet because the router could not tell.
APPLE_OS_NAMES: Final[frozenset[str]] = frozenset({"ios", "ipados", "watchos"})
ANDROID_OS_NAME: Final = "android"

# The `notify` entity action an output that is an entity id is delivered with
# (`$HA_CORE_SRC/homeassistant/components/notify/const.py` line 29,
# `SERVICE_SEND_MESSAGE`; registered on the entity component in
# `.../notify/__init__.py` lines 84-91). It carries `message` and `title` and
# nothing else, which is the whole of contract v0.7 §"Entity outputs".
SERVICE_SEND_MESSAGE: Final = "send_message"

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

# The read-only sixth service (contract v0.4, ADR-0018 §1). It is registered
# next to the five above, with `SupportsResponse.ONLY`, and it acts on nothing.
SERVICE_EXPLAIN: Final = "explain"

# Keys of an `explain` response (contract v0.4: "the response is a mapping with
# three keys ... Each person's value has exactly these keys").
ATTR_PERSONS: Final = "persons"
ATTR_DECISION: Final = "decision"
ATTR_UNTIL: Final = "until"
ATTR_REASON: Final = "reason"
ATTR_DETAIL: Final = "detail"
ATTR_OUTPUTS: Final = "outputs"
ATTR_MISSING_OUTPUTS: Final = "missing_outputs"

# v0.7 addendum (ADR-0021 §8): the response goes from three top-level keys to
# five. `escalated` names the rule that raised this decision's priority;
# `outputs` -- the same string as the per-person key above, deliberately, since
# it is the same kind of list -- lists the target's bare outputs at the top
# level, because a bare output has no person to hang off.
ATTR_ESCALATED: Final = "escalated"

# The three values `decision` can take. No fourth one without an ADR.
DECISION_ROUTED: Final = "routed"
DECISION_DEFERRED: Final = "deferred"
DECISION_DROPPED: Final = "dropped"

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
# Raised by every UI service when the integration is set up but no config entry
# is loaded (v0.3, ADR-0017 §5: the services live in `async_setup`).
ERROR_NO_LOADED_ENTRY: Final = "no_loaded_entry"

# The smallest temporary silence that has a defined meaning (ADR-0016:
# `silence(minutes: 0)` is refused, zero has no meaning).
MIN_SILENCE_MINUTES: Final = 1

# The longest temporary silence, in minutes: one day, the same ceiling
# `services.yaml` already puts on the `minutes` number selector. An upper bound
# is not cosmetic: `dt_util.utcnow() + timedelta(minutes=minutes)` raises
# `OverflowError` (a plain `Exception`, not a `HomeAssistantError`) as soon as
# the result leaves `datetime`'s range, so an unbounded `minutes` turns a
# caller's typo into a 500 instead of a translated refusal. Beyond a day, a
# silence is a schedule -- that is what a person's `silence_entities` are for.
MAX_SILENCE_MINUTES: Final = 1440

# ---------------------------------------------------------------------------
# Robustness
# ---------------------------------------------------------------------------

# An output missing for more than this many consecutive calls raises a repair.
MAX_CONSECUTIVE_OUTPUT_MISSES: Final = 3

# A UI service refused for the same unknown target/person this many times
# raises a `repairs` issue (sprint-2 brief item 7). One refused call is already
# reported to its caller as a `ServiceValidationError`; a card wired to a stale
# slug keeps hitting it, and that is what deserves a repair.
#
# The count is **cumulative, not consecutive**: it is only ever reset when that
# exact slug/person becomes valid again (the row is added back, the person joins
# the audience), at which point the issue is deleted too. Nothing else clears
# it, so three refusals a week apart raise the issue just as three in a row do
# -- which is the point, since a card wired to a stale slug fires whenever
# somebody taps it, not in bursts.
MAX_INVALID_SERVICE_CALLS: Final = 3

# How many *distinct* invalid targets/persons are tracked individually. A caller
# that generates a fresh bad value on every call (a template gone wrong, a fuzz
# test) would otherwise grow the counter dict and the issue registry without
# bound, one persisted `repairs` issue per value. Past this many distinct
# values, no new per-value issue is raised and a single aggregated one takes
# over.
MAX_TRACKED_INVALID_SERVICE_CALLS: Final = 20

# The aggregated `repairs` issue id/translation key used past that bound.
ISSUE_INVALID_SERVICE_CALLS_MANY: Final = "invalid_service_calls_many"

# The per-output fan-out timeout lives in `dispatcher.OUTPUT_TIMEOUT_SECONDS`,
# not here: ADR-0017 §3 fixes that module and that name so the acceptance suite
# can patch it instead of waiting 30 seconds.

# The `repairs` issue raised for a person who is in the audience of a row that
# adds Companion buttons but whose `person.*` is not linked to a Home Assistant
# user, so `context.user_id` can never resolve them (v0.3, ADR-0017 §4).
ISSUE_PERSON_WITHOUT_USER_ID: Final = "person_without_user_id"

# The two consistency repairs of v0.4 (ADR-0018 §5). Both are `is_fixable=False`
# -- the fix is in the user's configuration, not in this integration -- raised
# once and deleted when their cause disappears on the next reload.
ISSUE_PERSON_WITHOUT_OUTPUTS: Final = "person_without_outputs"
ISSUE_ALERT_ENTITY_MISSING: Final = "alert_entity_missing"

# Number of decisions kept in memory for diagnostics.
DIAGNOSTICS_DECISION_LOG_SIZE: Final = 20

SIGNAL_STATE_UPDATED: Final = f"{DOMAIN}_state_updated"
