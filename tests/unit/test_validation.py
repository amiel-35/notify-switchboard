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


# ---------------------------------------------------------------------------
# v0.7 (ADR-0021 §5): an audience entry may be a `notify.*` service name
# ---------------------------------------------------------------------------


def test_a_bare_output_is_a_valid_audience_entry() -> None:
    """The domain is the whole rule: a `notify.*` name is not an unknown person."""
    assert (
        validate_target(
            a_target(audience=["person.alice", "notify.kitchen_speaker"]),
            [],
            ["person.alice"],
            is_new=True,
        )
        == {}
    )


def test_a_bare_output_pointing_back_at_the_switchboard_is_refused() -> None:
    """The recursion guard does not care which side of the audience it is on."""
    errors = validate_target(
        a_target(audience=["person.alice", "notify.switchboard_leak"]),
        [],
        ["person.alice"],
        is_new=True,
    )
    assert errors["audience"] == "recursive_output"


def test_an_audience_of_bare_outputs_only_is_valid() -> None:
    """A target may address nothing but things: no person is not no audience."""
    assert (
        validate_target(
            a_target(audience=["notify.kitchen_speaker"]),
            [],
            ["person.alice"],
            is_new=True,
        )
        == {}
    )


@pytest.mark.parametrize("entry", ["notify.notify", "notify.send_message"])
def test_a_notify_component_service_is_refused_as_an_audience_entry(entry) -> None:
    """The domain rule lets these in; neither can ever be a recipient.

    `notify.notify` is the aggregate legacy service — it fans the message out
    to every notify platform on the instance, which is the undifferentiated
    channel this router replaces, and no episode can say who it reached.
    `notify.send_message` is the entity action: its schema requires an
    `entity_id`, so the call built for a bare output fails every time. The
    pickers hide both, but `custom_value=True` makes both typable.
    """
    errors = validate_target(
        a_target(audience=["person.alice", entry]),
        [],
        ["person.alice"],
        is_new=True,
    )
    assert errors["audience"] == "component_service_output"


def test_persistent_notification_stays_a_valid_bare_output() -> None:
    """The third component service is the one that *is* a destination.

    It takes a plain `message`, it names exactly one place, and it is what a
    household uses before any phone is registered.
    """
    assert (
        validate_target(
            a_target(audience=["notify.persistent_notification"]),
            [],
            ["person.alice"],
            is_new=True,
        )
        == {}
    )
