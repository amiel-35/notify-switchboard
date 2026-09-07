"""Side effects for Notify Switchboard.

`router.py` decides, this module acts: it reads the world into a
`RoutingContext`, calls the resolved `notify.*` services, adds Companion
buttons, persists snoozes and night deferrals, listens for Companion
callbacks, observes `alert.*` states in observer mode, keeps the diagnostic
counters and raises `repairs` issues.

Home Assistant APIs used here (paths in home-assistant/core 2026.9.1):
- homeassistant/helpers/event.py: async_track_state_change_event,
  async_track_point_in_time, async_track_time_change
- homeassistant/helpers/storage.py: Store (through .store)
- homeassistant/helpers/translation.py: async_get_translations
- homeassistant/helpers/issue_registry.py: async_create_issue
- homeassistant/helpers/device_registry.py: async_get, async_get_device
- homeassistant/helpers/dispatcher.py: async_dispatcher_send
- homeassistant/helpers/template/__init__.py: Template(...).async_render
- homeassistant/exceptions.py: ServiceValidationError
- homeassistant/util/dt.py: now, utcnow, parse_datetime
"""

from __future__ import annotations

import asyncio
import logging
from collections import deque
from collections.abc import Iterable, Iterator, Mapping
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, Final

import voluptuous as vol
from homeassistant.components.notify import NotifyEntityFeature
from homeassistant.const import (
    ATTR_ENTITY_ID,
    ATTR_FRIENDLY_NAME,
    ATTR_SUPPORTED_FEATURES,
    EVENT_HOMEASSISTANT_STOP,
    STATE_HOME,
    STATE_IDLE,
    STATE_NOT_HOME,
    STATE_OFF,
    STATE_ON,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
)
from homeassistant.core import (
    CALLBACK_TYPE,
    Context,
    Event,
    HomeAssistant,
    State,
    callback,
)
from homeassistant.exceptions import (
    HomeAssistantError,
    ServiceValidationError,
    TemplateError,
)
from homeassistant.helpers import device_registry as dr, issue_registry as ir
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import (
    EventStateChangedData,
    async_call_later,
    async_track_point_in_time,
    async_track_state_change_event,
    async_track_time_change,
)
from homeassistant.helpers.template import Template
from homeassistant.helpers.translation import async_get_translations
from homeassistant.util import dt as dt_util, slugify

from .const import (
    ACTION_ACKNOWLEDGE,
    ATTR_ACTIONS,
    ATTR_AUTHENTICATION_REQUIRED,
    ATTR_DECISION,
    ATTR_DETAIL,
    ATTR_ESCALATED,
    ATTR_MIN_PRIORITY,
    ATTR_MISSING_OUTPUTS,
    ATTR_NEXT_EVENT,
    ATTR_NOTIFICATION_ID,
    ATTR_OS_NAME,
    ATTR_OUTPUTS,
    ATTR_PERSON,
    ATTR_PERSONS,
    ATTR_PRIORITY,
    ATTR_REASON,
    ATTR_SWITCHBOARD_DONE,
    ATTR_TAG,
    ATTR_TARGET,
    ATTR_UNTIL,
    ATTR_USER_ID,
    AUTHENTICATED_PRIORITIES,
    CLEAR_NOTIFICATION_MESSAGE,
    COMPANION_OUTPUT_PREFIX,
    CONF_CRITICAL_PAYLOAD,
    CONF_TTL_MINUTES,
    DECISION_DEFERRED,
    DECISION_DROPPED,
    DECISION_ROUTED,
    DELIVERY_EVENT_TYPES,
    DIAGNOSTICS_DECISION_LOG_SIZE,
    DOMAIN,
    DROP_DELIVERY_FAILED,
    DROP_EXPIRED,
    DROP_NOT_IN_AUDIENCE,
    DROP_SILENCED,
    DROP_SNOOZED,
    DROP_UNKNOWN_PERSON,
    DROP_UNKNOWN_TARGET,
    ERROR_ACKNOWLEDGE_NOT_ALLOWED,
    ERROR_INVALID_SILENCE_MINUTES,
    ERROR_NO_AUDIENCE,
    ERROR_PERSON_NOT_IN_AUDIENCE,
    ERROR_SNOOZE_MINUTES_NOT_OFFERED,
    ERROR_UNKNOWN_PERSON,
    ERROR_UNKNOWN_TARGET,
    EVENT_MOBILE_APP_NOTIFICATION_ACTION,
    EVENT_TYPE_ACKNOWLEDGED,
    EVENT_TYPE_DROPPED,
    EVENT_TYPE_ROUTED,
    EVENT_TYPE_SNOOZED,
    ISSUE_ALERT_ENTITY_MISSING,
    ISSUE_INVALID_SERVICE_CALLS_MANY,
    ISSUE_PERSON_WITHOUT_OUTPUTS,
    ISSUE_PERSON_WITHOUT_USER_ID,
    MAX_CONSECUTIVE_OUTPUT_MISSES,
    MAX_INVALID_SERVICE_CALLS,
    MAX_SILENCE_MINUTES,
    MAX_TRACKED_INVALID_SERVICE_CALLS,
    MIN_SILENCE_MINUTES,
    PERSISTENT_NOTIFICATION_OUTPUT,
    PRIORITY_CRITICAL,
    PRIORITY_RANK,
    SERVICE_SEND_MESSAGE,
    SIGNAL_STATE_UPDATED,
    SUMMARY_TAG,
    TEST_MESSAGE_TAG,
    UNCOUNTED_DROP_REASONS,
)
from .router import (
    NotificationRequest,
    PersonConfig,
    RoutedDelivery,
    RoutingContext,
    RoutingDecision,
    RoutingTable,
    TargetConfig,
    build_actions,
    build_routing_table,
    caller_tag,
    collapse_by_tag,
    critical_keys_for_os,
    decide,
    effective_priority,
    effective_tag,
    is_recursive_output,
    merge_data,
    parse_action,
    parse_min_priority,
    resolve_priority,
    resolve_ttl,
    silences_catching,
    split_outputs,
    state_is_on,
    summary_data,
)
from .store import DeferredMessage, Episode, SwitchboardStore

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry

_LOGGER = logging.getLogger(__name__)

# How long one `notify.<output>` call may take before the router abandons it
# (contract v0.3, ADR-0017 §3). Deliberately a plain module constant: it is a
# backstop against a hung push service, not a tuning knob, and the acceptance
# suite patches it here rather than waiting half a minute for a timeout.
OUTPUT_TIMEOUT_SECONDS: Final = 30

# How long after an entry is set up the router waits before complaining that a
# row's `alert_entity` is not in the state machine (contract v0.4, ADR-0018 §5).
# At setup the `alert` component may simply not have been set up yet, and a
# router that shouts about every alert during startup trains its user to ignore
# it. Like `OUTPUT_TIMEOUT_SECONDS` this is a plain module constant on purpose:
# it is a backstop, not a tuning knob, and the acceptance suite must be able to
# reach past it without waiting a minute.
ALERT_ENTITY_GRACE_SECONDS: Final = 60

NOTIFY_DOMAIN = "notify"
ALERT_DOMAIN = "alert"
SERVICE_TURN_OFF = "turn_off"
MOBILE_APP_DOMAIN = "mobile_app"
# The `mobile_app` config-entry data key holding the name its owner gave the
# device. Spelled out rather than imported, exactly as `MOBILE_APP_DOMAIN` is:
# the integration keeps no dependency on `mobile_app`.
MOBILE_APP_DEVICE_NAME = "device_name"
# The UI half of an episode is closed through core's own service
# (`homeassistant/components/persistent_notification/__init__.py`: the `dismiss`
# service, `SCHEMA_SERVICE_NOTIFICATION`, `async_dismiss`).
PERSISTENT_NOTIFICATION_DOMAIN = "persistent_notification"
SERVICE_DISMISS = "dismiss"

TRANSLATION_CATEGORY = "common"
KEY_ACKNOWLEDGE = f"component.{DOMAIN}.{TRANSLATION_CATEGORY}.acknowledge"
KEY_SNOOZE_MINUTES = f"component.{DOMAIN}.{TRANSLATION_CATEGORY}.snooze_minutes"
KEY_BACK_TO_NORMAL = f"component.{DOMAIN}.{TRANSLATION_CATEGORY}.back_to_normal"
KEY_TEST_MESSAGE = f"component.{DOMAIN}.{TRANSLATION_CATEGORY}.test_message"
# The wake-time summary (contract v0.5, ADR-0019 §2). `{count}` is the number
# of **lines**, not of messages that were queued: the count and the list a user
# reads must agree.
KEY_SUMMARY_TITLE = f"component.{DOMAIN}.{TRANSLATION_CATEGORY}.summary_title"
KEY_SUMMARY_LINE = f"component.{DOMAIN}.{TRANSLATION_CATEGORY}.summary_line"
KEY_SUMMARY_LINE_UNTITLED = (
    f"component.{DOMAIN}.{TRANSLATION_CATEGORY}.summary_line_untitled"
)

# One `common.detail_*` string per thing `explain` can have to say (ADR-0018
# §1: "`detail` is always a non-empty translated sentence ... naming the thing
# the user has to look at"). Keyed by the drop reason where there is one, so a
# reason added to the contract cannot silently lose its sentence.
KEY_DETAIL_PREFIX = f"component.{DOMAIN}.{TRANSLATION_CATEGORY}.detail_"
DETAIL_SILENCED_TEMPORARY = "silenced_temporary"
# The floored variant of `detail_silenced` (ADR-0021 §2): same drop reason,
# same switch to look at, plus the floor that decided which calls it catches.
DETAIL_SILENCED_FLOOR = "silenced_floor"

# v0.7.1: the two `common` words an output label is built from. They live
# here, next to `friendly_name` and `companion_service_name`, because both
# halves of the interface have to name the same phone the same way -- the
# `outputs` picker of the options flow, and the `detail` sentence `explain`
# and the test result show.
LABEL_HOME_ASSISTANT_APP = "home_assistant_app"
LABEL_PERSISTENT_NOTIFICATION = "persistent_notification"
OUTPUT_LABEL_FALLBACKS: dict[str, str] = {
    LABEL_HOME_ASSISTANT_APP: "Home Assistant app",
    LABEL_PERSISTENT_NOTIFICATION: "Home Assistant notifications",
}

# v0.7.1: the words a `detail` sentence names somebody's whereabouts with.
# `home` and `not_home` are the state machine's words, and a sentence that
# quotes them reads "Alice is currently not_home". A state that is neither --
# a zone -- is already a name the household chose, and is passed through.
LABEL_STATE_HOME = "state_home"
LABEL_STATE_NOT_HOME = "state_not_home"
LABEL_STATE_UNKNOWN = "state_unknown"
PERSON_STATE_LABELS: dict[str, str] = {
    STATE_HOME: LABEL_STATE_HOME,
    STATE_NOT_HOME: LABEL_STATE_NOT_HOME,
    # `unknown` and `unavailable` say the same thing to a household -- the
    # house cannot tell -- and there is nothing to be gained from spelling the
    # difference out on a screen.
    STATE_UNKNOWN: LABEL_STATE_UNKNOWN,
    STATE_UNAVAILABLE: LABEL_STATE_UNKNOWN,
}
PERSON_STATE_FALLBACKS: dict[str, str] = {
    LABEL_STATE_HOME: "at home",
    LABEL_STATE_NOT_HOME: "away from home",
    LABEL_STATE_UNKNOWN: "somewhere the house cannot name",
}

# The `SelectSelector` translation keys of the two coded choices. They live
# here, with the output labels, for the same reason: the options flow shows
# them to pick a value and `explain` shows them to justify a decision, and the
# two must be the same words. `SelectSelectorConfig(translation_key=...)` is
# how Home Assistant labels a stored value, so there is exactly one place the
# wording lives -- `component.<domain>.selector.<key>.options.<value>` --
# rather than a second copy in `common` that would drift.
SELECTOR_CATEGORY = "selector"
SELECTOR_PRIORITY = "priority"
SELECTOR_PRESENCE_RULE = "presence_rule"
KEY_SELECTOR_PREFIX = f"component.{DOMAIN}.{SELECTOR_CATEGORY}."

FALLBACK_ACKNOWLEDGE = "Acknowledge"
FALLBACK_SNOOZE = "Snooze {minutes} min"
FALLBACK_BACK_TO_NORMAL = "Back to normal"
FALLBACK_TEST_MESSAGE = "Notify Switchboard test message"
FALLBACK_SUMMARY_TITLE = "{count} messages while you were away"
FALLBACK_SUMMARY_LINE = "\u2022 {title} \u2014 {message}"
FALLBACK_SUMMARY_LINE_UNTITLED = "\u2022 {message}"
# `detail` is promised non-empty even if a translation file is somehow missing
# the key, so every lookup falls back to something a human can still read.
FALLBACK_DETAIL = "No explanation is available for this decision."

# The name a row's `message`/`done_message` template sees the alert under
# (contract §"Per-row texts": "rendered with the row's alert's current state
# exposed as `alert`").
TEMPLATE_ALERT_VARIABLE = "alert"
ATTR_ALERT_MESSAGE = "message"
ATTR_ALERT_DONE_MESSAGE = "done_message"


class Switchboard:
    """Owns every side effect of one config entry."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialise the switchboard for a config entry."""
        self.hass = hass
        self.entry = entry
        self.table: RoutingTable = build_routing_table(dict(entry.options))
        self.store = SwitchboardStore(hass)

        self.routed_today = 0
        self.dropped_today = 0
        # Deferrals are neither routed nor dropped: they are late. Counting
        # them separately is the only way a user can see that a quiet night
        # was a queue rather than silence.
        self.deferred_today = 0
        self.drop_reasons: dict[str, int] = {}
        self.last_notification: dict[str, datetime] = {}
        self.decision_log: deque[dict[str, Any]] = deque(
            maxlen=DIAGNOSTICS_DECISION_LOG_SIZE
        )

        self._unsubs: list[CALLBACK_TYPE] = []
        # Kept out of `_unsubs` on purpose: see `_async_stop_event`.
        self._stop_unsub: CALLBACK_TYPE | None = None
        self._deferral_unsubs: dict[str, CALLBACK_TYPE] = {}
        # One timer per temporarily silenced person, so `binary_sensor.
        # <p>_silenced` goes back to `off` on its own when the silence lifts
        # rather than waiting for the next routing decision to purge it.
        self._silence_unsubs: dict[str, CALLBACK_TYPE] = {}
        # Consecutive failures per output service: a service that does not
        # exist and one that keeps raising both count here.
        self.failing_outputs: dict[str, int] = {}
        self._reported_unknown_targets: set[str] = set()
        self._labels: dict[str, str] | None = None
        self._selector_labels: dict[str, str] | None = None
        # How many times a UI service was refused for the same unknown
        # target/person, keyed by `(field, value)` (brief item 7).
        self._invalid_service_calls: dict[tuple[str, str], int] = {}
        # Set when an episode gained a recipient, an output or a tag during a
        # delivery (ADR-0019 §5). The save is done once, by the request that
        # caused it, rather than once per person of a fan-out.
        self._episodes_dirty = False
        # Set by `async_shutdown`. Unloading detaches the listeners but does
        # *not* cancel a flush task that has not started yet, so the flush has
        # to stand down on its own; see `_async_flush_deferrals`.
        self._shutdown = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def async_setup(self) -> None:
        """Load persisted state and start every listener."""
        await self.store.async_load()

        # An options change reloads the entry, so this is also the moment a
        # slug or a person the user has just added stops being "invalid".
        self._async_clear_fixed_service_issues()

        # Same moment, same reason: linking a `person.*` to a Home Assistant
        # user is a deliberate change the user makes in Settings > People, not
        # a routing event, so the repair is (re)evaluated on reload.
        self._async_review_person_user_ids()

        # ADR-0018 §5: a person with no outputs is dropped with `no_outputs` on
        # every single message, for ever, and nothing says so. Evaluated here
        # because an options change reloads the entry, which is exactly the
        # moment the gap is closed.
        self._async_review_person_outputs()

        # The alert check cannot run now -- `alert` may not be set up yet -- but
        # issues for a slug the table no longer has, or for a row that no longer
        # names an alert, are pruned at once: the issue registry is persisted, so
        # nothing else would ever clear them.
        self._async_review_alert_entities(create=False)

        self._unsubs.append(
            self.hass.bus.async_listen(
                EVENT_MOBILE_APP_NOTIFICATION_ACTION, self._async_handle_action_event
            )
        )
        self._unsubs.append(
            async_track_time_change(
                self.hass, self._async_reset_counters, hour=0, minute=0, second=0
            )
        )

        silence_entities = sorted(
            {
                entity_id
                for person in self.table.persons.values()
                for entity_id in person.silence_entities
            }
        )
        if silence_entities:
            self._unsubs.append(
                async_track_state_change_event(
                    self.hass, silence_entities, self._async_silence_changed
                )
            )

        # ADR-0019 §5: every row that names an `alert_entity` has episodes, in
        # observer mode or not -- a row whose alert calls
        # `notify.switchboard_<slug>` through its own `notifiers:` list has
        # exactly the same ones. So the subscription is widened from "every
        # observed alert" to "every row's alert"; only the *routing* half of the
        # handler is still reserved to observer mode.
        alerts = sorted(
            {
                target.alert_entity
                for target in self.table.targets.values()
                if target.alert_entity
            }
        )
        if alerts:
            self._unsubs.append(
                async_track_state_change_event(
                    self.hass, alerts, self._async_alert_changed
                )
            )

        # Config entries are not unloaded when Home Assistant stops, so timers
        # have to be cancelled explicitly or they outlive the event loop.
        self._stop_unsub = self.hass.bus.async_listen_once(
            EVENT_HOMEASSISTANT_STOP, self._async_stop_event
        )

        # A restart may have spanned somebody's wake time: deliver what is
        # already late before arming the timers for what is not.
        await self._async_catch_up_deferrals()

        for person in self.table.persons:
            self._async_schedule_deferral(person)

        # ADR-0018 §5: the alert-entity check runs once, ALERT_ENTITY_GRACE_SECONDS
        # after this entry's own setup. The handle joins `_unsubs` so unloading
        # the entry -- or Home Assistant stopping -- cancels a grace check that
        # has not fired yet, instead of leaving a live timer behind.
        self._unsubs.append(
            async_call_later(
                self.hass, ALERT_ENTITY_GRACE_SECONDS, self._async_alert_grace_elapsed
            )
        )

        # A restart may also have spanned the end of a temporary silence.
        # Persist the purge: without the save, the lifted silence is still on
        # disk and comes back at the next load if nothing else writes the store
        # in between.
        if self.store.purge_expired_silences(dt_util.utcnow()):
            await self.store.async_save()
        for person, until in self.store.silences.items():
            self._async_schedule_silence_expiry(person, until)

    @callback
    def _async_stop_event(self, _event: Event) -> None:
        """Detach everything when Home Assistant shuts down.

        Config entries are not unloaded on shutdown, so nothing else runs
        `async_shutdown`: without this, the midnight counter reset armed by
        `async_track_time_change`, the bus listener and the state trackers all
        outlive the event loop they were scheduled on.

        The stop listener itself is already gone by the time this runs --
        `_OneTimeListener.__call__` (`homeassistant/core.py`, lines 1470-1478)
        removes it *before* calling us -- so its unsub is dropped here rather
        than left for `async_shutdown` to call a second time. Calling it twice
        reaches `EventBus._async_remove_listener` (lines 1823-1843), which
        logs "Unable to remove unknown job listener" with a `ValueError`
        traceback: an ERROR on every single Home Assistant shutdown. That is
        also why the unsub lives in its own slot instead of in `_unsubs`.
        """
        self._stop_unsub = None
        self.async_shutdown()

    @callback
    def async_cancel_timers(self) -> None:
        """Cancel every pending deferral and silence-expiry timer."""
        for unsub in self._deferral_unsubs.values():
            unsub()
        self._deferral_unsubs.clear()
        for unsub in self._silence_unsubs.values():
            unsub()
        self._silence_unsubs.clear()

    @callback
    def async_shutdown(self) -> None:
        """Detach every listener (called when the config entry unloads).

        The flag is what stops a flush this entry has already scheduled: core
        *awaits* `ConfigEntry.async_create_task` tasks at unload rather than
        cancelling them (`homeassistant/config_entries.py`,
        `_async_process_on_unload` waits ten seconds on `_tasks` and cancels
        only `_background_tasks`), so a flush queued a moment earlier would
        otherwise run with every listener already detached.
        """
        self._shutdown = True
        self.async_cancel_timers()
        if self._stop_unsub is not None:
            self._stop_unsub()
            self._stop_unsub = None
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()

    # ------------------------------------------------------------------
    # Reading the world
    # ------------------------------------------------------------------

    def build_context(self) -> RoutingContext:
        """Snapshot person states, silence sources and live snoozes."""
        now = dt_util.utcnow()
        self.store.purge_expired_snoozes(now)
        self.store.purge_expired_silences(now)

        person_states: dict[str, str] = {}
        for entity_id in self.table.persons:
            if (state := self.hass.states.get(entity_id)) is not None:
                person_states[entity_id] = state.state

        # Only the entities that are **on**, each mapped to the floor it
        # publishes (ADR-0021 §2). An entity that is `off` is simply absent,
        # which is what makes "is this silence catching my call" one membership
        # test plus one rank comparison rather than two lookups.
        silenced: dict[str, str | None] = {}
        for person in self.table.persons.values():
            for entity_id in person.silence_entities:
                state = self.hass.states.get(entity_id)
                if state is None or not state_is_on(state.state):
                    continue
                silenced[entity_id] = parse_min_priority(
                    state.attributes.get(ATTR_MIN_PRIORITY)
                )

        return RoutingContext(
            now=now,
            person_states=person_states,
            silenced=silenced,
            snoozes=dict(self.store.snoozes),
            temporary_silences=dict(self.store.silences),
            episode_recipients=self._episode_recipients(),
        )

    def _episode_recipients(self) -> dict[str, frozenset[str]]:
        """Return, per row that has episodes, who its current one reached.

        A slug is a key of this mapping **iff** its row names an
        `alert_entity`: an absent key is what makes `not_notified` unreachable
        for a household that never wrote an `alert:` block, and an empty set is
        a row whose alert fired and reached nobody -- there is simply nobody to
        tell that it is over (ADR-0019 §5).
        """
        recipients: dict[str, frozenset[str]] = {}
        for slug, target in self.table.targets.items():
            if not target.alert_entity:
                continue
            episode = self.store.episodes.get(slug)
            recipients[slug] = frozenset(episode.persons if episode else ())
        return recipients

    def is_person_silenced(self, person: PersonConfig) -> bool:
        """Return True when either silence source covers this person.

        ADR-0016: `binary_sensor.<p>_silenced` is true when one of the person's
        own `silence_entities` is `on` **or** a `notify_switchboard.silence` has
        not expired yet. The two sources are independent; the router owns only
        the second one.
        """
        return self.has_configured_silence(
            person
        ) or self.store.is_temporarily_silenced(person.entity_id, dt_util.utcnow())

    def configured_silence_end(self, person: PersonConfig) -> datetime | None:
        """Return the earliest end this person's active silences publish.

        ADR-0020 §3: a wake time is optional, and a silenced person who has
        none is deferred rather than dropped **when the silence says when it
        ends**. In core 2026.9.1 exactly one domain publishes such an end:
        `schedule`, whose entity carries the instant its current block finishes
        as a `next_event` state attribute
        (`$HA_CORE_SRC/homeassistant/components/schedule/const.py`,
        `ATTR_NEXT_EVENT` / `ScheduleEntityStateAttribute.NEXT_EVENT`, set in
        `schedule/__init__.py`'s extra state attributes). The attribute is read
        rather than the domain matched, so an entity that publishes the same
        thing works for the same reason; an `input_boolean`, a Companion Focus
        `binary_sensor` and a temporary `notify_switchboard.silence` publish
        nothing and are deliberately left out -- deferring against them would
        queue a message with no upper bound and nothing to report as `until`.

        Only silences that are **on** count: an end published by a schedule
        that is already off is the end of somebody else's night.
        """
        ends: list[datetime] = []
        for entity_id in person.silence_entities:
            state = self.hass.states.get(entity_id)
            if state is None or not state_is_on(state.state):
                continue
            raw = state.attributes.get(ATTR_NEXT_EVENT)
            if raw is None:
                continue
            end = raw if isinstance(raw, datetime) else dt_util.parse_datetime(str(raw))
            if end is not None:
                ends.append(dt_util.as_utc(end))
        return min(ends) if ends else None

    def deferral_until(self, person: PersonConfig) -> datetime | None:
        """Return when a deferral for this person would be flushed, if ever.

        The wake time when there is one -- unchanged from 0.5.1 -- and the end
        the silence publishes when there is not (ADR-0020 §3). `None` is the
        answer that makes `_async_defer` drop instead of queueing: there is no
        instant to arm a timer on and none to put in `explain`'s `until`.
        """
        if person.wake_time is not None:
            return next_wake_time(dt_util.now(), person.wake_time)
        return self.configured_silence_end(person)

    def has_configured_silence(self, person: PersonConfig) -> bool:
        """Return True when one of the person's own silence entities is `on`."""
        return any(
            (state := self.hass.states.get(entity_id)) is not None
            and state.state == STATE_ON
            for entity_id in person.silence_entities
        )

    @property
    def critical_payload_enabled(self) -> bool:
        """Return whether the Companion critical keys are added (ADR-0021 §7).

        `entry.options["critical_payload"]` is a boolean whose default is
        **true**, and an absent key means true -- so no migration and no
        options rewrite. Only an explicit `False` turns it off, and turning it
        off never puts `data.priority` back: the strip of §7(a) is
        unconditional.
        """
        return self.entry.options.get(CONF_CRITICAL_PAYLOAD, True) is not False

    def notify_entity_id(self, output: str) -> str | None:
        """Return the `notify` entity id this output resolves to, or None (§6).

        A legacy notify service and a notify entity share one namespace, so the
        order has to be stated rather than discovered: **a registered service
        wins**, which is exactly today's behaviour for every output that exists
        today. Only an output that is not a registered service, and that is in
        the `notify` domain, is looked up as an entity.

        The router resolves the entity itself rather than calling and hoping.
        `notify.send_message` is an entity service: an `entity_id` that
        resolves to nothing is **logged and skipped**
        (`$HA_CORE_SRC/homeassistant/helpers/service.py`,
        `_resolve_entity_service_call_entities` at line 675, its
        `referenced.log_missing(...)` at line 730), and one that exists but is
        `unavailable` is filtered out of the candidates at line 722. Either way
        the call succeeds and nothing is delivered, so a router that did not
        check would count a delivery that never happened.
        """
        domain, _, service = output.rpartition(".")
        if (domain or NOTIFY_DOMAIN) != NOTIFY_DOMAIN:
            return None
        entity_id = f"{NOTIFY_DOMAIN}.{service}"
        state = self.hass.states.get(entity_id)
        if state is None or state.state == STATE_UNAVAILABLE:
            return None
        return entity_id

    def output_is_reachable(self, output: str) -> bool:
        """Return True when an output resolves to a service or a notify entity."""
        domain, _, service = output.rpartition(".")
        domain = domain or NOTIFY_DOMAIN
        if self.hass.services.has_service(domain, service):
            return True
        return self.notify_entity_id(output) is not None

    def companion_os_name(self, service: str) -> str | None:
        """Return the `os_name` of the registration behind a Companion output.

        The output service name is `slugify(f"mobile_app_{device_name}")`
        (`$HA_CORE_SRC/homeassistant/components/notify/legacy.py`), which is
        what `companion_service_name` composes, so the match is against the
        `device_name` of each `mobile_app` config entry -- the same entry data
        the router already reads `user_id` from. `None` is "no matching
        registration, or one that declares no OS", which
        `router.critical_keys_for_os` answers with both key sets.
        """
        for entry in self.hass.config_entries.async_entries(MOBILE_APP_DOMAIN):
            device_name = entry.data.get("device_name")
            if not device_name:
                continue
            if companion_service_name(str(device_name)) != service:
                continue
            os_name = entry.data.get(ATTR_OS_NAME)
            return str(os_name) if os_name else None
        return None

    def temporary_silence_until(self, person: PersonConfig) -> datetime | None:
        """Return when a temporary silence lifts, or None when there is none."""
        until = self.store.silences.get(person.entity_id)
        if until is None or until <= dt_util.utcnow():
            return None
        return until

    # ------------------------------------------------------------------
    # Inbound requests
    # ------------------------------------------------------------------

    async def async_handle_request(
        self,
        message: str,
        *,
        title: str | None = None,
        targets: list[str] | None = None,
        data: Mapping[str, Any] | None = None,
    ) -> RoutingDecision:
        """Route one inbound `notify.switchboard[_<slug>]` call."""
        slugs = tuple(targets) if targets else ()
        if not slugs:
            slugs = (self.table.default_target,) if self.table.default_target else ()

        request = NotificationRequest(
            message=message,
            title=title,
            targets=slugs,
            data=dict(data or {}),
        )
        decision, _outputs = await self._async_route(request)
        return decision

    async def _async_route(
        self, request: NotificationRequest
    ) -> tuple[RoutingDecision, set[str]]:
        """Decide and apply one request, returning the outputs it reached.

        The second half of the pair is what §6 needs and `async_handle_request`
        has never had to expose: `clear_done` clears the `done` message on the
        Companion outputs that *received* it, which nothing but the delivery
        itself can know.
        """
        decision = decide(self.table, request, self.build_context())
        delivered = await self._async_apply(request, decision)
        return decision, delivered

    async def _async_apply(
        self, request: NotificationRequest, decision: RoutingDecision
    ) -> set[str]:
        """Perform the side effects of a decision, and report what it reached."""
        self.decision_log.append(
            {
                "at": dt_util.utcnow().isoformat(),
                "targets": list(request.targets),
                "message": request.message,
                "routed": [
                    {"person": item.person, "slug": item.slug}
                    for item in decision.routed
                ],
                "dropped": [
                    {
                        "person": item.person,
                        "slug": item.slug,
                        "reason": item.reason,
                    }
                    for item in decision.dropped
                ],
            }
        )

        store_dirty = False
        for drop in decision.dropped:
            if drop.reason == DROP_UNKNOWN_TARGET:
                self._async_report_unknown_target(drop.slug)

            if (
                drop.reason == DROP_SILENCED
                and drop.person is not None
                and self._async_defer(request, drop.person, drop.slug)
            ):
                store_dirty = True
                continue

            self._async_count_drop(drop.reason, drop.person, drop.slug)

        delivered = await self._async_deliver_all(
            decision, request.message, request.title
        )

        if store_dirty or self._episodes_dirty:
            self._episodes_dirty = False
            await self.store.async_save()

        self._async_notify_entities()
        return delivered

    async def async_send_test_message(self, slug: str) -> None:
        """Route one translated test message through the real routing path.

        ADR-0018 §6: a dry run proves nothing about an output. This is an
        ordinary request -- counted, evented, deferred or dropped like any
        other -- distinguished only by the public `data.tag` the contract
        freezes, which is what lets a user, an automation or a Companion
        channel tell a test from the real thing. The title is left to the
        row's `default_title`, exactly as for any caller that supplies none.
        """
        await self.async_handle_request(
            await self._async_test_message(),
            targets=[slug],
            data={ATTR_TAG: TEST_MESSAGE_TAG},
        )

    def target_for_person(self, person_id: str) -> str | None:
        """Return the slug of the row that would reach `person_id`, if any.

        ADR-0018 §6: the default target first, when that person is in its
        audience, otherwise the first row in stored order whose audience
        contains them. `None` means no row reaches this person at all, which is
        what the `test_person` step aborts on.
        """
        default = self.table.default_target
        if default is not None:
            target = self.table.targets.get(default)
            if target is not None and person_id in target.audience:
                return default
        for slug, target in self.table.targets.items():
            if person_id in target.audience:
                return slug
        return None

    # ------------------------------------------------------------------
    # `explain` -- a read-only answer (contract v0.4, ADR-0018 §1)
    # ------------------------------------------------------------------

    async def async_explain(
        self, slug: str, priority: str | None = None, person: str | None = None
    ) -> dict[str, Any]:
        """Answer what would happen to a message sent right now.

        A pure evaluation: `build_context()` and `router.decide`, and nothing
        else. No `notify.*` call, no counter, no `event.switchboard_delivery`,
        no queued deferral, no stored snooze, no `Store.async_save`. A card that
        calls this on every render must not inflate the day's figures, and
        somebody running it to *understand* their configuration must not change
        it.

        One caveat on "pure": `build_context()` drops snoozes and temporary
        silences whose end time has passed from `Store.snoozes` / `.silences`.
        That is an in-memory tidy of entries that already expired -- it changes
        no answer, and nothing is written, since `Store.async_save` is only ever
        called by the paths that add or lift one.

        The refusals are the ones every other service raises (ADR-0015), with
        one deliberate difference from `_require_target` / `_require_person`:
        nothing here feeds the `invalid_service_*` counters. Asking a question
        with a stale slug is a question, not an attempt to act.
        """
        target = self.table.targets.get(slug)
        if target is None:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key=ERROR_UNKNOWN_TARGET,
                translation_placeholders={"target": slug},
            )
        if person is not None and person not in self.table.persons:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key=ERROR_UNKNOWN_PERSON,
                translation_placeholders={"person": person},
            )

        data: dict[str, Any] = {} if priority is None else {ATTR_PRIORITY: priority}
        context = self.build_context()
        # ADR-0021 §8: `priority` reports the **escalated** priority, because
        # `explain` answers "what would happen to a message sent right now" and
        # right now the escalation is part of that. `escalated` names the rule
        # that changed it, and is `null` when nothing did.
        effective, escalated = effective_priority(target, data, context)
        # The message is never sent and never read: `decide` does not look at it.
        decision = decide(
            self.table,
            NotificationRequest(message="", targets=(slug,), data=data),
            context,
        )

        routed = {item.person: item for item in decision.routed if not item.is_bare}
        dropped: dict[str | None, str] = {}
        for drop in decision.dropped:
            if drop.output is None:
                dropped.setdefault(drop.person, drop.reason)

        # `persons` stays a mapping of `person.*` entity ids: a bare output is
        # not a person and never appears there (ADR-0021 §5). It is listed under
        # the top-level `outputs` key instead, because it has no person to hang
        # off.
        wanted = [person] if person is not None else list(target.audience_persons)
        persons: dict[str, Any] = {}
        for person_id in wanted:
            persons[person_id] = await self._async_explain_person(
                target,
                person_id,
                routed.get(person_id),
                dropped.get(person_id),
                context,
                priority=effective,
            )

        return {
            ATTR_TARGET: slug,
            ATTR_PRIORITY: effective,
            ATTR_PERSONS: persons,
            ATTR_ESCALATED: escalated,
            ATTR_OUTPUTS: list(target.bare_outputs),
        }

    async def _async_explain_person(
        self,
        target: TargetConfig,
        person_id: str,
        routed: RoutedDelivery | None,
        reason: str | None,
        context: RoutingContext,
        *,
        priority: str,
    ) -> dict[str, Any]:
        """Turn one person's outcome into the frozen six-key answer.

        `priority` is the effective one, escalation included: it is what
        decides which of this person's `on` silence entities actually catch the
        message, and therefore what the `detail` sentence has to name.
        """
        person = self.table.persons.get(person_id)
        reachable, missing = self._split_registered_outputs(person)

        if routed is not None:
            return {
                ATTR_DECISION: DECISION_ROUTED,
                ATTR_UNTIL: None,
                ATTR_REASON: None,
                ATTR_DETAIL: await self._async_detail(
                    DECISION_ROUTED,
                    target,
                    person_id,
                    person,
                    context,
                    priority=priority,
                    outputs=reachable,
                ),
                ATTR_OUTPUTS: reachable,
                ATTR_MISSING_OUTPUTS: missing,
            }

        # A person the answer was asked about but who is neither routed nor
        # dropped is not in this row's audience -- `decide` only walks the
        # persons it knows, and an explicit `person` may be one of those.
        reason = reason or DROP_NOT_IN_AUDIENCE

        if reason == DROP_SILENCED and (until := self._deferral_until(person)):
            return {
                ATTR_DECISION: DECISION_DEFERRED,
                ATTR_UNTIL: until.isoformat(),
                ATTR_REASON: None,
                ATTR_DETAIL: await self._async_detail(
                    DECISION_DEFERRED,
                    target,
                    person_id,
                    person,
                    context,
                    priority=priority,
                    until=until,
                ),
                ATTR_OUTPUTS: reachable,
                ATTR_MISSING_OUTPUTS: missing,
            }

        return {
            ATTR_DECISION: DECISION_DROPPED,
            ATTR_UNTIL: None,
            ATTR_REASON: reason,
            ATTR_DETAIL: await self._async_detail(
                reason, target, person_id, person, context, priority=priority
            ),
            # Nothing would be called, so there is nothing to list (ADR-0018
            # §1). `missing_outputs` is still reported: a broken output is worth
            # knowing about even for somebody who is currently snoozed.
            ATTR_OUTPUTS: [],
            ATTR_MISSING_OUTPUTS: missing,
        }

    def _deferral_until(self, person: PersonConfig | None) -> datetime | None:
        """Return the instant `_async_defer` would queue this person until.

        `None` means it would drop instead. Deliberately the same conditions
        the dispatcher applies, so `explain` can never promise a deferral the
        router would not make: one of the person's *configured* silence
        entities is on (a temporary `notify_switchboard.silence` is not a
        night), and the night has a known end -- their `wake_time`, or what
        their silence publishes (ADR-0020 §3). The priority is not `critical`
        by construction, since a critical message is never dropped for silence
        in the first place.
        """
        if person is None or not self.has_configured_silence(person):
            return None
        return self.deferral_until(person)

    def _split_registered_outputs(
        self, person: PersonConfig | None
    ) -> tuple[list[str], list[str]]:
        """Split a person's usable outputs into (registered, missing).

        Both lists carry **full** `notify.*` service names: everywhere else an
        output is stored bare because that is what the router compares, but
        `explain` is read by a human or by a card and the useful answer to
        "where would this go" is something you can paste into Developer tools
        (ADR-0018 §1). Recursive outputs appear in neither: they are refused,
        not absent.

        "Registered" means reachable, which from 0.7.0 is a registered legacy
        service **or** an available `notify` entity (ADR-0021 §6).
        """
        if person is None:
            return [], []
        usable, _recursive = split_outputs(person.outputs)
        registered: list[str] = []
        missing: list[str] = []
        for output in usable:
            domain, _, service = output.rpartition(".")
            domain = domain or NOTIFY_DOMAIN
            full = f"{domain}.{service}"
            # ADR-0021 §6: an output that is not a registered service may still
            # be an available `notify` entity, and one that is is reachable.
            # An entity id in no state machine, or an `unavailable` one, is a
            # missing output exactly as an unregistered service is.
            if self.output_is_reachable(output):
                registered.append(full)
            else:
                missing.append(full)
        return registered, missing

    async def _async_detail(
        self,
        key: str,
        target: TargetConfig,
        person_id: str,
        person: PersonConfig | None,
        context: RoutingContext,
        *,
        priority: str,
        outputs: list[str] | None = None,
        until: datetime | None = None,
    ) -> str:
        """Return the translated sentence that names what decided.

        `key` is either a decision (`routed`, `deferred`) or a drop reason, so a
        reason the contract adds cannot silently lose its sentence: it falls
        back to the generic `detail_dropped` and stays non-empty.

        `person_id` is passed separately from `person` because the one reason
        the table has no `PersonConfig` -- `unknown_person`, a hand-edited
        audience -- is also the one whose sentence exists to name whom it is
        about. Deriving `{person}` from `person` alone left it empty exactly
        there.
        """
        translations = await self._async_translations()
        selectors = await self._async_selector_translations()
        placeholders: dict[str, str] = {
            "target": target.name or target.slug,
            # v0.7.1: a sentence a household reads names people the way the
            # household does. `unknown_person` is the exception below -- there,
            # the id is the thing to go and fix.
            "person": friendly_name(self.hass, person_id),
            "reason": key,
            # ... and names a coded choice with the words the picker offered
            # when it was made, rather than with the value the row stores:
            # "its rule is home_only" is the router explaining itself to
            # itself. Every reason now has a `detail_` sentence of its own, so
            # `{reason}` reaches nobody; it stays for the day the contract adds
            # one, which is the whole point of the `detail_dropped` fallback.
            "rule": selector_label(
                selectors, SELECTOR_PRESENCE_RULE, target.presence_rule
            ),
            "state": _presence_label(
                translations, context.person_states.get(person_id, "") or STATE_UNKNOWN
            ),
            # ... and names devices the way the outputs picker does, from the
            # same builder. The `outputs` key of the answer keeps the full
            # `notify.*` service names a script pastes into Developer tools
            # (ADR-0018 §1); only this sentence is rewritten.
            "outputs": self._output_names(outputs or (), translations),
            "until": _local_text(until),
        }

        if key == DROP_SILENCED:
            catching = self._silences_catching(person, context, priority)
            if not catching:
                # No configured entity catches this call, so what silences this
                # person is a temporary `notify_switchboard.silence`: name when
                # it lifts rather than a switch they would look for and not
                # find.
                key = DETAIL_SILENCED_TEMPORARY
                placeholders["until"] = _local_text(
                    self.temporary_silence_until(person) if person else None
                )
            else:
                placeholders["entities"] = ", ".join(
                    named_entity(self.hass, entity_id) for entity_id in catching
                )
                # ADR-0021 §2: naming only the entity leaves the user unable to
                # tell why the `high` message got through and the `normal` one
                # did not, so a floored silence gets a sentence that names the
                # floor as well. Only when *every* catching entity carries one:
                # one floor-less silence among them catches everything, and
                # quoting a floor there would be a half-truth.
                floors = [context.silenced[entity_id] for entity_id in catching]
                if all(floor is not None for floor in floors):
                    key = DETAIL_SILENCED_FLOOR
                    placeholders["floor"] = selector_label(
                        selectors,
                        SELECTOR_PRIORITY,
                        max(
                            (floor for floor in floors if floor is not None),
                            key=lambda floor: PRIORITY_RANK[floor],
                        ),
                    )
        elif key == DECISION_DEFERRED:
            placeholders["entities"] = ", ".join(
                named_entity(self.hass, entity_id)
                for entity_id in self._silence_entities_on(person, context)
            )
        elif key == DROP_SNOOZED and person is not None:
            placeholders["until"] = _local_text(
                context.snoozes.get((person.entity_id, target.slug))
            )

        if key == DROP_UNKNOWN_PERSON:
            # The one sentence whose whole point is to name somebody the table
            # does not know: the id is what a hand-edited audience holds, and
            # what the user has to correct.
            placeholders["person"] = named_entity(self.hass, person_id)

        template = translations.get(
            f"{KEY_DETAIL_PREFIX}{key}",
            translations.get(f"{KEY_DETAIL_PREFIX}dropped", FALLBACK_DETAIL),
        )
        return _fill(template, placeholders)

    def _output_names(
        self, outputs: Iterable[str], translations: Mapping[str, str]
    ) -> str:
        """Name a list of `notify.*` services the way a household would.

        The labels are the ones the `outputs` picker offers, so the phone
        somebody ticked as "Bob's iPhone" is still "Bob's iPhone" in the
        sentence that says where a message went. The words those labels are
        built from come out of `common`, which `_async_translations` fetches in
        **the instance language** (`hass.config.language`) -- a user whose own
        interface is in another language reads this sentence in the
        instance's, which is why the test-result step says so.
        """
        texts = {
            name: translations.get(
                f"component.{DOMAIN}.{TRANSLATION_CATEGORY}.{name}", fallback
            )
            for name, fallback in OUTPUT_LABEL_FALLBACKS.items()
        }
        devices = companion_device_names(self.hass)
        return ", ".join(
            output_label(service.rpartition(".")[2], devices, texts)
            for service in outputs
        )

    def _silence_entities_on(
        self, person: PersonConfig | None, context: RoutingContext
    ) -> list[str]:
        """Return the person's configured silence entities that are `on`.

        Only those: naming a silence entity that is `off` sends the user to the
        wrong switch, which is the one thing this sentence exists to avoid.
        """
        if person is None:
            return []
        return [
            entity_id
            for entity_id in person.silence_entities
            if entity_id in context.silenced
        ]

    def _silences_catching(
        self, person: PersonConfig | None, context: RoutingContext, priority: str
    ) -> list[str]:
        """Return the person's `on` silences that catch a call at `priority`.

        Narrower than `_silence_entities_on` from 0.7.0, and for the same
        reason it existed in the first place: with a floor in play, an entity
        that is on but lets this call through is not the switch the user has to
        look at (ADR-0021 §2).
        """
        if person is None:
            return []
        return silences_catching(person, context, priority)

    # ------------------------------------------------------------------
    # Delivery
    # ------------------------------------------------------------------

    async def _async_deliver_all(
        self, decision: RoutingDecision, message: str, title: str | None
    ) -> set[str]:
        """Deliver every routed message of one decision, concurrently.

        Contract v0.3 §"Fan-out guarantees" (ADR-0017 §3): the persons of one
        decision are served at the same time, so the wall time of a decision is
        bounded by its slowest single output rather than by the sum of them all.
        `return_exceptions=True` is the shape core itself uses when one member
        of a fan-out must not abort the others
        (`homeassistant/helpers/entity_platform.py`, `async_add_entities`;
        `homeassistant/core.py`, the shutdown-jobs gather).

        Counts and per-person outcomes are promised; the order of the resulting
        `event.switchboard_delivery` events is explicitly not.
        """
        delivered: set[str] = set()
        if not decision.routed:
            return delivered

        results = await asyncio.gather(
            *(
                self._async_deliver(routed, message, title)
                for routed in decision.routed
            ),
            return_exceptions=True,
        )
        for routed, result in zip(decision.routed, results, strict=True):
            if isinstance(result, BaseException):
                _LOGGER.exception(
                    "Unexpected error while delivering %s to %s",
                    routed.slug,
                    routed.person,
                    exc_info=result,
                )
                # `_async_deliver` accounts for every person it handles, so
                # one that raised before doing so would leave the counters
                # short: neither routed nor dropped. Nothing reached that
                # person, which is the same outcome as every output failing,
                # so it gets the same reason rather than one of its own.
                self._async_count_drop(DROP_DELIVERY_FAILED, routed.person, routed.slug)
                continue
            delivered.update(result)
        return delivered

    async def _async_deliver(
        self, routed: RoutedDelivery, message: str, title: str | None
    ) -> tuple[str, ...]:
        """Deliver one routed message to every output of one person.

        Returns the outputs that actually answered, which is what an episode
        records and what `clear_done` later clears (ADR-0019 §5 and §6).
        """
        target = self.table.targets.get(routed.slug)
        if target is None:
            return ()

        # Contract §"Per-row texts": `default_title` is the outgoing title
        # whenever the caller did not supply one. Applied here, per delivery,
        # rather than on the request, so a call fanned out over several rows
        # gets each row's own default.
        if title is None:
            title = target.default_title

        payload = await self._async_build_payload(target, routed)
        # Whether the tag in that payload is the router's own default or a name
        # the caller (or the row's `default_data`) wrote: only the first kind is
        # scoped to the outputs that read it.
        router_tag = caller_tag(routed.data) is None
        # Every output of this person at once, each bounded by its own timeout:
        # a phone off the network must not hold back the tablet next to it. A
        # bare output has exactly one, and this loop is the same one.
        outcomes = await asyncio.gather(
            *(
                self._async_call_output(
                    output,
                    message,
                    title,
                    payload,
                    target.slug,
                    router_tag=router_tag,
                    priority=routed.priority,
                    bare=routed.is_bare,
                )
                for output in routed.outputs
            ),
            return_exceptions=True,
        )
        delivered = tuple(
            output
            for output, outcome in zip(routed.outputs, outcomes, strict=True)
            if outcome is True
        )

        if not delivered:
            # Every output of this person failed or does not exist: the
            # message reached nobody, so it is a drop, not a delivery.
            # Counting it as routed would make the daily figure a count of
            # *intentions* rather than of notifications that went out.
            self._async_count_drop(DROP_DELIVERY_FAILED, routed.person, routed.slug)
            return ()

        self._async_record_episode(target, routed, payload, delivered)
        self.routed_today += 1
        if routed.person is not None:
            # A bare output is nobody's phone, so there is no
            # `sensor.<person>_last_notification` for it to move (ADR-0021 §5).
            self.last_notification[routed.person] = dt_util.utcnow()
        self._async_fire_delivery_event(
            EVENT_TYPE_ROUTED,
            {
                "person": routed.person,
                "target": routed.slug,
                "priority": routed.priority,
                "delivered": True,
            },
        )
        return delivered

    @callback
    def _async_record_episode(
        self,
        target: TargetConfig,
        routed: RoutedDelivery,
        payload: Mapping[str, Any],
        delivered: tuple[str, ...],
    ) -> None:
        """Remember that this delivery belonged to the row's open episode.

        Only a **delivered** message counts: somebody whose message was dropped,
        or deferred and not yet flushed, was not told about the leak and must
        not be told it is over (ADR-0019 §5). The episode is closed before the
        `done` message is routed, so the `done` message is never recorded into
        the episode it closes -- which is what lets `clear_done: false` keep it
        on the phone while the episode's own notifications are cleared.
        """
        episode = self.store.episodes.get(target.slug)
        if episode is None or not episode.is_open:
            return
        # The audience entry, not the person: a bare output is an episode
        # recipient like any other (ADR-0021 §5), and what `decide` filters a
        # `done` message against is the entry as the audience spells it.
        episode.persons.add(routed.audience_entry)
        episode.outputs.update(delivered)
        episode.tags.add(str(payload[ATTR_TAG]))
        self._episodes_dirty = True

    async def _async_build_payload(
        self, target: TargetConfig, routed: RoutedDelivery
    ) -> dict[str, Any]:
        """Build the merged `data` payload, tag and buttons included.

        ADR-0019 §6: every message acquires a deterministic identity, because a
        notification you cannot name is one you can never clear. A caller's own
        `data.tag` always wins; the default only fills a gap.

        This is the router's *internal* view of the message -- what the episode
        record and the clear logic reason about. It is not what an output
        receives: `_async_call_output` keeps each router-added key for the
        outputs that read it and drops it for the others (§6, amendment
        2026-09-07 (2)).
        """
        payload = dict(routed.data)
        payload[ATTR_TAG] = effective_tag(target.slug, routed.data)
        authenticate = routed.priority in AUTHENTICATED_PRIORITIES
        labels = await self._async_labels(target)
        actions = build_actions(target, labels, authenticate)
        if actions:
            payload[ATTR_ACTIONS] = actions
        if authenticate:
            payload[ATTR_AUTHENTICATION_REQUIRED] = True
        return payload

    def _scope_output_data(
        self,
        payload: Mapping[str, Any],
        service: str,
        *,
        router_tag: bool,
        priority: str | None,
        bare: bool,
    ) -> dict[str, Any]:
        """Return the `data` this one output actually receives.

        ADR-0019 §6, amendment 2026-09-07 (2): the router is a proxy
        (ADR-0002), so an output receives the caller's `data` merged with the
        row's `default_data` and nothing else. The keys the router adds for
        itself are scoped here, per output -- never on the shared payload,
        which the episode record and the clear logic still read whole. Not
        cosmetic: a sibling adapter that validates its `data` (AirPlay
        Notifier's voluptuous schema, `PREVENT_EXTRA` by default; Assist
        Satellite Notifier's `ALLOWED_DATA_KEYS`) raises
        `ServiceValidationError` on a key it does not know, so a router key
        sent to one of them fails every single call.
        """
        data = dict(payload)
        companion = service.startswith(COMPANION_OUTPUT_PREFIX)
        persistent = service == PERSISTENT_NOTIFICATION_OUTPUT
        if bare or not companion:
            # Companion buttons only make sense on a Companion output -- and a
            # bare output is nobody's phone, so it gets none of them even when
            # it is one (ADR-0021 §5).
            data.pop(ATTR_ACTIONS, None)
            data.pop(ATTR_AUTHENTICATION_REQUIRED, None)
            # `tag` is read by the Companion app and, below, as the source of
            # the `persistent_notification` id. Anywhere else it is a key the
            # router invented. A tag the *caller* wrote is the caller's own key
            # and is proxied like any other.
            if router_tag and (bare or not persistent):
                data.pop(ATTR_TAG, None)
        if companion:
            self._apply_companion_payload(data, priority, service)
        # `data.notification_id` mirrors the effective tag, and is added for the
        # bare `persistent_notification` output only -- the one core documents
        # as reading it (`components/notify/__init__.py`, the
        # `persistent_notification` service handler: `notification_id =
        # data.get(pn.ATTR_NOTIFICATION_ID)`, then `pn.async_create(...)`).
        # Every other output would receive a key it has no use for. A
        # caller-supplied value wins here too, hence the membership test.
        if not bare and persistent and ATTR_NOTIFICATION_ID not in data:
            tag = data.get(ATTR_TAG)
            if tag is not None:
                data[ATTR_NOTIFICATION_ID] = str(tag)
        return data

    async def _async_call_unregistered_output(
        self,
        output: str,
        domain: str,
        service: str,
        *,
        message: str,
        title: str | None,
        slug: str,
    ) -> bool:
        """Handle an output that is not a registered legacy service (§6).

        It may still be a `notify` **entity** -- Alexa Devices, Telegram, a
        core `NotifyGroup` -- in which case `message` and `title` are the only
        things that survive the trip. Anything else is a missing output, with
        the same counter, the same repair and the same `delivery_failed` drop
        an unregistered service has always produced.
        """
        if (entity_id := self.notify_entity_id(output)) is not None:
            return await self._async_call_notify_entity(
                output, entity_id, message, title, slug
            )
        self._async_record_output_failure(output)
        _LOGGER.warning(
            "Output %s.%s is neither a registered service nor an available "
            "notify entity (yet); will retry on the next call",
            domain,
            service,
        )
        return False

    async def _async_call_output(
        self,
        output: str,
        message: str,
        title: str | None,
        payload: Mapping[str, Any],
        slug: str,
        *,
        router_tag: bool,
        priority: str | None = None,
        bare: bool = False,
    ) -> bool:
        """Call one `notify.*` output; never let a failure stop the others.

        `router_tag` says whether `payload["tag"]` is the router's own default
        rather than a value the caller (or the row's `default_data`) wrote. A
        router key is scoped to the outputs that read it; a caller key is
        proxied to all of them (ADR-0019 §6, amendment 2026-09-07 (2)).

        `bare` says this output is an audience entry of its own rather than one
        of a person's phones (ADR-0021 §5): it receives exactly the caller's
        `data` merged with the target's `default_data` and nothing the router
        invented, even when it happens to be a Companion service. What it does
        *not* escape is §7 -- the critical payload is a property of the
        service, not of the audience entry.

        `priority` is the **effective** priority of this message, after the
        escalation of §1. `None` means "this is not a routed message" -- a
        wake-time summary, whose `data` is built rather than merged and which
        can never be critical, since a critical message is never deferred.
        """
        if is_recursive_output(output):
            _LOGGER.error(
                "Refusing to call %s: an output pointing back at the switchboard "
                "would recurse",
                output,
            )
            return False

        domain, _, service = output.rpartition(".")
        domain = domain or NOTIFY_DOMAIN

        if not self.hass.services.has_service(domain, service):
            return await self._async_call_unregistered_output(
                output, domain, service, message=message, title=title, slug=slug
            )

        service_data: dict[str, Any] = {"message": message}
        if title is not None:
            service_data["title"] = title
        data = self._scope_output_data(
            payload, service, router_tag=router_tag, priority=priority, bare=bare
        )
        if data:
            service_data["data"] = data

        try:
            # `blocking=True` is a direct `await` of the handler's coroutine
            # (`homeassistant/core.py`, `ServiceRegistry.async_call`: "response_data
            # = await coro"), so cancelling here abandons the call instead of
            # leaving a detached task running behind it. For a coroutine handler
            # that really is a cancellation. For a *legacy* notify platform
            # whose `send_message` is synchronous it is not: core wraps it in
            # `hass.async_add_executor_job`
            # (`homeassistant/components/notify/legacy.py`,
            # `BaseNotificationService.async_send_message`), and an executor
            # thread cannot be cancelled -- the await is abandoned, the thread
            # runs to completion on its own. Either way this coroutine stops
            # waiting after `OUTPUT_TIMEOUT_SECONDS`, which is what the fan-out
            # guarantee is about.
            async with asyncio.timeout(OUTPUT_TIMEOUT_SECONDS):
                await self.hass.services.async_call(
                    domain, service, service_data, blocking=True
                )
        except TimeoutError:
            # ADR-0017 §3: a timeout is recorded exactly like any other failed
            # output -- same counter, same repair, same `delivery_failed` drop
            # when every output of the person failed. No new drop reason.
            _LOGGER.warning(
                "Output %s.%s did not answer within %s s for target %s; abandoned",
                domain,
                service,
                OUTPUT_TIMEOUT_SECONDS,
                slug,
            )
            self._async_record_output_failure(output)
            return False
        except (HomeAssistantError, vol.Invalid) as err:
            _LOGGER.error(
                "Output %s.%s failed for target %s: %s", domain, service, slug, err
            )
            self._async_record_output_failure(output)
            return False
        except Exception:  # noqa: BLE001 - an output must never break the others
            _LOGGER.exception(
                "Unexpected error from output %s.%s for target %s",
                domain,
                service,
                slug,
            )
            self._async_record_output_failure(output)
            return False

        # The output answered: whatever the repair said about it is no longer
        # true, and nothing else would ever delete a persisted issue. The
        # deletion is unconditional because the issue registry outlives this
        # process while the counter does not -- after a restart the repair is
        # still on screen with an empty `failing_outputs`. Deleting an issue
        # that is not there is a no-op (`issue_registry.async_delete`).
        self.failing_outputs.pop(output, None)
        ir.async_delete_issue(self.hass, DOMAIN, f"missing_output_{output}")
        return True

    def _entity_takes_a_title(self, entity_id: str) -> bool:
        """Return whether a notify entity declares `NotifyEntityFeature.TITLE`.

        Read from the published `supported_features` state attribute rather
        than from the entity object: the router never reaches past a public
        service into another integration's objects (ADR-0021, rejected
        alternatives). An entity that publishes no `supported_features` is
        given the benefit of the doubt and sent the title, because that is the
        case where core's own drop still applies.
        """
        state = self.hass.states.get(entity_id)
        if state is None:
            return False
        features = state.attributes.get(ATTR_SUPPORTED_FEATURES)
        if features is None:
            return True
        return bool(int(features) & NotifyEntityFeature.TITLE)

    @callback
    def _apply_companion_payload(
        self, data: dict[str, Any], priority: str | None, service: str
    ) -> None:
        """Fix up the `data` a Companion output receives (ADR-0021 §7).

        Two changes, and to no other kind of output.

        **(a) The router's own `priority` key is stripped. Unconditionally.**
        `data.priority` is a router *input* -- it selects the effective
        priority -- and has never been a Companion key. `mobile_app` on Android
        reads `data.priority` and knows one value, `high`; on iOS it means
        nothing at all. It is removed whatever the priority is and whatever the
        option below says, which is the one breaking change of 0.7.0.

        **(b) When the effective priority is `critical`, the Companion keys are
        added**, translated for the OS the registration declares. A key the
        caller (or the target's `default_data`) already wrote is never
        overwritten, and `push` counts as a **single** caller key: if the
        caller supplied any `push` mapping the router adds nothing under it,
        which is how a household that prefers
        `push: {interruption-level: critical}` writes it. Merging into a nested
        mapping the caller wrote is where a rule like this stops being
        predictable.

        `priority` is the one exception to "caller wins", and (a) is why: it is
        stripped before (b) runs, so the router's `priority: high` is never
        contending with a caller's routing priority.
        """
        data.pop(ATTR_PRIORITY, None)
        if priority != PRIORITY_CRITICAL or not self.critical_payload_enabled:
            return
        for key, value in critical_keys_for_os(self.companion_os_name(service)).items():
            data.setdefault(key, value)

    async def _async_call_notify_entity(
        self,
        output: str,
        entity_id: str,
        message: str,
        title: str | None,
        slug: str,
    ) -> bool:
        """Deliver one message through `notify.send_message` (ADR-0021 §6).

        `message` and `title` and nothing else: `NotifyEntity.async_send_message`
        takes those two
        (`$HA_CORE_SRC/homeassistant/components/notify/__init__.py` line 185)
        and the entity service schema accepts only those two (lines 84-91).

        `title` is sent only to an entity that declares
        `NotifyEntityFeature.TITLE` (line 63). Core's base implementation drops
        it for an entity that does not, and ADR-0021 §6 leaves the decision to
        core on that basis -- but a platform is free to override
        `async_send_message`, and one that does never reaches the base
        implementation that would have dropped it. Reading the published
        `supported_features` and declining to send the key is the same outcome
        for an entity that inherits the base behaviour and the *documented*
        outcome for one that does not. An entity that publishes no
        `supported_features` at all is sent the title and core decides, which
        is the ADR's rule where it can still apply.

        A target whose output is an entity therefore cannot carry
        `default_data` to it, cannot carry a caller's `data`, and gets no tag,
        no buttons and no critical payload. That is the same Home Assistant
        limitation the contract already records for this integration's own
        degraded `notify.switchboard` entity, stated in the other direction.

        Failures are accounted for exactly as a service call's are: same
        counter, same repair, same `delivery_failed` when it was a person's
        only output.
        """
        service_data: dict[str, Any] = {ATTR_ENTITY_ID: entity_id, "message": message}
        if title is not None and self._entity_takes_a_title(entity_id):
            service_data["title"] = title
        try:
            async with asyncio.timeout(OUTPUT_TIMEOUT_SECONDS):
                await self.hass.services.async_call(
                    NOTIFY_DOMAIN, SERVICE_SEND_MESSAGE, service_data, blocking=True
                )
        except TimeoutError:
            _LOGGER.warning(
                "Notify entity %s did not answer within %s s for target %s; abandoned",
                entity_id,
                OUTPUT_TIMEOUT_SECONDS,
                slug,
            )
            self._async_record_output_failure(output)
            return False
        except (HomeAssistantError, vol.Invalid) as err:
            _LOGGER.error(
                "Notify entity %s failed for target %s: %s", entity_id, slug, err
            )
            self._async_record_output_failure(output)
            return False
        except Exception:  # noqa: BLE001 - an output must never break the others
            _LOGGER.exception(
                "Unexpected error from notify entity %s for target %s", entity_id, slug
            )
            self._async_record_output_failure(output)
            return False

        self.failing_outputs.pop(output, None)
        ir.async_delete_issue(self.hass, DOMAIN, f"missing_output_{output}")
        return True

    @callback
    def _async_record_output_failure(self, output: str) -> None:
        """Count one consecutive failure of an output and repair if durable.

        An output that exists but keeps raising is exactly as useless as one
        that does not exist, so both feed the same counter and the same
        `repairs` issue: tolerated `MAX_CONSECUTIVE_OUTPUT_MISSES` times (load
        order, a transient push error), reported on the next one. Any success
        clears the counter.
        """
        failures = self.failing_outputs.get(output, 0) + 1
        self.failing_outputs[output] = failures
        if failures > MAX_CONSECUTIVE_OUTPUT_MISSES:
            self._async_report_missing_output(output)

    # ------------------------------------------------------------------
    # Night deferral (brief item 7)
    # ------------------------------------------------------------------

    @callback
    def _async_defer(
        self, request: NotificationRequest, person_id: str, slug: str
    ) -> bool:
        """Queue a silenced message until the person's night ends.

        Returns True when the message was queued (so it must not be counted as
        a drop: nothing is lost, it is simply late).

        Two conditions, and `deferral_until` is the second of them. One of the
        person's *configured* silence entities has to be on -- a temporary
        `notify_switchboard.silence` is not a night: ADR-0016 says such a
        message is dropped with reason `silenced`, and queueing it until
        tomorrow morning because somebody asked for an hour of quiet would be
        the wrong kind of late. And the night has to have a known end: the
        person's `wake_time` as in 0.5.1, or, when they have none, the end
        their silence publishes (ADR-0020 §3). With neither, the message is
        dropped with reason `silenced`, exactly as in 0.1 -> 0.5.
        """
        person = self.table.persons.get(person_id)
        target = self.table.targets.get(slug)
        if person is None or target is None:
            return False

        if not self.has_configured_silence(person):
            return False

        if self.deferral_until(person) is None:
            return False

        # ADR-0019 §6 only means the `tag` half of the `(person, target, tag)`
        # de-duplication key is now always populated: an untagged message keeps
        # de-duplicating against itself exactly as it did, under a name.
        deferral = DeferredMessage(
            person=person_id,
            slug=slug,
            tag=effective_tag(slug, merge_data(target, request.data)),
            message=request.message,
            title=request.title,
            priority=resolve_priority(target, request.data),
            data=dict(request.data),
            queued_at=dt_util.utcnow(),
        )
        self.store.deferrals[deferral.key] = deferral
        self.deferred_today += 1
        self._async_schedule_deferral(person_id)
        _LOGGER.debug(
            "Deferred %s for %s until %s", slug, person_id, self.deferral_until(person)
        )
        return True

    async def _async_catch_up_deferrals(self) -> None:
        """Deliver deferrals whose wake time passed while HA was down.

        Without this, a message queued at 23:30 and reloaded at 09:00 the next
        morning would be rescheduled for the *following* 07:00 and arrive a
        day late. Overdue messages are delivered once at setup; the store is
        keyed on `(person, target, tag)`, so the tag de-duplication still
        holds and nothing is sent twice.
        """
        now = dt_util.now()
        for person_id, person in self.table.persons.items():
            queued = [
                deferral
                for key, deferral in self.store.deferrals.items()
                if key[0] == person_id
            ]
            if not queued:
                continue
            if person.wake_time is None:
                # ADR-0020 §3: this queue is bounded by the end its silence
                # published, and that end has passed exactly when the silence
                # is no longer on. A silence still running holds the queue, and
                # the early flush of ADR-0019 §4 releases it.
                overdue = [] if self.has_configured_silence(person) else queued
            else:
                overdue = [
                    deferral
                    for deferral in queued
                    if next_wake_time(
                        dt_util.as_local(deferral.queued_at), person.wake_time
                    )
                    <= now
                ]
            if overdue:
                _LOGGER.debug(
                    "Delivering %d deferral(s) for %s whose wake time already passed",
                    len(overdue),
                    person_id,
                )
                await self._async_flush_deferrals(person_id, only=overdue)

    @callback
    def _async_schedule_deferral(self, person_id: str) -> None:
        """(Re)schedule the delivery of one person's queued messages.

        Two instants can be predicted, and the timer is armed on whichever of
        them comes first that is still ahead of us:

        * the person's next wake time, or -- when they have none (ADR-0020 §3)
          -- the end their active `silence_entities` publish, the same instant
          `explain` reports as `until`;
        * the end of a temporary `notify_switchboard.silence`, if one is
          running.

        The second one matters because `_async_flush_deferrals` re-checks both
        silences and keeps a message that is still covered. Without it, a flush
        held back by an hour of requested quiet would wait until the *next*
        morning to try again -- and a person with no wake time would wait for
        no morning at all: a temporary silence that outlives the night leaves
        the re-arm reading a schedule that has since gone `off` and publishes
        nothing, so the queue would be left with no timer whatsoever until some
        later night ended. A message with a time to live rarely survives that.

        Only an instant **strictly ahead** of `now` is armed on. A timer that
        fires exactly at the end a schedule published can run before that
        schedule's own state write lands, so the re-arm may still read the end
        that has just passed; arming on it would have
        `async_track_point_in_time` fire again immediately
        (`$HA_CORE_SRC/homeassistant/helpers/event.py`, `_TrackPointUTCTime`
        clamps a past instant to "now"), and the flush and the re-arm would
        chase each other in a loop. Dropping the stale instant leaves the later
        one -- or, when there is none, nothing to wait for, which is what the
        early flush of ADR-0019 §4 is for.

        A configured `silence_entities` going `off` early is not scheduled for
        here -- the router cannot predict when that happens -- but it is no
        longer ignored either: `_async_silence_changed` flushes on the spot when
        the last active one lifts (ADR-0019 §4). `wake_time` stays the upper
        bound, so nothing waits longer than it used to.
        """
        if (unsub := self._deferral_unsubs.pop(person_id, None)) is not None:
            unsub()
        if self._shutdown:
            # `async_cancel_timers` has already run and will not run again:
            # anything armed from here would outlive the entry that owns it.
            return

        person = self.table.persons.get(person_id)
        if person is None:
            return
        if not any(key[0] == person_id for key in self.store.deferrals):
            return

        now = dt_util.now()
        candidates: list[datetime] = []
        if person.wake_time is not None:
            candidates.append(next_wake_time(now, person.wake_time))
        elif (end := self.configured_silence_end(person)) is not None:
            # ADR-0020 §3: no wake time, so the upper bound is the end the
            # silence published. With nothing published there is nothing to
            # arm on from here, and the early flush of ADR-0019 §4 is what
            # releases the queue.
            candidates.append(dt_util.as_local(end))
        if (until := self.store.silences.get(person_id)) is not None:
            candidates.append(dt_util.as_local(until))

        ahead = [instant for instant in candidates if instant > now]
        if not ahead:
            return
        when = min(ahead)

        @callback
        def _deliver(_now: datetime) -> None:
            self._deferral_unsubs.pop(person_id, None)
            self._async_schedule_flush(person_id)

        self._deferral_unsubs[person_id] = async_track_point_in_time(
            self.hass, _deliver, when
        )

    @callback
    def _async_schedule_flush(self, person_id: str) -> None:
        """Run one person's flush in a task of the config entry's own.

        Two of the three entry points into a flush -- the wake-time timer and
        the early flush of ADR-0019 §4; the setup catch-up calls the flush
        inline -- go through here, so a flush never runs *inside* the timer
        sweep or the state write that triggered it. It calls
        `notify.*` services, re-runs the whole decision and writes the store;
        none of that belongs in the middle of somebody else's callback, and
        scheduling it also gives the midnight counter reset and a flush that
        come due at the same instant a defined order.

        The task belongs to the config entry, which means unloading **waits**
        for it rather than cancelling it: `_async_process_on_unload`
        (`homeassistant/config_entries.py`) cancels `_background_tasks` and
        gives `_tasks` ten seconds to finish. That is the behaviour this wants
        -- a flush that has begun pops deferrals from the store and saves them
        gone before it delivers anything, so cancelling it halfway would
        deliver messages the store still lists as queued. A flush that has
        *not* begun stands down instead, on the `_shutdown` flag
        `async_shutdown` sets.

        Ten seconds is less than the thirty a single output may take, so the
        wait is not a guarantee: `_async_flush_deferrals` also stands its own
        tail down on `_shutdown`, for the flush that finishes after the entry
        that owned it is gone.
        """
        if self._shutdown:
            return
        self.entry.async_create_task(
            self.hass,
            self._async_flush_deferrals(person_id),
            name=f"notify_switchboard flush {person_id}",
            eager_start=False,
        )

    async def _async_flush_deferrals(
        self, person_id: str, only: list[DeferredMessage] | None = None
    ) -> None:
        """Re-decide, expire, summarise and deliver one person's queue.

        `only` restricts the flush to a subset (the overdue ones at setup); by
        default everything queued for that person is considered. There are three
        entry points -- the wake-time timer, the early flush of ADR-0019 §4 and
        the catch-up after a restart -- and all three run this, so §1, §2 and §3
        apply identically to each.

        Each queued message goes through, in this order:

        1. **its time-to-live** (§1), read *now* from its stored priority and
           its stored `data`, never frozen at queue time: a message whose time
           has run out is dropped with the reason `expired` and leaves the
           queue, rather than waking somebody up about something that stopped
           mattering hours ago;
        2. **the whole routing decision** (§3), `router.decide` over a fresh
           `build_context()`, with the message's **original** priority written
           back into the rebuilt request so a row whose `default_priority`
           changed overnight cannot silently re-grade it. `silenced` is the one
           outcome that still holds the message and re-arms the flush -- the
           night is not over, which is the whole point of a deferral; every
           other drop is real, and carries the reason that says why;
        3. **the summary** (§2): two or more survivors for a person whose
           `summary` is on become one notification per output instead of one
           per message.
        """
        if self._shutdown:
            _LOGGER.debug("Not flushing %s: the config entry is unloading", person_id)
            return

        pending = sorted(
            only
            if only is not None
            else [
                deferral
                for key, deferral in self.store.deferrals.items()
                if key[0] == person_id
            ],
            key=lambda deferral: deferral.queued_at,
        )
        if not pending:
            return

        person = self.table.persons.get(person_id)
        context = self.build_context()
        survivors, drops, held, refusals = self._triage_deferrals(
            pending, person_id, context
        )

        for deferral, _reason in drops:
            self.store.deferrals.pop(deferral.key, None)
        for deferral, _routed in survivors:
            self.store.deferrals.pop(deferral.key, None)

        self._async_log_flush(person_id, survivors, drops, held, refusals)

        for deferral, reason in (*drops, *refusals):
            self._async_count_drop(reason, person_id, deferral.slug)

        # The pops above are the durable half of a flush, and this is the last
        # moment at which they are certainly safe to write. What follows can
        # take `OUTPUT_TIMEOUT_SECONDS` *per output* -- thirty seconds -- while
        # `_async_process_on_unload` (`homeassistant/config_entries.py`) gives
        # an entry task ten before giving up on it and returning. A flush stuck
        # on one hanging output therefore outlives its own entry, and a reload
        # (an options edit) builds a second `Switchboard` over the same file
        # while this one is still holding an older picture of it. Saving here
        # is what makes that harmless: the messages this flush has taken are on
        # disk before anything can go slow, so the tail below has nothing left
        # it *must* write and can simply stand down.
        if drops or survivors:
            self._episodes_dirty = False
            await self.store.async_save()

        await self._async_deliver_survivors(person, survivors)

        if held:
            _LOGGER.debug(
                "Keeping %d deferral(s) for %s: still silenced at the flush",
                len(held),
                person_id,
            )

        # Unconditional: with something left this re-arms for whichever comes
        # first, the next wake time or the end of a temporary silence; with
        # nothing left it cancels the timer an early flush has just made moot.
        self._async_schedule_deferral(person_id)

        if self._shutdown:
            # The entry unloaded while an output was hanging: `self.store`
            # belongs to a `Switchboard` nobody holds any more, and a reloaded
            # entry may already own the file. Everything durable was written
            # before the first delivery; what would be added here is the
            # episode membership of messages that were delivered anyway, and it
            # is not worth writing a released instance's state over a live one.
            # The entities are gone too, so there is nothing left to refresh.
            _LOGGER.debug(
                "Flush of %s outlived the config entry: leaving the store and "
                "the entities to whoever owns them now",
                person_id,
            )
            return

        # Only the episode membership recorded by the deliveries above is left
        # to persist; the rest went to disk before them.
        if self._episodes_dirty:
            self._episodes_dirty = False
            await self.store.async_save()
        if drops or survivors:
            self._async_notify_entities()

    @callback
    def _async_log_flush(
        self,
        person_id: str,
        survivors: list[tuple[DeferredMessage, RoutedDelivery]],
        drops: list[tuple[DeferredMessage, str]],
        held: list[DeferredMessage],
        refusals: list[tuple[DeferredMessage, str]],
    ) -> None:
        """Write one `decision_log` entry per message this flush re-decided.

        A deferred message is decided twice -- once when it is queued, once
        when it is flushed -- and only the first used to reach the diagnostics.
        The dump a household reads to answer "why did this arrive, why did that
        one not" therefore stopped at the moment the night began, which is
        precisely the window it exists to explain.

        The shape is `_async_apply`'s, so a reader of `last_decisions` does not
        have to learn a second one; `flush: true` is the only addition, and it
        says which of the two decisions on the same message this is. One entry
        per message rather than one per flush, because each queued message is
        re-decided as its own request (§3) and a flush of eleven of them has
        eleven answers.
        """
        # `DeferredMessage.key` is `(person, target, tag)`, the store's own
        # de-duplication key, so it names one queued message exactly.
        refused: dict[tuple[str, str, str], list[str]] = {}
        for deferral, reason in refusals:
            refused.setdefault(deferral.key, []).append(reason)

        at = dt_util.utcnow().isoformat()

        def _append(
            deferral: DeferredMessage, routed: bool, reasons: list[str]
        ) -> None:
            self.decision_log.append(
                {
                    "at": at,
                    "flush": True,
                    "targets": [deferral.slug],
                    "message": deferral.message,
                    "routed": (
                        [{"person": person_id, "slug": deferral.slug}] if routed else []
                    ),
                    "dropped": [
                        {"person": person_id, "slug": deferral.slug, "reason": reason}
                        for reason in reasons
                    ],
                }
            )

        for deferral, _routed in survivors:
            _append(deferral, True, refused.get(deferral.key, []))
        for deferral, reason in drops:
            _append(deferral, False, [reason])
        for deferral in held:
            _append(deferral, False, [DROP_SILENCED])

    def _triage_deferrals(
        self,
        pending: list[DeferredMessage],
        person_id: str,
        context: RoutingContext,
    ) -> tuple[
        list[tuple[DeferredMessage, RoutedDelivery]],
        list[tuple[DeferredMessage, str]],
        list[DeferredMessage],
        list[tuple[DeferredMessage, str]],
    ]:
        """Split a person's queue into (survivors, real drops, held, refusals).

        The time-to-live of §1 first, then the full re-decision of §3. Both are
        read now rather than at queue time, and the single outcome that holds a
        message instead of dropping it is `silenced`.

        A **refusal** is the fourth outcome and the only one that coexists with
        a delivery: it is counted and logged like a drop, but it does not stop
        the message going out and the deferral leaves the queue as a survivor.
        """
        mapping = self.entry.options.get(CONF_TTL_MINUTES)
        survivors: list[tuple[DeferredMessage, RoutedDelivery]] = []
        drops: list[tuple[DeferredMessage, str]] = []
        held: list[DeferredMessage] = []
        refusals: list[tuple[DeferredMessage, str]] = []

        for deferral in pending:
            ttl = resolve_ttl(
                deferral.priority,
                deferral.data,
                mapping if isinstance(mapping, Mapping) else None,
            )
            if ttl is not None and deferral.queued_at + ttl <= context.now:
                drops.append((deferral, DROP_EXPIRED))
                continue

            routed, reason, refused = self._redecide(deferral, person_id, context)
            if routed is not None:
                survivors.append((deferral, routed))
                refusals.extend((deferral, one) for one in refused)
            elif reason == DROP_SILENCED:
                held.append(deferral)
            else:
                drops.append((deferral, reason or DROP_UNKNOWN_TARGET))

        return survivors, drops, held, refusals

    def _redecide(
        self,
        deferral: DeferredMessage,
        person_id: str,
        context: RoutingContext,
    ) -> tuple[RoutedDelivery | None, str | None, tuple[str, ...]]:
        """Run the whole decision again for one queued message (§3).

        The flush stops being a second, weaker decision engine and becomes the
        same one, run later: same `router.decide`, same fresh context, same
        message, same target, and the deferral's own priority written back into
        `data.priority`.

        The third element is the refusals that came back **alongside** a
        delivery. `router.route_person` can produce both at once -- a person
        with one `notify.switchboard*` output among usable ones is routed and
        refused `recursion` in the same breath -- and the live path counts
        both. Returning on the first routed item would throw the refusal away,
        so a loop configured into the table would be invisible on the one path
        that runs while nobody is watching.
        """
        request = NotificationRequest(
            message=deferral.message,
            title=deferral.title,
            targets=(deferral.slug,),
            data={**deferral.data, ATTR_PRIORITY: deferral.priority},
        )
        decision = decide(self.table, request, context)
        refusals = tuple(
            drop.reason
            for drop in decision.dropped
            if drop.output is None and drop.person == person_id
        )
        for item in decision.routed:
            if item.person == person_id:
                return item, None, refusals
        for drop in decision.dropped:
            # `person is None` with no `output` is the `unknown_target` drop:
            # the row this message was queued for has been deleted since. A
            # drop that names an `output` belongs to a bare output of the same
            # target (ADR-0021 §5) and says nothing about this person.
            if drop.output is not None:
                continue
            if drop.person in (person_id, None):
                return None, drop.reason, ()
        return None, None, ()

    async def _async_deliver_survivors(
        self,
        person: PersonConfig | None,
        survivors: list[tuple[DeferredMessage, RoutedDelivery]],
    ) -> None:
        """Send what a flush decided to keep, as a digest or one by one.

        The digest of §2 needs a person who asked for one and more than one
        message to fold into it; anything else is delivered message by message,
        exactly as it would have been at the moment it was queued. An empty
        list is a normal outcome -- everything expired, dropped or still
        silenced -- and sends nothing.
        """
        if not survivors:
            return
        if person is not None and person.summary and len(survivors) > 1:
            await self._async_deliver_summary(person, survivors)
            return
        for deferral, routed in survivors:
            await self._async_deliver(routed, deferral.message, deferral.title)

    async def _async_deliver_summary(
        self,
        person: PersonConfig,
        survivors: list[tuple[DeferredMessage, RoutedDelivery]],
    ) -> None:
        """Deliver one digest instead of a burst of notifications (§2).

        Eleven deferred messages used to be eleven notifications, eleven sounds
        and eleven banners at the exact moment somebody opens their eyes: the
        integration that exists to protect the night was the loudest thing in
        it.

        Messages sharing a `tag` collapse to the last one, across rows. The
        payload is *built*, not merged -- `switchboard-summary`, the union of
        the `switchboard_*` keys, and nothing else -- so no Companion button
        ever lands on a digest, where it could only act on an arbitrary one of
        the messages it summarises.

        Counting follows the lines: each line is one message that reached this
        person, so each one is one `routed` count and one `routed`
        `event.switchboard_delivery`. A message collapsed away is superseded,
        exactly as the queue-time de-duplication on `(person, target, tag)`
        already supersedes one.
        """
        kept: list[tuple[DeferredMessage, RoutedDelivery]] = collapse_by_tag(
            [(deferral.tag, (deferral, routed)) for deferral, routed in survivors]
        )

        translations = await self._async_translations()
        line_template = translations.get(KEY_SUMMARY_LINE, FALLBACK_SUMMARY_LINE)
        untitled_template = translations.get(
            KEY_SUMMARY_LINE_UNTITLED, FALLBACK_SUMMARY_LINE_UNTITLED
        )

        lines: list[str] = []
        for deferral, _routed in kept:
            target = self.table.targets.get(deferral.slug)
            title = deferral.title or (target.default_title if target else None)
            if title:
                lines.append(
                    _fill(line_template, {"title": title, "message": deferral.message})
                )
            else:
                lines.append(_fill(untitled_template, {"message": deferral.message}))

        summary_title = _fill(
            translations.get(KEY_SUMMARY_TITLE, FALLBACK_SUMMARY_TITLE),
            {"count": str(len(lines))},
        )
        payload = summary_data([routed.data for _deferral, routed in kept])

        usable, _recursive = split_outputs(person.outputs)
        outcomes = await asyncio.gather(
            *(
                self._async_call_output(
                    output,
                    "\n".join(lines),
                    summary_title,
                    payload,
                    SUMMARY_TAG,
                    # `switchboard-summary` is a name the router chose for a
                    # message it composed itself, never a caller's.
                    router_tag=True,
                    # A summary carries no critical payload and no `priority`
                    # (ADR-0021 §7): its `data` is *built* rather than merged
                    # (ADR-0019 §2), and a critical message is never deferred,
                    # so there is never a critical one to summarise.
                    priority=None,
                )
                for output in usable
            ),
            return_exceptions=True,
        )
        delivered = tuple(
            output
            for output, outcome in zip(usable, outcomes, strict=True)
            if outcome is True
        )
        if not delivered:
            for deferral, _routed in kept:
                self._async_count_drop(
                    DROP_DELIVERY_FAILED, person.entity_id, deferral.slug
                )
            return

        self.last_notification[person.entity_id] = dt_util.utcnow()
        for deferral, routed in kept:
            # A digest is a delivery, so it is recorded into every episode that
            # contributed a line to it -- with `switchboard-summary` as the tag
            # (ADR-0019 §6, amendment (b)). Without this the person a digest
            # woke would be filtered out of the `done` message by §5's
            # `not_notified` rule, and the digest would stay on their phone
            # after the alert ended.
            if (target := self.table.targets.get(deferral.slug)) is not None:
                self._async_record_episode(
                    target, routed, {ATTR_TAG: SUMMARY_TAG}, delivered
                )
            self.routed_today += 1
            self._async_fire_delivery_event(
                EVENT_TYPE_ROUTED,
                {
                    "person": person.entity_id,
                    "target": deferral.slug,
                    "priority": deferral.priority,
                    "delivered": True,
                },
            )

    # ------------------------------------------------------------------
    # Companion callbacks (brief item 6)
    # ------------------------------------------------------------------

    async def _async_handle_action_event(self, event: Event[dict[str, Any]]) -> None:
        """Handle a `mobile_app_notification_action` event."""
        action = parse_action(event.data.get("action"))
        if action is None:
            return

        user_id = event.context.user_id
        target = self.table.targets.get(action.slug)
        if target is None:
            _LOGGER.warning(
                "Refusing switchboard action %r: unknown target (user_id=%s)",
                event.data.get("action"),
                user_id,
            )
            return

        if action.verb == ACTION_ACKNOWLEDGE:
            await self._async_acknowledge(target, user_id, event.context)
            return

        if action.minutes is not None:
            await self._async_snooze(
                target,
                action.minutes,
                event.data.get("device_id"),
                user_id,
                event.context,
            )

    def _person_for_user_id(self, user_id: str | None) -> str | None:
        """Return the `person.*` whose `user_id` attribute is `user_id`.

        `mobile_app` re-fires a Companion action with the registration's own
        context (`homeassistant/components/mobile_app/webhook.py`,
        `webhook_fire_event` -> `context=registration_context(config_entry.data)`,
        which is `Context(user_id=registration[CONF_USER_ID])` in
        `mobile_app/helpers.py`), and a person entity exposes the user it is
        linked to as a state attribute (`homeassistant/components/person/
        __init__.py`, `PersonEntityStateAttribute.USER_ID`). That pair is a
        far stronger signal than any name-based device match.
        """
        if not user_id:
            return None
        for entity_id in self.table.persons:
            if self._person_user_id(entity_id) == user_id:
                return entity_id
        return None

    @staticmethod
    def acknowledge_is_allowed(target: TargetConfig) -> bool:
        """Return True when the ADR-009 allow-list permits acknowledging a row.

        The single source of truth for both the Companion button path (which
        logs and returns when it is False) and `notify_switchboard.acknowledge`
        (which raises `ServiceValidationError`).
        """
        return bool(target.alert_entity) and target.allow_acknowledge

    async def _async_acknowledge(
        self,
        target: TargetConfig,
        user_id: str | None,
        context: Context | None = None,
    ) -> None:
        """Turn off the row's alert, if the allow-list permits it (ADR-009)."""
        if not self.acknowledge_is_allowed(target):
            _LOGGER.warning(
                "Refusing to acknowledge target %s: no alert in the routing table "
                "or acknowledgement disabled (user_id=%s)",
                target.slug,
                user_id,
            )
            return

        await self._async_turn_off_alert(target, user_id, context)

    async def _async_turn_off_alert(
        self,
        target: TargetConfig,
        user_id: str | None,
        context: Context | None = None,
    ) -> None:
        """Perform the acknowledgement itself, once the allow-list said yes.

        The caller's `Context` is carried through, so the logbook attributes the
        acknowledgement to whoever tapped the card or the Companion button
        rather than to "Notify Switchboard". It is carried in two different
        ways, and the difference matters:

        - `alert.turn_off` gets a **child** context (`child_context` below), not
          the caller's own. `alert` is an entity service, and
          `homeassistant/helpers/service.py`,
          `_resolve_entity_service_call_entities`, treats a non-empty
          `context.user_id` as "this call is that user's" and runs an auth
          lookup plus a per-entity permission check on it. Forwarding the
          caller's context verbatim would therefore make the row's
          `allow_acknowledge` allow-list (ADR-0009) silently subordinate to the
          caller's entity permissions — and would raise `UnknownUser` for a
          context whose user no longer exists. A child context keeps the
          attribution without moving the authorisation decision: the logbook
          falls back to the parent context's user when a row carries none
          (`homeassistant/components/logbook/processor.py`, the
          "Fall back to the parent context" branch).
        - The `acknowledged` event entity gets the caller's context as-is.
          Writing entity state runs no permission check, so the attribution is
          direct there.
        """
        child_context = Context(parent_id=context.id) if context is not None else None
        await self.hass.services.async_call(
            ALERT_DOMAIN,
            SERVICE_TURN_OFF,
            {ATTR_ENTITY_ID: target.alert_entity},
            blocking=True,
            context=child_context,
        )
        self._async_fire_delivery_event(
            EVENT_TYPE_ACKNOWLEDGED,
            {
                "target": target.slug,
                "alert_entity": target.alert_entity,
                "user_id": user_id,
                # ADR-0021 §4: the acting user resolved through the
                # **canonical** link only -- the `user_id` state attribute of a
                # `person.*`, contract v0.3 §"Callback resolution order" step 1
                # -- and `null` when that does not resolve. The `device_id`
                # fallback of step 2 is deliberately not used for authorship:
                # guessing who acknowledged from a device name is worse than
                # saying "unknown". No entity and no store exposes this; the
                # event is where it lives.
                ATTR_PERSON: self._person_for_user_id(user_id),
            },
            context,
        )
        self._async_notify_entities()

    async def _async_snooze(
        self,
        target: TargetConfig,
        minutes: int,
        device_id: Any,
        user_id: str | None,
        context: Context | None = None,
    ) -> None:
        """Store a snooze for (person, target) with an expiry."""
        persons = self._resolve_persons(target, device_id, user_id)
        if not persons:
            _LOGGER.warning(
                "Snooze for %s ignored: no person in the audience (user_id=%s)",
                target.slug,
                user_id,
            )
            return

        await self._async_store_snooze(target, minutes, persons, user_id, context)

    async def _async_store_snooze(
        self,
        target: TargetConfig,
        minutes: int,
        persons: list[str],
        user_id: str | None,
        context: Context | None = None,
    ) -> None:
        """Persist one snooze per person and announce it.

        Shared by the Companion callback and `notify_switchboard.snooze`; the
        two paths differ only in how they resolve `persons` and in what they do
        with a refusal.
        """
        expiry = dt_util.utcnow() + timedelta(minutes=minutes)
        for person_id in persons:
            self.store.snoozes[(person_id, target.slug)] = expiry

        await self.store.async_save()
        self._async_fire_delivery_event(
            EVENT_TYPE_SNOOZED,
            {
                "target": target.slug,
                "persons": persons,
                "minutes": minutes,
                "until": expiry.isoformat(),
                "user_id": user_id,
            },
            context,
        )
        self._async_notify_entities()

    def _resolve_persons(
        self, target: TargetConfig, device_id: Any, user_id: str | None = None
    ) -> list[str]:
        """Resolve the acting person, falling back to the row's audience.

        Three paths, strongest first (brief item 6):

        1. `event.context.user_id` -> the `person.*` linked to that Home
           Assistant user. Companion actions arrive with the registration's
           context, so this is authoritative when the person is linked.
        2. The `device_id` in the event, looked up in the device registry and
           turned into the `mobile_app_<name>` service name a person lists as
           an output.
        3. The documented ambiguous case: snooze every person in the row's
           audience and log it.
        """
        known = [
            person_id
            for person_id in target.audience
            if person_id in self.table.persons
        ]

        if (owner := self._person_for_user_id(user_id)) is not None and owner in known:
            return [owner]

        if not isinstance(device_id, str) or not device_id:
            return known

        # ADR-0017 §4: from here on we are on the fallback path. It has never
        # been verified against a real Companion device
        # (`docs/known-issues.md`), so it is reached only because the canonical
        # `person.user_id` link did not resolve -- which is itself reported as
        # a `person_without_user_id` repair.
        _LOGGER.debug(
            "No person.user_id matched context user_id=%s for target %s; "
            "falling back to the device_id %s",
            user_id,
            target.slug,
            device_id,
        )

        registry = dr.async_get(self.hass)
        device = registry.async_get(device_id) or registry.async_get_device(
            identifiers={(MOBILE_APP_DOMAIN, device_id)}
        )
        if device is None:
            return known

        candidates: set[str] = set()
        for name in (device.name, device.name_by_user):
            if name:
                candidates.add(companion_service_name(name))
        for entry_id in device.config_entries:
            entry = self.hass.config_entries.async_get_entry(entry_id)
            if entry is None or entry.domain != MOBILE_APP_DOMAIN:
                continue
            name = entry.data.get("device_name")
            if name:
                candidates.add(companion_service_name(str(name)))

        for candidate in candidates:
            person = self.table.person_for_output(candidate)
            if person is not None and person.entity_id in known:
                _LOGGER.debug(
                    "Resolved %s from the device_id fallback (output %s)",
                    person.entity_id,
                    candidate,
                )
                return [person.entity_id]

        return known

    # ------------------------------------------------------------------
    # UI services (contract §"UI services (v0.2, ADR-0016)")
    #
    # Every entry point below reuses the Companion code paths above and only
    # differs in one respect: a service call has a caller, so a refusal raises
    # `ServiceValidationError` (homeassistant/exceptions.py) instead of being
    # logged and swallowed.
    # ------------------------------------------------------------------

    async def async_service_acknowledge(
        self, slug: str, user_id: str | None, context: Context | None = None
    ) -> None:
        """Acknowledge a row's alert on behalf of a card, script or automation."""
        target = self._require_target(slug)
        if not self.acknowledge_is_allowed(target):
            _LOGGER.warning(
                "Refusing notify_switchboard.acknowledge for target %s: no alert "
                "in the routing table or acknowledgement disabled (user_id=%s)",
                slug,
                user_id,
            )
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key=ERROR_ACKNOWLEDGE_NOT_ALLOWED,
                translation_placeholders={"target": slug},
            )

        await self._async_turn_off_alert(target, user_id, context)

    async def async_service_snooze(
        self,
        slug: str,
        minutes: int,
        person: str | None,
        user_id: str | None,
        context: Context | None = None,
    ) -> None:
        """Snooze a row for one person, or for its whole audience."""
        target = self._require_target(slug)
        if minutes not in target.snooze_minutes:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key=ERROR_SNOOZE_MINUTES_NOT_OFFERED,
                translation_placeholders={
                    "target": slug,
                    "minutes": str(minutes),
                    "offered": ", ".join(str(m) for m in target.snooze_minutes) or "-",
                },
            )

        persons = self._require_persons(target, person)
        await self._async_store_snooze(target, minutes, persons, user_id, context)

    async def async_service_unsnooze(self, slug: str, person: str | None) -> None:
        """Clear a stored snooze immediately, without waiting for its expiry."""
        target = self._require_target(slug)
        persons = self._require_persons(target, person)

        cleared = [
            person_id
            for person_id in persons
            if self.store.snoozes.pop((person_id, target.slug), None) is not None
        ]
        if cleared:
            await self.store.async_save()
            self._async_notify_entities()
        _LOGGER.debug("Unsnoozed %s for %s", target.slug, cleared or "nobody")

    async def async_service_silence(self, person: str, minutes: int) -> None:
        """Set a temporary, person-wide silence the router owns (ADR-0016).

        `minutes` is bounded on both sides. The lower bound is ADR-0016's rule
        (zero has no meaning); the upper bound exists because the arithmetic
        below is not total: `datetime + timedelta(minutes=10**15)` raises
        `OverflowError`, which is a plain `Exception`, so an unbounded value
        would reach the caller as an unhandled error rather than as the
        translated `ServiceValidationError` ADR-0015 promises.
        """
        self._require_person(person)
        self._async_clear_invalid_service_call(ATTR_PERSON, person)
        if not MIN_SILENCE_MINUTES <= minutes <= MAX_SILENCE_MINUTES:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key=ERROR_INVALID_SILENCE_MINUTES,
                translation_placeholders={
                    "minutes": str(minutes),
                    "min": str(MIN_SILENCE_MINUTES),
                    "max": str(MAX_SILENCE_MINUTES),
                },
            )

        until = dt_util.utcnow() + timedelta(minutes=minutes)
        self.store.silences[person] = until
        await self.store.async_save()
        self._async_schedule_silence_expiry(person, until)
        # The queue has to be told too, and for the same reason `unsilence`
        # below re-arms: the deferral timer is armed on the earliest of the
        # wake time and the end of a running temporary silence, and until this
        # call there was no such silence to be a candidate. Without the re-arm
        # a quiet hour asked for at 04:30 by somebody who wakes at 07:00 ends
        # at 06:00 with nobody waiting for it -- the night that queued the
        # message may well have lifted in between, so the message would wait an
        # hour past the last thing that held it. `_async_schedule_deferral`
        # returns on the spot when there is nothing queued, which is the
        # ordinary case.
        self._async_schedule_deferral(person)
        self._async_notify_entities()
        _LOGGER.debug("Silenced %s until %s", person, until.isoformat())

    async def async_service_unsilence(self, person: str) -> None:
        """Lift a temporary silence immediately.

        Idempotent by contract: a person who is not temporarily silenced has
        nothing to undo, and that is not an error.

        "Immediately" has to cover the queue as well as the sensor. A deferral
        is armed on the earliest of the wake time and this silence's end
        (`_async_schedule_deferral`), so lifting the silence by hand without
        touching that timer would leave a message waiting for an expiry that no
        longer holds anything -- the same wait ADR-0019 §4 removed for a
        configured silence going `off` early, reached through the one silence
        source the router owns. The answer is the same as
        `_async_silence_changed`'s: with nothing left to hold the queue, flush
        now; with a configured silence still on, re-arm on what remains, which
        is the end that silence publishes or the wake time.
        """
        known = self._require_person(person)
        self._async_clear_invalid_service_call(ATTR_PERSON, person)
        if self.store.silences.pop(person, None) is None:
            return

        self._async_cancel_silence_expiry(person)
        await self.store.async_save()
        self._async_notify_entities()

        if not any(key[0] == person for key in self.store.deferrals):
            return
        if self.has_configured_silence(known):
            self._async_schedule_deferral(person)
            return
        _LOGGER.debug(
            "The temporary silence of %s was lifted by hand: flushing", person
        )
        self._async_schedule_flush(person)

    # ------------------------------------------------------------------
    # Service-call validation
    # ------------------------------------------------------------------

    def _require_target(self, slug: str) -> TargetConfig:
        """Return the row named by `slug`, or refuse the call."""
        target = self.table.targets.get(slug)
        if target is None:
            self._async_record_invalid_service_call(ATTR_TARGET, slug)
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key=ERROR_UNKNOWN_TARGET,
                translation_placeholders={"target": slug},
            )
        self._async_clear_invalid_service_call(ATTR_TARGET, slug)
        return target

    def _require_person(self, person: str) -> PersonConfig:
        """Return the person row for `person`, or refuse the call."""
        known = self.table.persons.get(person)
        if known is None:
            self._async_record_invalid_service_call(ATTR_PERSON, person)
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key=ERROR_UNKNOWN_PERSON,
                translation_placeholders={"person": person},
            )
        return known

    def _require_persons(self, target: TargetConfig, person: str | None) -> list[str]:
        """Resolve the persons a snooze/unsnooze applies to.

        An explicit `person` must be known *and* in the row's audience; without
        one, the whole audience is used — the same fallback the Companion path
        documents for an unresolvable device (`tests/acceptance/README.md`
        "Assumptions" §3), reached here without needing a device at all.
        """
        audience = [
            person_id
            for person_id in target.audience
            if person_id in self.table.persons
        ]

        if person is None:
            if not audience:
                raise ServiceValidationError(
                    translation_domain=DOMAIN,
                    translation_key=ERROR_NO_AUDIENCE,
                    translation_placeholders={"target": target.slug},
                )
            return audience

        self._require_person(person)
        if person not in audience:
            self._async_record_invalid_service_call(ATTR_PERSON, person)
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key=ERROR_PERSON_NOT_IN_AUDIENCE,
                translation_placeholders={"person": person, "target": target.slug},
            )
        self._async_clear_invalid_service_call(ATTR_PERSON, person)
        return [person]

    @callback
    def _async_record_invalid_service_call(self, field: str, value: str) -> None:
        """Count a refused service call and repair when the same one recurs.

        One bad call is already answered with a `ServiceValidationError`; a card
        still pointing at a renamed slug repeats it forever and nobody reads the
        log, which is what the `repairs` issue is for (brief item 7, same spirit
        as `MAX_CONSECUTIVE_OUTPUT_MISSES`).

        The count is **cumulative, not consecutive**: only
        `_async_clear_invalid_service_call` resets it, when that exact
        slug/person becomes usable again. See `MAX_INVALID_SERVICE_CALLS`.

        Only `MAX_TRACKED_INVALID_SERVICE_CALLS` distinct values are tracked
        individually. A caller producing a fresh bad value every time — a
        template rendering to garbage, a fuzzed card — would otherwise grow this
        dict and the (persisted) issue registry without bound; past the cap a
        single aggregated issue says so instead.
        """
        key = (field, value)
        if (
            key not in self._invalid_service_calls
            and len(self._invalid_service_calls) >= MAX_TRACKED_INVALID_SERVICE_CALLS
        ):
            self._async_report_many_invalid_service_calls()
            return

        count = self._invalid_service_calls.get(key, 0) + 1
        self._invalid_service_calls[key] = count
        if count < MAX_INVALID_SERVICE_CALLS:
            return
        ir.async_create_issue(
            self.hass,
            DOMAIN,
            f"invalid_service_{field}_{value}",
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key=f"invalid_service_{field}",
            translation_placeholders={"value": value},
        )

    @callback
    def _async_clear_invalid_service_call(self, field: str, value: str) -> None:
        """Forget a slug/person that is valid again, and drop its repair.

        A `repairs` issue outlives the process that raised it, so adding the
        missing row back — or putting the person into the audience — has to
        delete it explicitly, or the user fixes the cause and the warning stays
        on their dashboard for ever.
        """
        if self._invalid_service_calls.pop((field, value), None) is None:
            return
        ir.async_delete_issue(self.hass, DOMAIN, f"invalid_service_{field}_{value}")

    @callback
    def _async_report_many_invalid_service_calls(self) -> None:
        """Raise the one aggregated issue that replaces per-value ones."""
        ir.async_create_issue(
            self.hass,
            DOMAIN,
            ISSUE_INVALID_SERVICE_CALLS_MANY,
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key=ISSUE_INVALID_SERVICE_CALLS_MANY,
            translation_placeholders={"count": str(MAX_TRACKED_INVALID_SERVICE_CALLS)},
        )

    @callback
    def _async_clear_fixed_service_issues(self) -> None:
        """Delete the repairs whose cause the options flow has just fixed.

        Called at setup, so a reload — which is what an options change triggers
        (`__init__._async_update_options`) — is enough to clear the warnings for
        every slug and person the new table now knows about. The in-memory
        counters do not survive that reload, so the aggregated issue goes too:
        it describes a burst this process never saw.

        The issue registry is persisted, so a repair nobody deletes outlives
        the change it asked for: creating the missing row, or dropping the dead
        output, has to make the warning go away. `unknown_target_<slug>` is
        cleared for every slug the new table knows, and `missing_output_<x>`
        for every output no person routes to any more (an output that is still
        configured is cleared instead by the first call that succeeds, in
        `_async_call_output` — unconditionally there, since the in-memory
        counters do not survive a reload either).
        """
        for slug in self.table.targets:
            ir.async_delete_issue(
                self.hass, DOMAIN, f"invalid_service_{ATTR_TARGET}_{slug}"
            )
            ir.async_delete_issue(self.hass, DOMAIN, f"unknown_target_{slug}")
            self._reported_unknown_targets.discard(slug)
        for person in self.table.persons:
            ir.async_delete_issue(
                self.hass, DOMAIN, f"invalid_service_{ATTR_PERSON}_{person}"
            )
        ir.async_delete_issue(self.hass, DOMAIN, ISSUE_INVALID_SERVICE_CALLS_MANY)

        configured = {
            output
            for person in self.table.persons.values()
            for output in person.outputs
        }
        registry = ir.async_get(self.hass)
        orphaned = [
            issue_id
            for (domain, issue_id), issue in registry.issues.items()
            if domain == DOMAIN
            and issue.translation_key == "missing_output"
            and issue.translation_placeholders is not None
            and issue.translation_placeholders["output"] not in configured
        ]
        for issue_id in orphaned:
            ir.async_delete_issue(self.hass, DOMAIN, issue_id)

    # ------------------------------------------------------------------
    # Temporary silence expiry
    # ------------------------------------------------------------------

    @callback
    def _async_schedule_silence_expiry(self, person: str, until: datetime) -> None:
        """(Re)arm the timer that lifts one person's temporary silence.

        The routing decision purges expired silences anyway; this timer exists
        so `binary_sensor.<p>_silenced` goes back to `off` at the right minute
        instead of at the next notification, which may be hours later.
        """
        self._async_cancel_silence_expiry(person)

        async def _expire(_now: datetime) -> None:
            self._silence_unsubs.pop(person, None)
            self.store.purge_expired_silences(dt_util.utcnow())
            await self.store.async_save()
            self._async_notify_entities()

        self._silence_unsubs[person] = async_track_point_in_time(
            self.hass, _expire, until
        )

    @callback
    def _async_cancel_silence_expiry(self, person: str) -> None:
        """Cancel the pending expiry timer of one person, if there is one."""
        if (unsub := self._silence_unsubs.pop(person, None)) is not None:
            unsub()

    # ------------------------------------------------------------------
    # Observer mode (brief item 8)
    # ------------------------------------------------------------------

    async def _async_alert_changed(self, event: Event[EventStateChangedData]) -> None:
        """Open and close episodes, and route in observer mode (ADR-007, ADR-0019).

        One handler for both halves, because they are the same two transitions.
        Episodes are kept for **every** row that names an `alert_entity`
        (ADR-0019 §5); the routing is still observer mode's alone -- a row that
        is called through its alert's own `notifiers:` list would otherwise be
        notified twice.
        """
        old_state = event.data["old_state"]
        new_state = event.data["new_state"]
        if new_state is None or old_state is None:
            return

        entity_id = event.data["entity_id"]
        targets = [
            target
            for target in self.table.targets.values()
            if target.alert_entity == entity_id
        ]
        if not targets:
            return

        old, new = old_state.state, new_state.state
        for target in targets:
            if old == STATE_IDLE and new == STATE_ON:
                await self._async_open_episode(target)
                if target.observer_mode:
                    await self.async_handle_request(
                        self._observer_message(target, new_state),
                        title=self._observer_title(target),
                        targets=[target.slug],
                    )
            elif new == STATE_IDLE and old in (STATE_ON, STATE_OFF):
                await self._async_close_episode(target, new_state)
            # `on -> off` is an acknowledgement: nothing is routed, and the
            # episode is not over -- the alert is still firing.

    # ------------------------------------------------------------------
    # Episodes and closing the loop (contract v0.5, ADR-0019 §5 and §6)
    # ------------------------------------------------------------------

    async def _async_open_episode(self, target: TargetConfig) -> None:
        """Start a fresh episode for one row, discarding the previous one.

        The reset happens here rather than at the end of the previous episode,
        because a `done` message is by definition sent after the alert is
        already back to `idle`: the recipients have to outlive the episode.
        """
        self.store.episodes[target.slug] = Episode(slug=target.slug, is_open=True)
        await self.store.async_save()

    async def _async_close_episode(self, target: TargetConfig, state: State) -> None:
        """Close a row's episode, announce it and tidy up the channels it used.

        The order is ADR-0019 §6's: the record is closed first (so the `done`
        message is not recorded into the episode it closes), then the `done`
        message is routed, then the `clear_notification` pushes and the
        `persistent_notification.dismiss`, then -- if the row asked for it --
        the `done` message's own clear.

        Only a row in **observer mode** announces and tidies here: it is the one
        whose "back to normal" the router itself sends. A row driven by its
        alert's `notifiers:` list sends its own, on its own schedule, and the
        router closing its channels first would clear the notification a moment
        before the message explaining why arrives (core's `end_alerting`,
        `homeassistant/components/alert/entity.py`, awaits the done message
        *before* `async_write_ha_state()`, so it leaves ahead of the `→ idle`
        this method reacts to).

        That is the whole of the narrowing (ADR-0019 §6, amendment (a)). The
        clear does **not** ask what backs the `alert.*` state: any observer row
        naming an `alert_entity` is tidied up after, whether that state comes
        from the `alert` integration, a template or a test. The router observed
        it and notified on the strength of it; declining to tidy up on the same
        evidence would be incoherent.
        """
        episode = self.store.episodes.get(target.slug)
        if episode is not None and episode.is_open:
            episode.is_open = False
            await self.store.async_save()

        if not target.observer_mode:
            return

        done_data: dict[str, Any] = {ATTR_SWITCHBOARD_DONE: True}
        _decision, done_outputs = await self._async_route(
            NotificationRequest(
                message=await self._async_observer_done_message(target, state),
                title=self._observer_title(target),
                targets=(target.slug,),
                data=done_data,
            )
        )

        if episode is not None:
            for tag in sorted(episode.tags):
                for output in sorted(episode.outputs):
                    if output.startswith(COMPANION_OUTPUT_PREFIX):
                        await self._async_clear_notification(output, tag)
                if PERSISTENT_NOTIFICATION_OUTPUT in episode.outputs:
                    await self._async_dismiss_notification(tag)

        if target.clear_done and done_outputs:
            done_tag = effective_tag(target.slug, merge_data(target, done_data))
            for output in sorted(done_outputs):
                if output.startswith(COMPANION_OUTPUT_PREFIX):
                    await self._async_clear_notification(output, done_tag)

    async def _async_clear_notification(self, output: str, tag: str) -> None:
        """Tell one Companion output to remove the notification bearing `tag`.

        `clear_notification` is core's own literal
        (`homeassistant/components/mobile_app/const.py`, `CLEAR_NOTIFICATION`);
        the Companion app on the device is what removes the notification when
        the push arrives. Core reads the literal in exactly one place --
        `mobile_app/live_activity/__init__.py`, `if data.get(ATTR_MESSAGE) ==
        CLEAR_NOTIFICATION`, which ends the Live Activity for the same tag --
        and otherwise forwards the payload untouched to the push relay, which is
        why this has to be an ordinary `notify.mobile_app_<device>` call rather
        than an API that does not exist.

        **A clear is not a message** (ADR-0019 §6): it is not counted, it fires
        no `event.switchboard_delivery`, it is subject to no routing rule and it
        never creates a deferral. It is housekeeping on a channel that was
        already used, addressed to a device rather than to a person.
        """
        await self._async_housekeeping_call(
            NOTIFY_DOMAIN,
            output,
            {"message": CLEAR_NOTIFICATION_MESSAGE, "data": {ATTR_TAG: tag}},
        )

    async def _async_dismiss_notification(self, notification_id: str) -> None:
        """Close the UI half of an episode through core's own `dismiss`."""
        await self._async_housekeeping_call(
            PERSISTENT_NOTIFICATION_DOMAIN,
            SERVICE_DISMISS,
            {ATTR_NOTIFICATION_ID: notification_id},
        )

    async def _async_housekeeping_call(
        self, domain: str, service: str, data: dict[str, Any]
    ) -> None:
        """Call one tidy-up service, bounded and swallowing every failure.

        Bounded by the same `OUTPUT_TIMEOUT_SECONDS` as any other output call,
        because a phone off the network must not hold the event loop; a failure
        is logged and swallowed, because failing to tidy up is never worth
        raising at whoever ended the alert.
        """
        if not self.hass.services.has_service(domain, service):
            _LOGGER.debug("Nothing to clear: %s.%s is not registered", domain, service)
            return
        try:
            async with asyncio.timeout(OUTPUT_TIMEOUT_SECONDS):
                await self.hass.services.async_call(
                    domain, service, data, blocking=True
                )
        except (TimeoutError, HomeAssistantError, vol.Invalid) as err:
            _LOGGER.warning("Could not clear through %s.%s: %s", domain, service, err)
        except Exception:  # noqa: BLE001 - tidying up must never break anything
            _LOGGER.exception("Unexpected error while clearing %s.%s", domain, service)

    def _observer_message(self, target: TargetConfig, state: State) -> str:
        """Return the text of an `idle -> on` transition (contract, ADR-0016).

        Order: the alert's own `message` attribute (kept first for forward
        compatibility — a real `AlertEntity` exposes none today, see
        `docs/known-issues.md`), then the row's `message` template, then the
        row's bare name.
        """
        if (attribute := state.attributes.get(ATTR_ALERT_MESSAGE)) not in (None, ""):
            return str(attribute)
        if (rendered := self._render_row_text(target, target.message)) is not None:
            return rendered
        return target.name

    async def _async_observer_done_message(
        self, target: TargetConfig, state: State
    ) -> str:
        """Return the text of an `on|off -> idle` transition (contract, ADR-0016).

        Order: the row's `done_message` template, then the alert's own
        `done_message` attribute, then the translated `common.back_to_normal`.
        Contract §"Per-row texts" and ADR-0016 §3 both put the row's template
        first here, unlike `message`; the row is the only source that exists in
        practice, so the two orders behave identically on a real alert.
        """
        if (rendered := self._render_row_text(target, target.done_message)) is not None:
            return rendered
        if (attribute := state.attributes.get(ATTR_ALERT_DONE_MESSAGE)) not in (
            None,
            "",
        ):
            return str(attribute)
        return await self._async_back_to_normal()

    def _observer_title(self, target: TargetConfig) -> str:
        """Return the title of an observer-generated message.

        Observer mode never had a caller to supply a title, so the row's
        `default_title` always applies (ADR-0016); the row's name stays the last
        resort, which is exactly what Sprint 1 always sent.
        """
        return target.default_title or target.name

    def _render_row_text(self, target: TargetConfig, raw: str | None) -> str | None:
        """Render one of the row's optional templates, or return None.

        The row's alert's current state is exposed to the template as `alert`
        (`None` when the row has no `alert_entity`, or that entity does not
        exist), so a row can write `{{ alert.attributes.level }}` without
        depending on a real `AlertEntity` ever gaining state attributes.
        """
        if not raw:
            return None

        alert_state = (
            self.hass.states.get(target.alert_entity) if target.alert_entity else None
        )
        try:
            rendered = Template(raw, self.hass).async_render(
                {TEMPLATE_ALERT_VARIABLE: alert_state}, parse_result=False
            )
        except TemplateError as err:
            _LOGGER.error(
                "Target %s: could not render its text %r: %s", target.slug, raw, err
            )
            return None
        text = str(rendered).strip()
        return text or None

    # ------------------------------------------------------------------
    # Translations
    # ------------------------------------------------------------------

    async def _async_translations(self) -> dict[str, str]:
        """Fetch and cache this integration's `common` translations."""
        if self._labels is None:
            self._labels = await async_get_translations(
                self.hass, self.hass.config.language, TRANSLATION_CATEGORY, {DOMAIN}
            )
        return self._labels

    async def _async_selector_translations(self) -> dict[str, str]:
        """Fetch and cache the option labels of the two coded selectors.

        A second category, and therefore a second fetch: `async_get_translations`
        takes one at a time. Cached exactly as `common` is, and read in the
        instance language for the same reason -- `explain` answers into an
        event and a card, not into one browser session.
        """
        if self._selector_labels is None:
            self._selector_labels = await async_get_translations(
                self.hass, self.hass.config.language, SELECTOR_CATEGORY, {DOMAIN}
            )
        return self._selector_labels

    async def _async_labels(self, target: TargetConfig) -> dict[str, str]:
        """Return the button labels for one row, in Home Assistant's language."""
        translations = await self._async_translations()
        snooze_template = translations.get(KEY_SNOOZE_MINUTES, FALLBACK_SNOOZE)
        labels = {
            "acknowledge": translations.get(KEY_ACKNOWLEDGE, FALLBACK_ACKNOWLEDGE)
        }
        for minutes in target.snooze_minutes:
            labels[f"snooze_{minutes}"] = snooze_template.replace(
                "{minutes}", str(minutes)
            )
        return labels

    async def _async_back_to_normal(self) -> str:
        """Return the translated "back to normal" observer-mode message."""
        translations = await self._async_translations()
        return translations.get(KEY_BACK_TO_NORMAL, FALLBACK_BACK_TO_NORMAL)

    async def _async_test_message(self) -> str:
        """Return the translated body of an options-flow test message."""
        translations = await self._async_translations()
        return translations.get(KEY_TEST_MESSAGE, FALLBACK_TEST_MESSAGE)

    # ------------------------------------------------------------------
    # Counters, events and repairs
    # ------------------------------------------------------------------

    @callback
    def _async_count_drop(self, reason: str, person: str | None, slug: str) -> None:
        """Record a dropped delivery and its reason."""
        if reason in UNCOUNTED_DROP_REASONS:
            return
        self.dropped_today += 1
        self.drop_reasons[reason] = self.drop_reasons.get(reason, 0) + 1
        self._async_fire_delivery_event(
            EVENT_TYPE_DROPPED,
            {"person": person, "target": slug, "reason": reason},
        )

    @callback
    def _async_reset_counters(self, _now: datetime) -> None:
        """Reset the daily counters at local midnight (brief item 9)."""
        self.routed_today = 0
        self.dropped_today = 0
        self.deferred_today = 0
        self.drop_reasons.clear()
        self._async_notify_entities()

    @callback
    def _async_silence_changed(self, event: Event[EventStateChangedData]) -> None:
        """Refresh `binary_sensor.<person>_silenced`, and flush if the night ended.

        Three readings of the new state, and only the first is §4's:

        * gone (`off`, or the entity removed): flush, when this was the last
          thing holding the queue;
        * still `on`: nothing to release, but possibly a timer to give back --
          `_async_rearm_silenced_queues`;
        * `on` with a queue that is already armed: nothing at all.

        ADR-0019 §4: the router was already subscribed to every configured
        `silence_entities` of every person -- it simply refreshed a binary
        sensor and returned, so a schedule ending at 05:00 left the queue
        waiting until 07:00, two hours after the person was demonstrably awake.

        The flush is deliberately narrow. It needs the **last** active silence
        to lift: a person with a night schedule and a Focus sensor is not awake
        because one of the two went `off`. A running
        `notify_switchboard.silence` holds the queue too -- somebody asked for
        quiet in so many words, and the router owns that one.

        The flush itself is handed to a task rather than run inside the
        listener. A flush calls `notify.*` services, re-runs the whole decision
        and writes the store; doing all of that in the middle of the state write
        that triggered it would make the router re-enter the state machine it is
        reading. The task is the config entry's, which unloading *awaits*
        rather than cancels; a flush that has not begun by then stands down --
        see `_async_schedule_flush`.
        """
        self._async_notify_entities()

        entity_id = event.data["entity_id"]
        new_state = event.data["new_state"]
        if new_state is not None and state_is_on(new_state.state):
            self._async_rearm_silenced_queues(entity_id)
            return

        # `None` is an entity that has been renamed or removed, and it is the
        # one state that cannot mean "keep waiting": it will never be seen `on`
        # again, so a queue held behind it would never be offered §4 a second
        # time. `has_configured_silence` reads `hass.states`, where the entity
        # is now absent, so the loop below already treats it as lifted -- what
        # this needed was to reach the loop at all.
        now = dt_util.utcnow()
        for person_id, person in self._persons_silenced_by(entity_id):
            if self.has_configured_silence(person):
                continue
            if self.store.is_temporarily_silenced(person_id, now):
                continue
            if not any(key[0] == person_id for key in self.store.deferrals):
                continue
            _LOGGER.debug(
                "The last silence of %s lifted before their wake time: flushing",
                person_id,
            )
            self._async_schedule_flush(person_id)

    def _persons_silenced_by(
        self, entity_id: str
    ) -> Iterator[tuple[str, PersonConfig]]:
        """Yield the persons who named `entity_id` among their silences.

        The listener is subscribed to the union of everybody's
        `silence_entities`, so every handler starts by asking whose entity this
        was.
        """
        for person_id, person in self.table.persons.items():
            if entity_id in person.silence_entities:
                yield person_id, person

    @callback
    def _async_rearm_silenced_queues(self, entity_id: str) -> None:
        """Give back a timer to a queue behind `entity_id` that has none.

        A silence going `on` normally changes nothing: the deferral is already
        armed on the wake time, and a person who has one is never left without
        a timer. A person who has *not* can be, and `_async_schedule_deferral`
        explains how -- a re-arm that runs at the exact instant the schedule
        published reads an end that is no longer ahead of it, drops it rather
        than spin, and leaves nothing armed. That is correct at the time and
        would be permanent afterwards: the queue's only remaining hope is the
        early flush of §4, and a schedule that goes `on` again for a second
        block before it goes `off` never offers one.

        So this is deliberately the narrow case: a queue exists, and nothing is
        waiting for it. Re-arming a person who already has a timer would cancel
        and rebuild it on every state write of every silence they own, for no
        change of instant.
        """
        for person_id, _person in self._persons_silenced_by(entity_id):
            if person_id in self._deferral_unsubs:
                continue
            if not any(key[0] == person_id for key in self.store.deferrals):
                continue
            _LOGGER.debug(
                "A silence of %s went on with nothing armed for their queue: re-arming",
                person_id,
            )
            self._async_schedule_deferral(person_id)

    @callback
    def _async_notify_entities(self) -> None:
        """Ask this entry's entities to write their state."""
        async_dispatcher_send(
            self.hass, f"{SIGNAL_STATE_UPDATED}_{self.entry.entry_id}"
        )

    @callback
    def _async_fire_delivery_event(
        self,
        event_type: str,
        attributes: dict[str, Any],
        context: Context | None = None,
    ) -> None:
        """Push one `event.switchboard_delivery` event.

        `context` is the caller's, when there is one (a UI service call, a
        Companion callback). It is handed to the event entity so the state
        change it writes is attributed to that user in the logbook, the same
        way `alert.turn_off` is.
        """
        if event_type not in DELIVERY_EVENT_TYPES:  # pragma: no cover - guard
            return
        async_dispatcher_send(
            self.hass,
            f"{DOMAIN}_delivery_{self.entry.entry_id}",
            event_type,
            attributes,
            context,
        )

    @callback
    def _async_review_person_user_ids(self) -> None:
        """Raise (or clear) one `person_without_user_id` repair per person.

        ADR-0017 §4: `context.user_id` -> `person.user_id` is the canonical way
        to tell *who* tapped a Companion button, and it simply cannot work for a
        `person.*` that is not linked to a Home Assistant user. Such a person
        silently gets the documented "act on the whole audience" fallback
        instead, which is a configuration gap the user can close in
        Settings > People -- so it is a repair (`is_fixable=False`: there is
        nothing this integration can do about it), not a log line.

        Only persons in the audience of a row that actually adds buttons
        (`allow_acknowledge`, or a non-empty `snooze_minutes`) are concerned:
        without a button there is no callback to resolve. One issue per person,
        not per (person, row).

        Issues whose cause is gone are deleted, including those raised for a
        person the routing table no longer knows -- the issue registry is
        persisted, so nothing else would ever clear them.
        """
        unlinked = {
            person_id: self._person_issue_id(person_id)
            for person_id in self._persons_needing_a_user_id()
            if not self._person_user_id(person_id)
        }

        wanted = set(unlinked.values())
        registry = ir.async_get(self.hass)
        stale = [
            issue_id
            for (domain, issue_id), issue in registry.issues.items()
            if domain == DOMAIN
            and issue.translation_key == ISSUE_PERSON_WITHOUT_USER_ID
            and issue_id not in wanted
        ]
        for issue_id in stale:
            ir.async_delete_issue(self.hass, DOMAIN, issue_id)

        for person_id, issue_id in unlinked.items():
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                issue_id,
                is_fixable=False,
                severity=ir.IssueSeverity.WARNING,
                translation_key=ISSUE_PERSON_WITHOUT_USER_ID,
                # v0.7.1: a repair is read by a household. The id it has to act
                # on stays in brackets; the `issue_id` still carries it whole.
                translation_placeholders={"person": named_entity(self.hass, person_id)},
            )

    @staticmethod
    def _person_issue_id(person_id: str) -> str:
        """Return the `repairs` issue id used for one person."""
        return f"{ISSUE_PERSON_WITHOUT_USER_ID}_{person_id}"

    @callback
    def _async_review_person_outputs(self) -> None:
        """Raise (or clear) one `person_without_outputs` repair per person.

        ADR-0018 §5: a person with an empty `outputs` list who sits in the
        audience of at least one row is dropped with `no_outputs` on every
        single message, silently and for ever. That is a configuration gap the
        user can close, so it is a repair (`is_fixable=False`) rather than a log
        line nobody reads.

        A person in **no** audience raises nothing: without a row there is
        nothing to fail, and a repair that fires for somebody nobody routes to
        is worse than no repair at all.
        """
        in_an_audience = {
            person_id
            for target in self.table.targets.values()
            for person_id in target.audience
        }
        gaps = {
            f"{ISSUE_PERSON_WITHOUT_OUTPUTS}_{person_id}": person_id
            for person_id, person in self.table.persons.items()
            if not person.outputs and person_id in in_an_audience
        }
        self._async_prune_issues(ISSUE_PERSON_WITHOUT_OUTPUTS, set(gaps))
        for issue_id, person_id in gaps.items():
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                issue_id,
                is_fixable=False,
                severity=ir.IssueSeverity.WARNING,
                translation_key=ISSUE_PERSON_WITHOUT_OUTPUTS,
                translation_placeholders={"person": named_entity(self.hass, person_id)},
            )

    @callback
    def _async_alert_grace_elapsed(self, _now: datetime) -> None:
        """Run the alert-entity check once the grace period is over."""
        self._async_review_alert_entities(create=True)

    @callback
    def _async_review_alert_entities(self, *, create: bool) -> None:
        """Raise (or clear) one `alert_entity_missing` repair per row.

        A row whose `alert_entity` names an `alert.*` that does not exist
        acknowledges nothing and observes nothing, and nothing says so
        (ADR-0018 §5). The check itself is only meaningful once the rest of the
        configuration has had time to load, which is why `create` is False at
        setup: the stale issues are pruned there and the raising is left to the
        grace check armed by `async_setup`.
        """
        broken = {
            f"{ISSUE_ALERT_ENTITY_MISSING}_{slug}": (
                target.name or slug,
                target.alert_entity,
            )
            for slug, target in self.table.targets.items()
            if target.alert_entity and self.hass.states.get(target.alert_entity) is None
        }
        self._async_prune_issues(ISSUE_ALERT_ENTITY_MISSING, set(broken))
        if not create:
            return
        for issue_id, (name, entity_id) in broken.items():
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                issue_id,
                is_fixable=False,
                severity=ir.IssueSeverity.WARNING,
                translation_key=ISSUE_ALERT_ENTITY_MISSING,
                translation_placeholders={
                    "slug": name,
                    "entity_id": named_entity(self.hass, str(entity_id)),
                },
            )

    @callback
    def _async_prune_issues(self, translation_key: str, wanted: set[str]) -> None:
        """Delete every issue of one kind whose cause is gone.

        The issue registry is persisted, so a repair nobody deletes outlives the
        change it asked for.
        """
        registry = ir.async_get(self.hass)
        stale = [
            issue_id
            for (domain, issue_id), issue in registry.issues.items()
            if domain == DOMAIN
            and issue.translation_key == translation_key
            and issue_id not in wanted
        ]
        for issue_id in stale:
            ir.async_delete_issue(self.hass, DOMAIN, issue_id)

    def _persons_needing_a_user_id(self) -> list[str]:
        """Return the persons a Companion callback may have to resolve."""
        concerned: list[str] = []
        for person_id in self.table.persons:
            if any(
                person_id in target.audience
                and (target.allow_acknowledge or target.snooze_minutes)
                for target in self.table.targets.values()
            ):
                concerned.append(person_id)
        return concerned

    def _person_user_id(self, person_id: str) -> str | None:
        """Return the Home Assistant user a `person.*` is linked to, if any."""
        state = self.hass.states.get(person_id)
        if state is None:
            return None
        user_id = state.attributes.get(ATTR_USER_ID)
        return str(user_id) if user_id else None

    @callback
    def _async_report_unknown_target(self, slug: str) -> None:
        """Raise the `unknown_target` repair once per slug."""
        if slug in self._reported_unknown_targets:
            return
        self._reported_unknown_targets.add(slug)
        ir.async_create_issue(
            self.hass,
            DOMAIN,
            f"unknown_target_{slug}",
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key="unknown_target",
            translation_placeholders={"slug": slug},
        )

    @callback
    def _async_report_missing_output(self, output: str) -> None:
        """Raise the `missing_output` repair for a durably absent output."""
        ir.async_create_issue(
            self.hass,
            DOMAIN,
            f"missing_output_{output}",
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key="missing_output",
            translation_placeholders={"output": output},
        )


def friendly_name(hass: HomeAssistant, entity_id: str) -> str:
    """Return the name Home Assistant shows for an entity, never its id.

    A `person.*` is renamed in the UI without its id following, so
    `person.dev_bob` may well be "Bob"; showing the id to a household is the
    0.7.1 complaint in one line. `State.name` is not the source: it is
    `friendly_name or object_id.replace("_", " ")` (`homeassistant/core.py`,
    `State.name`) with no titling, so an entity without a friendly name would
    read "dev bob". The attribute is read directly and the titled object id is
    the single fallback -- for a state without a friendly name, and for no
    state at all, which a restart can reach before `person` has written its
    states.
    """
    state = hass.states.get(entity_id)
    if state is not None and (name := state.attributes.get(ATTR_FRIENDLY_NAME)):
        return str(name)
    return entity_id.partition(".")[2].replace("_", " ").title()


def named_entity(hass: HomeAssistant, entity_id: str) -> str:
    """Return "Name (entity id)": the name to read, the id to go and fix.

    Used wherever the sentence is an explanation the user has to *act* on --
    which silence entity is on, whom a target names that the table does not
    know. The name alone would be friendlier and useless: there is no switch
    called "Quiet hours" in the settings, there is `input_boolean.quiet_hours`.
    """
    name = friendly_name(hass, entity_id)
    return entity_id if name == entity_id else f"{name} ({entity_id})"


@callback
def companion_device_names(hass: HomeAssistant) -> dict[str, str]:
    """Map every Companion push service name to the device it belongs to.

    Built from the `mobile_app` config entries rather than from a name
    heuristic, and for every registration of the instance rather than one
    person's: an output is offered, and explained, without knowing whose it is.
    """
    return {
        companion_service_name(str(device_name)): str(device_name)
        for entry in hass.config_entries.async_entries(MOBILE_APP_DOMAIN)
        if (device_name := entry.data.get(MOBILE_APP_DEVICE_NAME))
    }


def output_label(
    service: str,
    devices: Mapping[str, str],
    texts: Mapping[str, str],
    *,
    identifier: str | None = None,
) -> str:
    """Return the label of one `notify` service option, brackets included.

    Three kinds, in order, and each one decides for itself whether the raw
    identifier is worth showing:

    - a Companion registration **is** its device, spelled the way its owner
      spelled it in the app; the `mobile_app_…` slug core derives from that
      name is noise nobody has to read, so it is dropped;
    - `persistent_notification` is the one core service worth a name of its
      own, and that name says the whole thing;
    - anything else has no friendlier name to hide behind, so it is at least
      turned back into words and keeps its own name in brackets -- somebody
      who has to go and change a configuration needs it.

    `identifier` is what those brackets say, the service name by default. The
    audience selector stores `notify.<service>` rather than the bare service
    and has to show what it stores, which is the only reason this is an
    argument rather than `service` itself. A `detail` sentence takes the
    default: it names the same thing the picker does, brackets included, for
    the same reason `named_entity` keeps an entity id -- somebody sent to go
    and change something needs the name the configuration uses.
    """
    device = devices.get(service)
    if device is not None:
        return f"{device} ({texts[LABEL_HOME_ASSISTANT_APP]})"
    if service == PERSISTENT_NOTIFICATION_OUTPUT:
        return texts[LABEL_PERSISTENT_NOTIFICATION]
    name = service if identifier is None else identifier
    readable = service.replace("_", " ").capitalize()
    return readable if readable == name else f"{readable} ({name})"


def companion_service_name(device_name: str) -> str:
    """Return the legacy notify service name `mobile_app` gives a device.

    Core slugifies the *whole* `<prefix>_<target>` string
    (`homeassistant/components/notify/legacy.py`,
    `BaseNotificationService.async_register_services`:
    `slugify(f"{self._target_service_name_prefix}_{name}")`), so a device
    called "Alice's iPhone" becomes `mobile_app_alice_s_iphone`, not
    `mobile_app_` + a separately slugified tail. Composing it any other way
    silently fails to match on names ending in a separator.
    """
    return slugify(f"{COMPANION_OUTPUT_PREFIX}{device_name}")


def next_wake_time(local_now: datetime, wake: Any) -> datetime:
    """Return the next local occurrence of `wake` after `local_now`.

    Built by combining a *date* with the wake time and re-attaching the local
    zone, never by adding a `timedelta` to an aware datetime: on the night a
    DST transition happens, adding 24 hours would land an hour early or late.
    """
    tzinfo = local_now.tzinfo
    candidate = datetime.combine(local_now.date(), wake, tzinfo=tzinfo)
    if candidate <= local_now:
        candidate = datetime.combine(
            local_now.date() + timedelta(days=1), wake, tzinfo=tzinfo
        )
    return candidate


def selector_label(translations: Mapping[str, str], selector: str, value: str) -> str:
    """Return the words a picker shows for one stored value, value in brackets.

    `SelectSelectorConfig(translation_key=...)` is Home Assistant's own
    mechanism for labelling a coded choice, and the flow already uses it, so
    the sentence reads the very string the user picked from rather than a
    second copy in `common` that would drift.

    The stored value stays in brackets for exactly the reason `output_label`
    keeps a service name there (ADR-0018 §2): a presence rule and a priority
    floor are configuration, and somebody sent to go and change one needs the
    word the configuration uses. Where somebody *is* gets no brackets -- a
    state is not a setting anybody can go and edit.

    The raw value is the last resort, exactly as `FALLBACK_DETAIL` is: a
    missing translation must degrade to something, never to an exception in a
    diagnostic.
    """
    label = translations.get(f"{KEY_SELECTOR_PREFIX}{selector}.options.{value}")
    return value if label is None else f"{label} ({value})"


def _presence_label(translations: Mapping[str, str], state: str) -> str:
    """Return where somebody is, in words.

    Only the three states the state machine spells in its own words are
    translated. Anything else is a zone, whose name the household chose
    themselves -- "at work" is already the answer, and mapping it would be
    replacing a real name with a worse one.
    """
    key = PERSON_STATE_LABELS.get(state)
    if key is None:
        return state
    return translations.get(
        f"component.{DOMAIN}.{TRANSLATION_CATEGORY}.{key}", PERSON_STATE_FALLBACKS[key]
    )


def _fill(template: str, placeholders: Mapping[str, str]) -> str:
    """Substitute `{name}` placeholders without going through `str.format`.

    `str.format` would raise on a translation that legitimately contains a
    brace, and a `KeyError` in a diagnostic sentence is the last thing somebody
    debugging a notification needs.
    """
    text = template
    for name, value in placeholders.items():
        text = text.replace(f"{{{name}}}", value)
    return text


def _local_text(when: datetime | None) -> str:
    """Render an instant for a human, in the instance's local time."""
    if when is None:
        return ""
    return dt_util.as_local(when).isoformat(timespec="minutes")
