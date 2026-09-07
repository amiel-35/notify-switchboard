"""Pure routing decisions for Notify Switchboard.

Nothing in this module touches `hass`: it turns a routing table, a request and
a snapshot of the world (`RoutingContext`) into a `RoutingDecision`. Side
effects -- calling `notify.*`, persisting snoozes, scheduling deferrals --
live in `dispatcher.py`. That split is what makes the decision engine unit
testable (brief item 3).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
from typing import Any

from homeassistant.const import STATE_HOME, STATE_NOT_HOME, STATE_ON
from homeassistant.util import dt as dt_util, slugify

from .const import (
    ACTION_ACKNOWLEDGE,
    ACTION_NAMESPACE,
    ACTION_SNOOZE,
    ATTR_PRIORITY,
    ATTR_SWITCHBOARD_DONE,
    ATTR_TAG,
    ATTR_TTL_MINUTES,
    CONF_ALERT_ENTITY,
    CONF_ALLOW_ACKNOWLEDGE,
    CONF_AUDIENCE,
    CONF_CLEAR_DONE,
    CONF_DEFAULT_DATA,
    CONF_DEFAULT_PRIORITY,
    CONF_DEFAULT_TARGET,
    CONF_DEFAULT_TITLE,
    CONF_DONE_MESSAGE,
    CONF_MANAGED,
    CONF_MESSAGE,
    CONF_OBSERVER_MODE,
    CONF_OUTPUTS,
    CONF_PERSONS,
    CONF_PRESENCE_RULE,
    CONF_SILENCE_ENTITIES,
    CONF_SLUG,
    CONF_SNOOZE_MINUTES,
    CONF_SUMMARY,
    CONF_TARGETS,
    CONF_WAKE_TIME,
    DEFAULT_PRESENCE_RULE,
    DEFAULT_PRIORITY,
    DEFAULT_TTL_MINUTES,
    DONE_TAG_SUFFIX,
    DROP_NO_OUTPUTS,
    DROP_NOT_IN_AUDIENCE,
    DROP_NOT_NOTIFIED,
    DROP_PRESENCE,
    DROP_RECURSION,
    DROP_SILENCED,
    DROP_SNOOZED,
    DROP_UNKNOWN_PERSON,
    DROP_UNKNOWN_TARGET,
    LEGACY_SERVICE_NAME,
    PRESENCE_AWAY_ONLY,
    PRESENCE_HOME_ONLY,
    PRIORITY_CRITICAL,
    SUMMARY_TAG,
    SWITCHBOARD_DATA_PREFIX,
    TAG_PREFIX,
    VALID_PRESENCE_RULES,
    VALID_PRIORITIES,
)

NOTIFY_PREFIX = "notify."

# `switchboard:ack:<slug>` and `switchboard:snooze:<slug>:<minutes>`.
ACTION_PARTS_ACKNOWLEDGE = 3
ACTION_PARTS_SNOOZE = 4


# ---------------------------------------------------------------------------
# Routing table
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PersonConfig:
    """One row of `entry.options["persons"]`.

    `outputs` are always stored **without** the `notify.` prefix: the options
    flow accepts both spellings and `parse_person` normalises them, so
    `notify.mobile_app_x` and `mobile_app_x` are the same output everywhere
    (person resolution, Companion-button gating, recursion check).
    """

    entity_id: str
    outputs: tuple[str, ...] = ()
    silence_entities: tuple[str, ...] = ()
    wake_time: time | None = None
    # v0.5 addendum (ADR-0019 §2). Absent in the options means True, so every
    # person row written before 0.5.0 keeps behaving as it does today -- except
    # that a wake time now delivers one digest instead of a burst.
    summary: bool = True

    @property
    def object_id(self) -> str:
        """Return the object_id of the person entity (`person.alice` -> `alice`)."""
        return self.entity_id.partition(".")[2] or self.entity_id


@dataclass(frozen=True, slots=True)
class TargetConfig:
    """One row of `entry.options["targets"]` -- the routing table."""

    slug: str
    name: str
    default_priority: str = DEFAULT_PRIORITY
    alert_entity: str | None = None
    audience: tuple[str, ...] = ()
    presence_rule: str = DEFAULT_PRESENCE_RULE
    allow_acknowledge: bool = False
    snooze_minutes: tuple[int, ...] = ()
    default_data: dict[str, Any] = field(default_factory=dict)
    observer_mode: bool = False
    # Per-row optional texts (v0.2 addendum, ADR-0016). `message` and
    # `done_message` are templates rendered with the row's alert state exposed
    # as `alert`; `default_title` is the outgoing title when no caller gave one.
    message: str | None = None
    done_message: str | None = None
    default_title: str | None = None
    # v0.4 addendum (ADR-0018 §4). Absent in the options means False, so every
    # row written before 0.4.0 keeps behaving exactly as it does today. It
    # changes nothing about routing: it only tells the options flow that this
    # row's audience is the router's to keep in sync.
    managed: bool = False
    # v0.5 addendum (ADR-0019 §6). Absent means False: the "back to normal"
    # message rings and then stays on the phone, which is why it never shares
    # the episode's own tag.
    clear_done: bool = False

    @property
    def service_name(self) -> str:
        """Return the legacy notify service name for this row."""
        return f"{LEGACY_SERVICE_NAME}_{self.slug}"


@dataclass(frozen=True, slots=True)
class RoutingTable:
    """The whole configuration, parsed once per config entry load."""

    persons: dict[str, PersonConfig] = field(default_factory=dict)
    targets: dict[str, TargetConfig] = field(default_factory=dict)
    default_target: str | None = None

    def person_for_output(self, output: str) -> PersonConfig | None:
        """Return the single person owning `output`, or None if ambiguous."""
        wanted = normalise_output(output)
        owners = [
            person for person in self.persons.values() if wanted in person.outputs
        ]
        if len(owners) == 1:
            return owners[0]
        return None


# ---------------------------------------------------------------------------
# Requests, contexts and decisions
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class NotificationRequest:
    """A single inbound request to `notify.switchboard[_<slug>]`."""

    message: str
    title: str | None = None
    targets: tuple[str, ...] = ()
    data: dict[str, Any] = field(default_factory=dict)

    @property
    def tag(self) -> str | None:
        """Return `data.tag` when the caller provided one."""
        tag = self.data.get(ATTR_TAG)
        return str(tag) if tag is not None else None

    @property
    def is_done(self) -> bool:
        """Return True when this call marks itself as a "back to normal"."""
        return is_done_message(self.data)


@dataclass(frozen=True, slots=True)
class RoutingContext:
    """A snapshot of everything the decision needs to read from the world."""

    now: datetime
    person_states: dict[str, str] = field(default_factory=dict)
    # Configured `silence_entities` (entity_id -> is it `on`): read, never owned.
    silenced: dict[str, bool] = field(default_factory=dict)
    snoozes: dict[tuple[str, str], datetime] = field(default_factory=dict)
    # Temporary, router-owned silences (person -> expiry), ADR-0016. Defaults to
    # empty so every Sprint 1 caller of `decide` keeps its exact behaviour.
    temporary_silences: dict[str, datetime] = field(default_factory=dict)
    # Who each row's current episode actually reached (v0.5, ADR-0019 §5). A
    # slug is a key of this mapping **iff** its row names an `alert_entity`, so
    # an absent key means "this row has no episodes" and an empty set means
    # "this episode reached nobody". Only a `done` message reads it.
    episode_recipients: dict[str, frozenset[str]] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class RoutedDelivery:
    """One (person, target) pair that must be delivered."""

    person: str
    slug: str
    outputs: tuple[str, ...]
    priority: str
    data: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class DroppedDelivery:
    """One (person, target) pair that will not be delivered, and why."""

    person: str | None
    slug: str
    reason: str


@dataclass(frozen=True, slots=True)
class RoutingDecision:
    """The outcome of routing one `NotificationRequest`."""

    routed: tuple[RoutedDelivery, ...] = ()
    dropped: tuple[DroppedDelivery, ...] = ()


# ---------------------------------------------------------------------------
# Options parsing (pure)
# ---------------------------------------------------------------------------


def parse_wake_time(raw: Any) -> time | None:
    """Parse a `"HH:MM[:SS]"` wake time, returning None when unusable."""
    if raw in (None, ""):
        return None
    if isinstance(raw, time):
        return raw
    return dt_util.parse_time(str(raw))


def normalise_output(raw: Any) -> str:
    """Return an output service name without its `notify.` prefix.

    Users write either `mobile_app_x` or `notify.mobile_app_x`; both name the
    same service, so everything downstream compares the bare form.
    """
    return str(raw).removeprefix(NOTIFY_PREFIX)


def parse_person(raw: dict[str, Any]) -> PersonConfig:
    """Build a `PersonConfig` from one raw options row."""
    return PersonConfig(
        entity_id=str(raw["entity_id"]),
        outputs=tuple(
            normalise_output(output) for output in raw.get(CONF_OUTPUTS) or ()
        ),
        silence_entities=tuple(
            str(entity) for entity in raw.get(CONF_SILENCE_ENTITIES) or ()
        ),
        wake_time=parse_wake_time(raw.get(CONF_WAKE_TIME)),
        # Absent means "summarise": the key is only written when it is False.
        summary=bool(raw.get(CONF_SUMMARY, True)),
    )


def parse_target(raw: dict[str, Any]) -> TargetConfig:
    """Build a `TargetConfig` from one raw options row."""
    priority = str(raw.get(CONF_DEFAULT_PRIORITY) or DEFAULT_PRIORITY)
    if priority not in VALID_PRIORITIES:
        priority = DEFAULT_PRIORITY
    presence_rule = str(raw.get(CONF_PRESENCE_RULE) or DEFAULT_PRESENCE_RULE)
    if presence_rule not in VALID_PRESENCE_RULES:
        presence_rule = DEFAULT_PRESENCE_RULE
    slug = slugify(str(raw[CONF_SLUG]))
    return TargetConfig(
        slug=slug,
        name=str(raw.get("name") or slug),
        default_priority=priority,
        alert_entity=raw.get(CONF_ALERT_ENTITY) or None,
        audience=tuple(str(person) for person in raw.get(CONF_AUDIENCE) or ()),
        presence_rule=presence_rule,
        allow_acknowledge=bool(raw.get(CONF_ALLOW_ACKNOWLEDGE)),
        snooze_minutes=tuple(
            int(minutes) for minutes in raw.get(CONF_SNOOZE_MINUTES) or ()
        ),
        default_data=dict(raw.get(CONF_DEFAULT_DATA) or {}),
        observer_mode=bool(raw.get(CONF_OBSERVER_MODE)),
        message=_optional_text(raw.get(CONF_MESSAGE)),
        done_message=_optional_text(raw.get(CONF_DONE_MESSAGE)),
        default_title=_optional_text(raw.get(CONF_DEFAULT_TITLE)),
        managed=bool(raw.get(CONF_MANAGED)),
        clear_done=bool(raw.get(CONF_CLEAR_DONE)),
    )


def _optional_text(raw: Any) -> str | None:
    """Return a non-empty row text, or None.

    An empty string in the options is the same as "not configured": the row
    falls back to whatever the contract says it falls back to, instead of
    routing an empty message or an empty title.
    """
    if raw is None:
        return None
    text = str(raw).strip()
    return text or None


def build_routing_table(options: dict[str, Any]) -> RoutingTable:
    """Parse `entry.options` into a `RoutingTable`.

    Malformed rows are skipped rather than raising: a config entry must always
    load, even if a hand-edited `.storage` file lost a key.
    """
    persons: dict[str, PersonConfig] = {}
    for raw in options.get(CONF_PERSONS) or ():
        if not isinstance(raw, dict) or not raw.get("entity_id"):
            continue
        person = parse_person(raw)
        persons[person.entity_id] = person

    targets: dict[str, TargetConfig] = {}
    for raw in options.get(CONF_TARGETS) or ():
        if not isinstance(raw, dict) or not raw.get(CONF_SLUG):
            continue
        target = parse_target(raw)
        targets[target.slug] = target

    default_target = options.get(CONF_DEFAULT_TARGET) or None
    if default_target is not None and default_target not in targets:
        default_target = next(iter(targets), None)

    return RoutingTable(persons=persons, targets=targets, default_target=default_target)


# ---------------------------------------------------------------------------
# Decision primitives (pure)
# ---------------------------------------------------------------------------


def is_recursive_output(output: str) -> bool:
    """Return True when an output points back at this integration.

    Contract "Output": an output resolving to `notify.switchboard*` is rejected
    at config time and at runtime.
    """
    name = output.removeprefix(NOTIFY_PREFIX)
    return name == LEGACY_SERVICE_NAME or name.startswith(f"{LEGACY_SERVICE_NAME}_")


def resolve_priority(target: TargetConfig, data: dict[str, Any]) -> str:
    """Return the effective priority: `data.priority` overrides the row's."""
    raw = data.get(ATTR_PRIORITY)
    if isinstance(raw, str) and raw in VALID_PRIORITIES:
        return raw
    return target.default_priority


def presence_allows(presence_rule: str, person_state: str | None) -> bool:
    """Evaluate the row's presence rule against a `person.*` state."""
    if presence_rule == PRESENCE_HOME_ONLY:
        return person_state == STATE_HOME
    if presence_rule == PRESENCE_AWAY_ONLY:
        return person_state == STATE_NOT_HOME
    return True


def has_configured_silence(person: PersonConfig, context: RoutingContext) -> bool:
    """Return True when any of the person's own silence entities is `on`."""
    return any(
        context.silenced.get(entity_id, False) for entity_id in person.silence_entities
    )


def has_temporary_silence(person_id: str, context: RoutingContext) -> bool:
    """Return True when a `notify_switchboard.silence` has not expired yet."""
    until = context.temporary_silences.get(person_id)
    return until is not None and until > context.now


def is_silenced(person: PersonConfig, context: RoutingContext) -> bool:
    """Return True when the person is silent, whichever source says so.

    ADR-0016: the two sources are independent and combine with an OR. A
    configured `schedule`/`input_boolean` is read and never owned; a temporary
    silence is owned by the router and expires on its own. Either one produces
    the same `silenced` drop reason, and `critical` bypasses both.
    """
    return has_configured_silence(person, context) or has_temporary_silence(
        person.entity_id, context
    )


def snooze_is_active(person: str, slug: str, context: RoutingContext) -> bool:
    """Return True when a stored snooze for (person, target) has not expired."""
    expiry = context.snoozes.get((person, slug))
    return expiry is not None and expiry > context.now


def merge_data(target: TargetConfig, caller_data: dict[str, Any]) -> dict[str, Any]:
    """Merge the row's `default_data` under the caller's `data` (caller wins)."""
    return {**target.default_data, **caller_data}


def split_outputs(
    outputs: tuple[str, ...],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Split a person's outputs into (usable, recursive)."""
    usable = tuple(output for output in outputs if not is_recursive_output(output))
    recursive = tuple(output for output in outputs if is_recursive_output(output))
    return usable, recursive


# ---------------------------------------------------------------------------
# v0.5 primitives: identity, time-to-live and the `done` marker (ADR-0019)
# ---------------------------------------------------------------------------


def is_done_message(data: Mapping[str, Any]) -> bool:
    """Return True when a call marks itself as a "back to normal" (§5).

    `data.switchboard_done: true` is the public, documented key a blueprint
    sets on the message it sends itself; observer mode sets the same key on the
    message it generates, so both paths are one rule downstream.
    """
    return bool(data.get(ATTR_SWITCHBOARD_DONE))


def default_tag(slug: str, *, done: bool = False) -> str:
    """Return the deterministic `data.tag` of a message on row `slug` (§6).

    A notification you cannot name is one you can never clear. The `done`
    message deliberately does **not** share the episode's tag: `clear_done`
    defaults to off, and a "back to normal" carrying `switchboard-<slug>` could
    not be kept on the phone while the episode's own notifications are cleared.
    """
    return f"{TAG_PREFIX}{slug}{DONE_TAG_SUFFIX if done else ''}"


def caller_tag(data: Mapping[str, Any]) -> str | None:
    """Return the `data.tag` the caller wrote, or None when there is not one.

    Worth telling apart from the router's own default because the two do not
    travel to the same outputs (ADR-0019 §6, amendment 2026-09-07 (2)): a key
    the caller wrote is proxied to every output, a key the router added goes
    only to the outputs that read it. An empty tag is not a name, so it counts
    as absent here exactly as it does in `effective_tag`.
    """
    caller = data.get(ATTR_TAG)
    if caller is not None and str(caller):
        return str(caller)
    return None


def effective_tag(slug: str, data: Mapping[str, Any]) -> str:
    """Return the tag a message will actually travel with.

    A caller-supplied `data.tag` always wins; the default only fills a gap.
    """
    return caller_tag(data) or default_tag(slug, done=is_done_message(data))


def _minutes(raw: Any) -> int | None:
    """Return a usable number of minutes, or None when there is not one.

    A bool is not a duration even though Python says it is an `int`, and a
    string, a `None` or an object is a configuration mistake rather than a
    promise the router should try to honour.
    """
    if isinstance(raw, bool) or not isinstance(raw, int | float):
        return None
    return int(raw)


def resolve_ttl(
    priority: str, data: Mapping[str, Any], mapping: Mapping[str, Any] | None = None
) -> timedelta | None:
    """Return the time-to-live of a deferred message, or None for "never" (§1).

    Read at **flush** time, from the deferral's stored priority and stored
    `data`, never frozen at queue time: the mapping is a household policy, not a
    per-message promise, so shortening `info` at 02:00 means it for what is
    already waiting.

    Precedence: `data.ttl_minutes` (where `0` means "this message never
    expires", the caller's opt-out in the other direction), then
    `entry.options["ttl_minutes"]`, then `DEFAULT_TTL_MINUTES`. An absent key
    means the default; an explicit `null` means never. `critical` is absent
    from the defaults and can be given no entry, so it never expires -- which
    is moot, since a critical message is never deferred in the first place.
    """
    per_call = _minutes(data.get(ATTR_TTL_MINUTES))
    if per_call is not None:
        return None if per_call <= 0 else timedelta(minutes=per_call)

    if mapping is not None and priority in mapping:
        configured: Any = mapping[priority]
    else:
        configured = DEFAULT_TTL_MINUTES.get(priority)

    minutes = _minutes(configured)
    if minutes is None or minutes <= 0:
        return None
    return timedelta(minutes=minutes)


def collapse_by_tag(items: list[tuple[str, Any]]) -> list[Any]:
    """Collapse `(tag, item)` pairs to the last item of each tag (§2).

    `items` is in queue order, newest last, and the survivor of a collapsed
    group keeps the position of its **latest** member -- which is also the one
    that is kept, since a summary line has to say what is true now rather than
    what was true first. The key is the effective tag alone, across rows: two
    rows a caller deliberately tagged the same are one line, not two.
    """
    last: dict[str, int] = {}
    for index, (tag, _item) in enumerate(items):
        last[tag] = index
    keep = set(last.values())
    return [item for index, (_tag, item) in enumerate(items) if index in keep]


def summary_data(payloads: list[Mapping[str, Any]]) -> dict[str, Any]:
    """Build a summary's `data`: built, not merged (§2).

    Only the switchboard's own keys survive -- the frozen `switchboard-summary`
    tag and the union of the `switchboard_*` keys of the collapsed survivors,
    later message wins. No caller key, no row `default_data`, no `priority`,
    and explicitly no `actions` and no `authenticationRequired`: three rows'
    worth of `data` cannot be merged without contradicting each other, and an
    Acknowledge button on a digest of three alerts would acknowledge an
    arbitrary one of them.
    """
    data: dict[str, Any] = {ATTR_TAG: SUMMARY_TAG}
    for payload in payloads:
        for key, value in payload.items():
            if key.startswith(SWITCHBOARD_DATA_PREFIX):
                data[key] = value
    return data


def _decide_for_person(
    table: RoutingTable,
    target: TargetConfig,
    person_id: str,
    context: RoutingContext,
    *,
    priority: str,
    bypass: bool,
    payload: dict[str, Any],
) -> tuple[RoutedDelivery | None, tuple[DroppedDelivery, ...]]:
    """Apply contract §"Routing decision" to one person of one row.

    Extracted from `decide` so that each of the two loops stays readable, and
    so the order of the rules -- audience, presence, silence, snooze, outputs --
    lives in exactly one place. A person can produce both a drop and a delivery
    (`recursion` alongside the usable outputs), which is why the refusals come
    back as a tuple rather than as a single reason.
    """
    slug = target.slug
    person = table.persons.get(person_id)
    if person is None:
        # The row names somebody the switchboard does not know about; the
        # options flow rejects this, a hand-edited file may not. Unlike
        # `not_in_audience` this *is* a loss: the row expected that person to be
        # notified and nobody was, so it is counted.
        return None, (DroppedDelivery(person_id, slug, DROP_UNKNOWN_PERSON),)

    if not presence_allows(target.presence_rule, context.person_states.get(person_id)):
        return None, (DroppedDelivery(person_id, slug, DROP_PRESENCE),)

    if not bypass and is_silenced(person, context):
        return None, (DroppedDelivery(person_id, slug, DROP_SILENCED),)

    if not bypass and snooze_is_active(person_id, slug, context):
        return None, (DroppedDelivery(person_id, slug, DROP_SNOOZED),)

    usable, recursive = split_outputs(person.outputs)
    refusals: tuple[DroppedDelivery, ...] = ()
    if recursive:
        refusals = (DroppedDelivery(person_id, slug, DROP_RECURSION),)
    if not usable:
        if not recursive:
            refusals = (DroppedDelivery(person_id, slug, DROP_NO_OUTPUTS),)
        return None, refusals

    return (
        RoutedDelivery(
            person=person_id,
            slug=slug,
            outputs=usable,
            priority=priority,
            data=dict(payload),
        ),
        refusals,
    )


def decide(
    table: RoutingTable, request: NotificationRequest, context: RoutingContext
) -> RoutingDecision:
    """Turn a request into a routing decision (contract "Routing decision")."""
    routed: list[RoutedDelivery] = []
    dropped: list[DroppedDelivery] = []

    for slug in request.targets:
        target = table.targets.get(slug)
        if target is None:
            dropped.append(DroppedDelivery(None, slug, DROP_UNKNOWN_TARGET))
            continue

        priority = resolve_priority(target, request.data)
        bypass = priority == PRIORITY_CRITICAL
        payload = merge_data(target, request.data)
        # A `done` message reaches only the persons the episode it closes
        # actually reached (ADR-0019 §5). `None` means "this row has no
        # episodes", which is every row that names no `alert_entity`, and is
        # what keeps `not_notified` unreachable for a household that never
        # wrote an `alert:` block.
        recipients = context.episode_recipients.get(slug) if request.is_done else None

        for person_id in target.audience:
            if recipients is not None and person_id not in recipients:
                # Filtered before the rest of the decision runs: "back to
                # normal" is a strange thing to receive about a problem you
                # never heard of.
                dropped.append(DroppedDelivery(person_id, slug, DROP_NOT_NOTIFIED))
                continue

            delivery, refusals = _decide_for_person(
                table,
                target,
                person_id,
                context,
                priority=priority,
                bypass=bypass,
                payload=payload,
            )
            dropped.extend(refusals)
            if delivery is not None:
                routed.append(delivery)

        for person_id in table.persons:
            if person_id not in target.audience:
                dropped.append(DroppedDelivery(person_id, slug, DROP_NOT_IN_AUDIENCE))

    return RoutingDecision(routed=tuple(routed), dropped=tuple(dropped))


def build_actions(
    target: TargetConfig, labels: dict[str, str], authenticate: bool
) -> list[dict[str, Any]]:
    """Build the Companion `actions` list for a row (contract "Buttons").

    `labels` maps `acknowledge` and `snooze_<minutes>` to already translated
    strings; the caller owns translation so this stays pure.
    """
    actions: list[dict[str, Any]] = []
    if target.allow_acknowledge and target.alert_entity:
        action: dict[str, Any] = {
            "action": acknowledge_action(target.slug),
            "title": labels.get("acknowledge", "Acknowledge"),
        }
        if authenticate:
            action["authenticationRequired"] = True
        actions.append(action)

    for minutes in target.snooze_minutes:
        action = {
            "action": snooze_action(target.slug, minutes),
            "title": labels.get(f"snooze_{minutes}", f"Snooze {minutes}"),
        }
        if authenticate:
            action["authenticationRequired"] = True
        actions.append(action)

    return actions


def acknowledge_action(slug: str) -> str:
    """Return the Companion action id acknowledging `slug`."""
    return f"{ACTION_NAMESPACE}:{ACTION_ACKNOWLEDGE}:{slug}"


def snooze_action(slug: str, minutes: int) -> str:
    """Return the Companion action id snoozing `slug` for `minutes`."""
    return f"{ACTION_NAMESPACE}:{ACTION_SNOOZE}:{slug}:{minutes}"


@dataclass(frozen=True, slots=True)
class ParsedAction:
    """A parsed `switchboard:<verb>:<slug>[:<minutes>]` Companion action."""

    verb: str
    slug: str
    minutes: int | None = None


def parse_action(raw: Any) -> ParsedAction | None:
    """Parse a Companion action id, returning None when it is not ours."""
    if not isinstance(raw, str):
        return None
    parts = raw.split(":")
    if len(parts) < ACTION_PARTS_ACKNOWLEDGE or parts[0] != ACTION_NAMESPACE:
        return None

    verb, slug = parts[1], parts[2]
    if verb == ACTION_ACKNOWLEDGE and len(parts) == ACTION_PARTS_ACKNOWLEDGE:
        return ParsedAction(verb=verb, slug=slug)
    if verb == ACTION_SNOOZE and len(parts) == ACTION_PARTS_SNOOZE:
        minutes = _positive_int(parts[3])
        if minutes is not None:
            return ParsedAction(verb=verb, slug=slug, minutes=minutes)
    return None


def _positive_int(raw: str) -> int | None:
    """Return a strictly positive integer, or None."""
    try:
        value = int(raw)
    except ValueError:
        return None
    return value if value > 0 else None


def state_is_on(state: str | None) -> bool:
    """Return True when a silence entity's state means "silent"."""
    return state == STATE_ON
