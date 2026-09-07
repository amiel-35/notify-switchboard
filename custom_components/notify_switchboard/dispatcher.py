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
from collections.abc import Mapping
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, Final

import voluptuous as vol
from homeassistant.const import (
    ATTR_ENTITY_ID,
    EVENT_HOMEASSISTANT_STOP,
    STATE_IDLE,
    STATE_OFF,
    STATE_ON,
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
    ATTR_PERSON,
    ATTR_TARGET,
    ATTR_USER_ID,
    AUTHENTICATED_PRIORITIES,
    COMPANION_OUTPUT_PREFIX,
    DELIVERY_EVENT_TYPES,
    DIAGNOSTICS_DECISION_LOG_SIZE,
    DOMAIN,
    DROP_DELIVERY_FAILED,
    DROP_SILENCED,
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
    ISSUE_INVALID_SERVICE_CALLS_MANY,
    ISSUE_PERSON_WITHOUT_USER_ID,
    MAX_CONSECUTIVE_OUTPUT_MISSES,
    MAX_INVALID_SERVICE_CALLS,
    MAX_SILENCE_MINUTES,
    MAX_TRACKED_INVALID_SERVICE_CALLS,
    MIN_SILENCE_MINUTES,
    PRIORITY_CRITICAL,
    SIGNAL_STATE_UPDATED,
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
    decide,
    is_recursive_output,
    parse_action,
    resolve_priority,
    split_outputs,
    state_is_on,
)
from .store import DeferredMessage, SwitchboardStore

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry

_LOGGER = logging.getLogger(__name__)

# How long one `notify.<output>` call may take before the router abandons it
# (contract v0.3, ADR-0017 §3). Deliberately a plain module constant: it is a
# backstop against a hung push service, not a tuning knob, and the acceptance
# suite patches it here rather than waiting half a minute for a timeout.
OUTPUT_TIMEOUT_SECONDS: Final = 30

NOTIFY_DOMAIN = "notify"
ALERT_DOMAIN = "alert"
SERVICE_TURN_OFF = "turn_off"
MOBILE_APP_DOMAIN = "mobile_app"

TRANSLATION_CATEGORY = "common"
KEY_ACKNOWLEDGE = f"component.{DOMAIN}.{TRANSLATION_CATEGORY}.acknowledge"
KEY_SNOOZE_MINUTES = f"component.{DOMAIN}.{TRANSLATION_CATEGORY}.snooze_minutes"
KEY_BACK_TO_NORMAL = f"component.{DOMAIN}.{TRANSLATION_CATEGORY}.back_to_normal"

FALLBACK_ACKNOWLEDGE = "Acknowledge"
FALLBACK_SNOOZE = "Snooze {minutes} min"
FALLBACK_BACK_TO_NORMAL = "Back to normal"

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
        # How many times a UI service was refused for the same unknown
        # target/person, keyed by `(field, value)` (brief item 7).
        self._invalid_service_calls: dict[tuple[str, str], int] = {}

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

        observed = sorted(
            {
                target.alert_entity
                for target in self.table.targets.values()
                if target.observer_mode and target.alert_entity
            }
        )
        if observed:
            self._unsubs.append(
                async_track_state_change_event(
                    self.hass, observed, self._async_observed_alert_changed
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
        """Detach every listener (called when the config entry unloads)."""
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

        silenced: dict[str, bool] = {}
        for person in self.table.persons.values():
            for entity_id in person.silence_entities:
                state = self.hass.states.get(entity_id)
                silenced[entity_id] = state_is_on(state.state if state else None)

        return RoutingContext(
            now=now,
            person_states=person_states,
            silenced=silenced,
            snoozes=dict(self.store.snoozes),
            temporary_silences=dict(self.store.silences),
        )

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

    def has_configured_silence(self, person: PersonConfig) -> bool:
        """Return True when one of the person's own silence entities is `on`."""
        return any(
            (state := self.hass.states.get(entity_id)) is not None
            and state.state == STATE_ON
            for entity_id in person.silence_entities
        )

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
        decision = decide(self.table, request, self.build_context())
        await self._async_apply(request, decision)
        return decision

    async def _async_apply(
        self, request: NotificationRequest, decision: RoutingDecision
    ) -> None:
        """Perform the side effects of a decision."""
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

        await self._async_deliver_all(decision, request.message, request.title)

        if store_dirty:
            await self.store.async_save()

        self._async_notify_entities()

    # ------------------------------------------------------------------
    # Delivery
    # ------------------------------------------------------------------

    async def _async_deliver_all(
        self, decision: RoutingDecision, message: str, title: str | None
    ) -> None:
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
        if not decision.routed:
            return

        results = await asyncio.gather(
            *(
                self._async_deliver(routed, message, title)
                for routed in decision.routed
            ),
            return_exceptions=True,
        )
        for routed, result in zip(decision.routed, results, strict=True):
            if isinstance(result, BaseException):  # pragma: no cover - guard
                _LOGGER.exception(
                    "Unexpected error while delivering %s to %s",
                    routed.slug,
                    routed.person,
                    exc_info=result,
                )

    async def _async_deliver(
        self, routed: RoutedDelivery, message: str, title: str | None
    ) -> None:
        """Deliver one routed message to every output of one person."""
        target = self.table.targets.get(routed.slug)
        if target is None:
            return

        # Contract §"Per-row texts": `default_title` is the outgoing title
        # whenever the caller did not supply one. Applied here, per delivery,
        # rather than on the request, so a call fanned out over several rows
        # gets each row's own default.
        if title is None:
            title = target.default_title

        payload = await self._async_build_payload(target, routed)
        # Every output of this person at once, each bounded by its own timeout:
        # a phone off the network must not hold back the tablet next to it.
        outcomes = await asyncio.gather(
            *(
                self._async_call_output(output, message, title, payload, target.slug)
                for output in routed.outputs
            ),
            return_exceptions=True,
        )
        delivered = any(outcome is True for outcome in outcomes)

        if not delivered:
            # Every output of this person failed or does not exist: the
            # message reached nobody, so it is a drop, not a delivery.
            # Counting it as routed would make the daily figure a count of
            # *intentions* rather than of notifications that went out.
            self._async_count_drop(DROP_DELIVERY_FAILED, routed.person, routed.slug)
            return

        self.routed_today += 1
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

    async def _async_build_payload(
        self, target: TargetConfig, routed: RoutedDelivery
    ) -> dict[str, Any]:
        """Build the merged `data` payload, buttons included."""
        payload = dict(routed.data)
        authenticate = routed.priority in AUTHENTICATED_PRIORITIES
        labels = await self._async_labels(target)
        actions = build_actions(target, labels, authenticate)
        if actions:
            payload[ATTR_ACTIONS] = actions
        if authenticate:
            payload[ATTR_AUTHENTICATION_REQUIRED] = True
        return payload

    async def _async_call_output(
        self,
        output: str,
        message: str,
        title: str | None,
        payload: Mapping[str, Any],
        slug: str,
    ) -> bool:
        """Call one `notify.*` output; never let a failure stop the others."""
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
            self._async_record_output_failure(output)
            _LOGGER.warning(
                "Output %s.%s does not exist (yet); will retry on the next call",
                domain,
                service,
            )
            return False

        service_data: dict[str, Any] = {"message": message}
        if title is not None:
            service_data["title"] = title
        # Companion buttons only make sense on a Companion output.
        data = dict(payload)
        if not service.startswith(COMPANION_OUTPUT_PREFIX):
            data.pop(ATTR_ACTIONS, None)
            data.pop(ATTR_AUTHENTICATION_REQUIRED, None)
        if data:
            service_data["data"] = data

        try:
            # `blocking=True` is a direct `await` of the handler's coroutine
            # (`homeassistant/core.py`, `ServiceRegistry.async_call`: "response_data
            # = await coro"), so cancelling here really does abandon the call
            # instead of leaving a detached task running behind it.
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
        # true, and nothing else would ever delete a persisted issue.
        if self.failing_outputs.pop(output, 0) > MAX_CONSECUTIVE_OUTPUT_MISSES:
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
        """Queue a silenced message until the person's wake time.

        Returns True when the message was queued (so it must not be counted as
        a drop: nothing is lost, it is simply late).
        """
        person = self.table.persons.get(person_id)
        target = self.table.targets.get(slug)
        if person is None or target is None or person.wake_time is None:
            return False

        if not self.has_configured_silence(person):
            # The only thing silencing this person is a temporary
            # `notify_switchboard.silence`, which is not a night: ADR-0016 says
            # such a message is dropped with reason `silenced`. `wake_time` is
            # documented as "the end of the night silence", so queueing a
            # message until tomorrow morning because somebody asked for an hour
            # of quiet would be the wrong kind of late.
            return False

        deferral = DeferredMessage(
            person=person_id,
            slug=slug,
            tag=request.tag or "",
            message=request.message,
            title=request.title,
            priority=resolve_priority(target, request.data),
            data=dict(request.data),
            queued_at=dt_util.utcnow(),
        )
        self.store.deferrals[deferral.key] = deferral
        self.deferred_today += 1
        self._async_schedule_deferral(person_id)
        _LOGGER.debug("Deferred %s for %s until %s", slug, person_id, person.wake_time)
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
            if person.wake_time is None:
                continue
            overdue = [
                deferral
                for key, deferral in self.store.deferrals.items()
                if key[0] == person_id
                and next_wake_time(
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

        The instant is whichever comes first: the person's next wake time, or
        the end of a temporary `notify_switchboard.silence` if one is running
        and lifts sooner. The second case matters because
        `_async_flush_deferrals` re-checks the silence and keeps a message that
        is still covered — without it, a flush held back by an hour of
        requested quiet would wait until the *next* morning to try again.

        A configured `silence_entities` going `off` early is not waited for: the
        router cannot predict when that happens, and `wake_time` is the
        documented promise.
        """
        if (unsub := self._deferral_unsubs.pop(person_id, None)) is not None:
            unsub()

        person = self.table.persons.get(person_id)
        if person is None or person.wake_time is None:
            return
        if not any(key[0] == person_id for key in self.store.deferrals):
            return

        now = dt_util.now()
        when = next_wake_time(now, person.wake_time)
        if (until := self.store.silences.get(person_id)) is not None:
            local_until = dt_util.as_local(until)
            if now < local_until < when:
                when = local_until

        async def _deliver(_now: datetime) -> None:
            self._deferral_unsubs.pop(person_id, None)
            await self._async_flush_deferrals(person_id)

        self._deferral_unsubs[person_id] = async_track_point_in_time(
            self.hass, _deliver, when
        )

    async def _async_flush_deferrals(
        self, person_id: str, only: list[DeferredMessage] | None = None
    ) -> None:
        """Deliver the messages queued for one person, then persist.

        `only` restricts the flush to a subset (the overdue ones at setup);
        by default everything queued for that person is delivered.

        The wake time is only a *prediction* that the night is over. Before
        delivering, the person's silence is re-read: a night schedule that runs
        late, a `notify_switchboard.silence` set in the small hours or a
        Home Assistant that came back up mid-night would otherwise push the
        whole queue at somebody who is still asleep — the exact thing the
        deferral exists to avoid. A message still under a silence stays queued
        and the flush is re-armed by `_async_schedule_deferral`, which picks the
        earlier of the next wake time and the end of a temporary silence.
        `critical` bypasses silence everywhere else
        (contract §"Routing decision"), so it bypasses it here too.
        """
        pending = (
            only
            if only is not None
            else [
                deferral
                for key, deferral in self.store.deferrals.items()
                if key[0] == person_id
            ]
        )
        person = self.table.persons.get(person_id)
        still_silenced = person is not None and self.is_person_silenced(person)

        deliverable: list[DeferredMessage] = []
        held: list[DeferredMessage] = []
        for deferral in pending:
            if still_silenced and deferral.priority != PRIORITY_CRITICAL:
                held.append(deferral)
            else:
                deliverable.append(deferral)

        for deferral in deliverable:
            del self.store.deferrals[deferral.key]

        for deferral in deliverable:
            target = self.table.targets.get(deferral.slug)
            if target is None or person is None:
                continue
            usable, _recursive = split_outputs(person.outputs)
            if not usable:
                continue
            routed = RoutedDelivery(
                person=person_id,
                slug=deferral.slug,
                outputs=usable,
                priority=deferral.priority,
                data=dict(deferral.data),
            )
            await self._async_deliver(routed, deferral.message, deferral.title)

        if held:
            _LOGGER.debug(
                "Keeping %d deferral(s) for %s: still silenced at the wake time",
                len(held),
                person_id,
            )
            self._async_schedule_deferral(person_id)

        if deliverable:
            await self.store.async_save()
            self._async_notify_entities()

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
        self._async_notify_entities()
        _LOGGER.debug("Silenced %s until %s", person, until.isoformat())

    async def async_service_unsilence(self, person: str) -> None:
        """Lift a temporary silence immediately.

        Idempotent by contract: a person who is not temporarily silenced has
        nothing to undo, and that is not an error.
        """
        self._require_person(person)
        self._async_clear_invalid_service_call(ATTR_PERSON, person)
        if self.store.silences.pop(person, None) is None:
            return

        self._async_cancel_silence_expiry(person)
        await self.store.async_save()
        self._async_notify_entities()

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
        `_async_call_output`).
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

    async def _async_observed_alert_changed(
        self, event: Event[EventStateChangedData]
    ) -> None:
        """Route on the observed alert's transitions (plan B, ADR-007)."""
        old_state = event.data["old_state"]
        new_state = event.data["new_state"]
        if new_state is None or old_state is None:
            return

        entity_id = event.data["entity_id"]
        targets = [
            target
            for target in self.table.targets.values()
            if target.observer_mode and target.alert_entity == entity_id
        ]
        if not targets:
            return

        old, new = old_state.state, new_state.state
        for target in targets:
            if old == STATE_IDLE and new == STATE_ON:
                message = self._observer_message(target, new_state)
            elif new == STATE_IDLE and old in (STATE_ON, STATE_OFF):
                message = await self._async_observer_done_message(target, new_state)
            else:
                # `on -> off` is an acknowledgement: nothing is routed.
                continue

            await self.async_handle_request(
                message,
                title=self._observer_title(target),
                targets=[target.slug],
            )

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
                "Target %s: could not render the row text %r: %s", target.slug, raw, err
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
    def _async_silence_changed(self, _event: Event[EventStateChangedData]) -> None:
        """Refresh `binary_sensor.<person>_silenced` when a source changes."""
        self._async_notify_entities()

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
                translation_placeholders={"person": person_id},
            )

    @staticmethod
    def _person_issue_id(person_id: str) -> str:
        """Return the `repairs` issue id used for one person."""
        return f"{ISSUE_PERSON_WITHOUT_USER_ID}_{person_id}"

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
