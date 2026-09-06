"""Unit tests for the pure options validation rules."""

from __future__ import annotations

import pytest

from custom_components.notify_switchboard.validation import (
    parse_snooze_minutes,
    validate_person,
    validate_target,
)


def a_person(**overrides) -> dict:
    """Build a valid person row."""
    row = {
        "entity_id": "person.alice",
        "outputs": ["mobile_app_alice"],
        "silence_entities": [],
        "wake_time": None,
    }
    row.update(overrides)
    return row


def a_target(**overrides) -> dict:
    """Build a valid routing-table row."""
    row = {
        "slug": "leak",
        "name": "Leak",
        "class": "building",
        "default_priority": "normal",
        "alert_entity": None,
        "audience": ["person.alice"],
        "presence_rule": "always",
        "allow_acknowledge": False,
        "snooze_minutes": "15, 60",
        "default_data": {},
        "observer_mode": False,
    }
    row.update(overrides)
    return row


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, ([], True)),
        ("", ([], True)),
        ([], ([], True)),
        ("15, 60", ([15, 60], True)),
        ([15, 60], ([15, 60], True)),
        ("15,", ([15], True)),
        ("soon", ([], False)),
        ("0", ([], False)),
        ("-5", ([], False)),
    ],
)
def test_parse_snooze_minutes(raw, expected) -> None:
    """Durations are comma-separated positive whole minutes."""
    assert parse_snooze_minutes(raw) == expected


def test_valid_person_has_no_errors() -> None:
    """A well-formed person row passes."""
    assert validate_person(a_person(), [], is_new=True) == {}


@pytest.mark.parametrize(
    ("overrides", "field", "error"),
    [
        ({"entity_id": "light.alice"}, "entity_id", "not_a_person"),
        ({"outputs": []}, "outputs", "no_outputs"),
        ({"outputs": ["switchboard_leak"]}, "outputs", "recursive_output"),
        ({"outputs": ["notify.switchboard"]}, "outputs", "recursive_output"),
        ({"outputs": ["Mobile App Alice"]}, "outputs", "invalid_output"),
        ({"silence_entities": ["nope"]}, "silence_entities", "invalid_entity"),
        ({"wake_time": "not a time"}, "wake_time", "invalid_time"),
    ],
)
def test_invalid_person_rows(overrides, field, error) -> None:
    """Each rule reports on its own field."""
    errors = validate_person(a_person(**overrides), [], is_new=True)
    assert errors[field] == error


def test_duplicate_person_is_rejected_only_when_new() -> None:
    """Editing an existing person is allowed; adding it twice is not."""
    existing = [a_person()]
    assert validate_person(a_person(), existing, is_new=True) == {
        "entity_id": "duplicate_person"
    }
    assert validate_person(a_person(), existing, is_new=False) == {}


def test_valid_target_has_no_errors() -> None:
    """A well-formed routing-table row passes."""
    assert validate_target(a_target(), [], ["person.alice"], is_new=True) == {}


@pytest.mark.parametrize(
    ("overrides", "field", "error"),
    [
        ({"slug": ""}, "slug", "invalid_slug"),
        ({"slug": "Fuite d'eau"}, "slug", "invalid_slug"),
        ({"default_priority": "urgent"}, "default_priority", "invalid_priority"),
        ({"presence_rule": "maybe"}, "presence_rule", "invalid_presence_rule"),
        ({"alert_entity": "sensor.leak"}, "alert_entity", "not_an_alert"),
        ({"audience": []}, "audience", "empty_audience"),
        ({"audience": ["person.ghost"]}, "audience", "unknown_person"),
        ({"snooze_minutes": "soon"}, "snooze_minutes", "invalid_snooze_minutes"),
        ({"default_data": "channel: family"}, "default_data", "invalid_default_data"),
    ],
)
def test_invalid_target_rows(overrides, field, error) -> None:
    """Each rule reports on its own field."""
    errors = validate_target(a_target(**overrides), [], ["person.alice"], is_new=True)
    assert errors[field] == error


def test_duplicate_slug_is_rejected_only_when_new() -> None:
    """Editing a row keeps its slug; adding a second row with it does not."""
    existing = [a_target()]
    assert validate_target(a_target(), existing, ["person.alice"], is_new=True) == {
        "slug": "duplicate_slug"
    }
    assert validate_target(a_target(), existing, ["person.alice"], is_new=False) == {}


def test_alert_entity_may_be_empty() -> None:
    """A row without an alert is valid."""
    assert (
        validate_target(a_target(alert_entity=None), [], ["person.alice"], is_new=True)
        == {}
    )
