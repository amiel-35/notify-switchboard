"""Pure routing decisions for Notify Switchboard.

Nothing in this module touches `hass`: it turns a routing table, a request and
a snapshot of the world (`RoutingContext`) into a `RoutingDecision`. Side
effects -- calling `notify.*`, persisting snoozes, scheduling deferrals --
live in `dispatcher.py`. That split is what makes the decision engine unit
testable (brief item 3).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, time
from typing import Any

from homeassistant.const import STATE_HOME, STATE_NOT_HOME, STATE_ON
from homeassistant.util import dt as dt_util, slugify

from .const import (
    ACTION_ACKNOWLEDGE,
    ACTION_NAMESPACE,
    ACTION_SNOOZE,
    ATTR_PRIORITY,
    ATTR_TAG,
    CONF_ALERT_ENTITY,
    CONF_ALLOW_ACKNOWLEDGE,
    CONF_AUDIENCE,
    CONF_CLASS,
    CONF_DEFAULT_DATA,
    CONF_DEFAULT_PRIORITY,
    CONF_DEFAULT_TARGET,
    CONF_OBSERVER_MODE,
    CONF_OUTPUTS,
    CONF_PERSONS,
    CONF_PRESENCE_RULE,
    CONF_SILENCE_ENTITIES,
    CONF_SLUG,
    CONF_SNOOZE_MINUTES,
    CONF_TARGETS,
    CONF_WAKE_TIME,
    DEFAULT_PRESENCE_RULE,
    DEFAULT_PRIORITY,
    DROP_NO_OUTPUTS,
    DROP_NOT_IN_AUDIENCE,
    DROP_PRESENCE,
    DROP_RECURSION,
    DROP_SILENCED,
    DROP_SNOOZED,
    DROP_UNKNOWN_TARGET,
    LEGACY_SERVICE_NAME,
    PRESENCE_AWAY_ONLY,
    PRESENCE_HOME_ONLY,
    PRIORITY_CRITICAL,
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
    """One row of `entry.options["persons"]`."""

    entity_id: str
    outputs: tuple[str, ...] = ()
    silence_entities: tuple[str, ...] = ()
    wake_time: time | None = None

    @property
    def object_id(self) -> str:
        """Return the object_id of the person entity (`person.alice` -> `alice`)."""
        return self.entity_id.partition(".")[2] or self.entity_id


@dataclass(frozen=True, slots=True)
class TargetConfig:
    """One row of `entry.options["targets"]` -- the routing table."""

    slug: str
    name: str
    target_class: str = ""
    default_priority: str = DEFAULT_PRIORITY
    alert_entity: str | None = None
    audience: tuple[str, ...] = ()
    presence_rule: str = DEFAULT_PRESENCE_RULE
    allow_acknowledge: bool = False
    snooze_minutes: tuple[int, ...] = ()
    default_data: dict[str, Any] = field(default_factory=dict)
    observer_mode: bool = False

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
        owners = [
            person for person in self.persons.values() if output in person.outputs
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


@dataclass(frozen=True, slots=True)
class RoutingContext:
    """A snapshot of everything the decision needs to read from the world."""

    now: datetime
    person_states: dict[str, str] = field(default_factory=dict)
    silenced: dict[str, bool] = field(default_factory=dict)
    snoozes: dict[tuple[str, str], datetime] = field(default_factory=dict)


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


def parse_person(raw: dict[str, Any]) -> PersonConfig:
    """Build a `PersonConfig` from one raw options row."""
    return PersonConfig(
        entity_id=str(raw["entity_id"]),
        outputs=tuple(str(output) for output in raw.get(CONF_OUTPUTS) or ()),
        silence_entities=tuple(
            str(entity) for entity in raw.get(CONF_SILENCE_ENTITIES) or ()
        ),
        wake_time=parse_wake_time(raw.get(CONF_WAKE_TIME)),
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
        target_class=str(raw.get(CONF_CLASS) or ""),
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
    )


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


def is_silenced(person: PersonConfig, context: RoutingContext) -> bool:
    """Return True when any of the person's silence entities is `on`."""
    return any(
        context.silenced.get(entity_id, False) for entity_id in person.silence_entities
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

        for person_id in target.audience:
            person = table.persons.get(person_id)
            if person is None:
                # The row names somebody the switchboard does not know about;
                # the options flow rejects this, a hand-edited file may not.
                dropped.append(DroppedDelivery(person_id, slug, DROP_NOT_IN_AUDIENCE))
                continue

            if not presence_allows(
                target.presence_rule, context.person_states.get(person_id)
            ):
                dropped.append(DroppedDelivery(person_id, slug, DROP_PRESENCE))
                continue

            if not bypass and is_silenced(person, context):
                dropped.append(DroppedDelivery(person_id, slug, DROP_SILENCED))
                continue

            if not bypass and snooze_is_active(person_id, slug, context):
                dropped.append(DroppedDelivery(person_id, slug, DROP_SNOOZED))
                continue

            usable, recursive = split_outputs(person.outputs)
            if recursive:
                dropped.append(DroppedDelivery(person_id, slug, DROP_RECURSION))
            if not usable:
                if not recursive:
                    dropped.append(DroppedDelivery(person_id, slug, DROP_NO_OUTPUTS))
                continue

            routed.append(
                RoutedDelivery(
                    person=person_id,
                    slug=slug,
                    outputs=usable,
                    priority=priority,
                    data=dict(payload),
                )
            )

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
