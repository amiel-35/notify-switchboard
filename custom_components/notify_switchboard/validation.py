"""Pure validation of the routing table, shared by the options flow.

Kept free of `hass` so the rules are unit-testable and so the whole schema can
be validated before anything is written (doctrine §5: concurrent edits must
never leave half a table behind).
"""

from __future__ import annotations

from typing import Any

from homeassistant.util import slugify

from .const import (
    CONF_ALERT_ENTITY,
    CONF_AUDIENCE,
    CONF_DEFAULT_PRIORITY,
    CONF_DONE_PRIORITY,
    CONF_OUTPUTS,
    CONF_PRESENCE_RULE,
    CONF_SILENCE_ENTITIES,
    CONF_SLUG,
    CONF_SNOOZE_MINUTES,
    VALID_PRESENCE_RULES,
    VALID_PRIORITIES,
)
from .router import (
    is_bare_output,
    is_component_service_output,
    is_recursive_output,
    parse_wake_time,
)

PERSON_DOMAIN = "person"
ALERT_DOMAIN = "alert"

# ADR-0022 §1: what a name that slugifies to nothing becomes.
FALLBACK_SLUG = "alert"


def derive_slug(name: Any, existing: list[str]) -> str:
    """Return the slug a new target called `name` gets (ADR-0022 §1).

    `slugify(name)`, de-duplicated against the slugs already in the table by
    appending `_2`, `_3`, ... -- the rule core's `IDManager.generate_id`
    applies to helper ids (`homeassistant/helpers/collection.py`), so the
    result reads like every other id the user has met.
    """
    text = str(name or "")
    # Core's `slugify` answers "unknown" for a text it can make nothing of;
    # a name made only of punctuation gets the documented fallback instead.
    base = (slugify(text) if any(char.isalnum() for char in text) else "") or (
        FALLBACK_SLUG
    )
    taken = set(existing)
    proposal, attempt = base, 1
    while proposal in taken:
        attempt += 1
        proposal = f"{base}_{attempt}"
    return proposal


def normalise_wake_time(raw: Any) -> str | None:
    """Return a typed wake time as `"HH:MM:SS"`, or None when it is unreadable.

    ADR-0022 §6: people type `7:30`, `07:30`, `7h30` or `7 h 30`; the options
    keep the `"HH:MM:SS"` string the contract documents. Hours alone (`7`)
    are refused, like core's own `parse_time` refuses them.
    """
    text = str(raw or "").strip().lower().replace(" ", "")
    if not text:
        return None
    text = text.replace("h", ":")
    if text.endswith(":"):
        text += "00"
    if not 2 <= len(text.split(":")) <= 3:  # noqa: PLR2004 - H:M or H:M:S
        return None
    parsed = parse_wake_time(text)
    return parsed.strftime("%H:%M:%S") if parsed is not None else None


def parse_snooze_minutes(raw: Any) -> tuple[list[int], bool]:
    """Parse a snooze duration list, returning (durations, ok)."""
    if raw in (None, "", []):
        return [], True
    if isinstance(raw, str):
        parts = [part.strip() for part in raw.split(",") if part.strip()]
    else:
        parts = [str(part).strip() for part in raw]
    minutes: list[int] = []
    for part in parts:
        try:
            value = int(part)
        except ValueError:
            return [], False
        if value <= 0:
            return [], False
        minutes.append(value)
    return minutes, True


def validate_person(
    row: dict[str, Any], existing: list[dict[str, Any]], *, is_new: bool
) -> dict[str, str]:
    """Validate one person row; return a mapping of field -> error key."""
    errors: dict[str, str] = {}

    entity_id = str(row.get("entity_id") or "")
    if not entity_id.startswith(f"{PERSON_DOMAIN}."):
        errors["entity_id"] = "not_a_person"
    elif is_new and any(other.get("entity_id") == entity_id for other in existing):
        errors["entity_id"] = "duplicate_person"

    outputs = [str(output).strip() for output in row.get(CONF_OUTPUTS) or []]
    if not outputs:
        errors[CONF_OUTPUTS] = "no_outputs"
    for output in outputs:
        if is_recursive_output(output):
            errors[CONF_OUTPUTS] = "recursive_output"
            break
        if slugify(output.removeprefix("notify.")) != output.removeprefix("notify."):
            errors[CONF_OUTPUTS] = "invalid_output"
            break

    for entity in row.get(CONF_SILENCE_ENTITIES) or []:
        if "." not in str(entity):
            errors[CONF_SILENCE_ENTITIES] = "invalid_entity"
            break

    wake_time = row.get("wake_time")
    if wake_time not in (None, "") and parse_wake_time(wake_time) is None:
        errors["wake_time"] = "invalid_time"

    return errors


def validate_target(
    row: dict[str, Any],
    existing: list[dict[str, Any]],
    known_persons: list[str],
    *,
    is_new: bool,
) -> dict[str, str]:
    """Validate one routing-table row; return a mapping of field -> error key."""
    errors: dict[str, str] = {}

    slug = str(row.get(CONF_SLUG) or "")
    if not slug or slugify(slug) != slug:
        errors[CONF_SLUG] = "invalid_slug"
    elif is_new and any(other.get(CONF_SLUG) == slug for other in existing):
        errors[CONF_SLUG] = "duplicate_slug"

    priority = row.get(CONF_DEFAULT_PRIORITY)
    if priority not in VALID_PRIORITIES:
        errors[CONF_DEFAULT_PRIORITY] = "invalid_priority"

    # v0.9 (ADR-0023 §2.1): optional, absent meaning `normal`.
    done_priority = row.get(CONF_DONE_PRIORITY)
    if done_priority is not None and done_priority not in VALID_PRIORITIES:
        errors[CONF_DONE_PRIORITY] = "invalid_priority"

    presence_rule = row.get(CONF_PRESENCE_RULE)
    if presence_rule not in VALID_PRESENCE_RULES:
        errors[CONF_PRESENCE_RULE] = "invalid_presence_rule"

    alert_entity = row.get(CONF_ALERT_ENTITY)
    if alert_entity and not str(alert_entity).startswith(f"{ALERT_DOMAIN}."):
        errors[CONF_ALERT_ENTITY] = "not_an_alert"

    # v0.7 addendum (ADR-0021 §5): an audience entry may be a `notify.*`
    # service name -- a kitchen speaker, a wall tablet's toast overlay -- and
    # the domain is the whole rule. A bare output is refused for two reasons
    # and no others: pointing back at the switchboard, which an output has
    # always been refused for, and naming one of the `notify` component's own
    # services that cannot be a recipient (`is_component_service_output`).
    # The pickers already hide both, but both are typable.
    audience = [str(entry) for entry in row.get(CONF_AUDIENCE) or []]
    bare = [entry for entry in audience if is_bare_output(entry)]
    persons = [entry for entry in audience if not is_bare_output(entry)]
    if not audience:
        errors[CONF_AUDIENCE] = "empty_audience"
    elif any(is_recursive_output(entry) for entry in bare):
        errors[CONF_AUDIENCE] = "recursive_output"
    elif any(is_component_service_output(entry) for entry in bare):
        errors[CONF_AUDIENCE] = "component_service_output"
    elif any(person not in known_persons for person in persons):
        errors[CONF_AUDIENCE] = "unknown_person"

    _minutes, ok = parse_snooze_minutes(row.get(CONF_SNOOZE_MINUTES))
    if not ok:
        errors[CONF_SNOOZE_MINUTES] = "invalid_snooze_minutes"

    default_data = row.get("default_data")
    if default_data not in (None, "") and not isinstance(default_data, dict):
        errors["default_data"] = "invalid_default_data"

    return errors
