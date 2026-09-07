"""`sensor.switchboard_routing_table` — the table, so cards stop copying it.

Written before the Sprint 6 implementation exists, against:

- `docs/contract.md` §"v0.6 addendum (ADR-0020)" → "`sensor.switchboard_routing_table`"
- `docs/ADR/0020-bounded-declarative-escalation.md` §5
- `docs/sprints/sprint-6-brief.md` item 5

Every card written against this integration so far re-declares the slugs, the
names, the snooze durations and the wake times in its own YAML, because nothing
exposes them — and that copy goes stale on the first options-flow edit, silently.

The entity is deliberately **not** a dump of the options. Its two lists carry
exactly the keys the contract names and nothing else: what is in it is frozen
for ever, `default_data` is where a user's secrets end up, and a card that
needs to know what *would* happen already has `notify_switchboard.explain`.
"""

from __future__ import annotations

import json

from .conftest import make_entry, make_person, make_target

TARGET_KEYS = frozenset(
    {"slug", "name", "alert_entity", "snooze_minutes", "allow_acknowledge", "audience"}
)
PERSON_KEYS = frozenset({"entity_id", "wake_time", "summary"})

SECRET = "s3cret-webhook-path"


def _entry(hass):
    return make_entry(
        hass,
        persons=[
            make_person("person.alice", ["mobile_app_alice"], wake_time="07:00:00"),
            make_person("person.bob", ["mobile_app_bob"], summary=False),
        ],
        targets=[
            make_target(
                "leak",
                "Fuite d'eau",
                alert_entity="alert.leak",
                audience=["person.alice", "person.bob"],
                allow_acknowledge=True,
                snooze_minutes=[15, 60],
                default_data={"channel": SECRET},
            ),
            make_target("garage", "Garage", audience=["person.alice"]),
        ],
        default_target="leak",
    )


def _rows(state, key: str) -> dict[str, dict]:
    """Return one attribute list keyed by its identifying field."""
    identifier = "slug" if key == "targets" else "entity_id"
    return {row[identifier]: row for row in state.attributes[key]}


async def test_the_state_is_the_row_count_and_targets_reflect_the_options(
    hass, enable_custom_integrations, install, mock_outputs, routing_table_sensor
):
    """Two rows, and each one reported with the six fields a card needs."""
    mock_outputs("mobile_app_alice", "mobile_app_bob")
    await install(_entry(hass))

    state = routing_table_sensor()
    assert state is not None, (
        "`sensor.switchboard_routing_table` is a frozen public name "
        "(contract v0.6, ADR-0020 §5)"
    )
    assert state.state == "2", "the state is the number of routing-table rows"

    targets = _rows(state, "targets")
    assert list(targets) == ["leak", "garage"], (
        "`targets` follows the order of the routing table"
    )
    assert targets["leak"] == {
        "slug": "leak",
        "name": "Fuite d'eau",
        "alert_entity": "alert.leak",
        "snooze_minutes": [15, 60],
        "allow_acknowledge": True,
        "audience": ["person.alice", "person.bob"],
    }
    assert targets["garage"]["alert_entity"] is None, (
        "`alert_entity` is `null` on a row that names none, never absent: a "
        "card reads the same shape for every row"
    )


async def test_the_persons_attribute_carries_the_entity_id_wake_time_and_summary(
    hass, enable_custom_integrations, install, mock_outputs, routing_table_sensor
):
    """A card showing "quiet until 07:00" stops hard-coding 07:00."""
    mock_outputs("mobile_app_alice", "mobile_app_bob")
    await install(_entry(hass))

    persons = _rows(routing_table_sensor(), "persons")
    assert list(persons) == ["person.alice", "person.bob"]
    assert persons["person.alice"] == {
        "entity_id": "person.alice",
        "wake_time": "07:00:00",
        "summary": True,
    }
    assert persons["person.bob"] == {
        "entity_id": "person.bob",
        "wake_time": None,
        "summary": False,
    }


async def test_each_row_carries_exactly_the_documented_keys(
    hass, enable_custom_integrations, install, mock_outputs, routing_table_sensor
):
    """The lists are closed: nothing is added to either without a new ADR.

    That is also how places (Router S7) stay out of a contract they are not in
    yet: a row that grew a `place` key would fail here.
    """
    mock_outputs("mobile_app_alice", "mobile_app_bob")
    await install(_entry(hass))

    state = routing_table_sensor()
    for row in state.attributes["targets"]:
        assert set(row) == TARGET_KEYS, (
            f"a target row is exactly {sorted(TARGET_KEYS)}; got {sorted(row)}"
        )
    for row in state.attributes["persons"]:
        assert set(row) == PERSON_KEYS, (
            f"a person row is exactly {sorted(PERSON_KEYS)}; got {sorted(row)}"
        )


async def test_default_data_never_leaks_into_the_entity(
    hass, enable_custom_integrations, install, mock_outputs, routing_table_sensor
):
    """`default_data` is the one row key that carries whatever the user put in it.

    A webhook path, an API key, a phone number: state attributes are readable
    by anybody who can read the state machine, so the key is not exposed and
    neither is its content, anywhere in either list (ADR-0020 §5).
    """
    mock_outputs("mobile_app_alice", "mobile_app_bob")
    await install(_entry(hass))

    state = routing_table_sensor()
    serialised = json.dumps(
        {
            "targets": state.attributes["targets"],
            "persons": state.attributes["persons"],
        }
    )
    assert "default_data" not in serialised
    assert SECRET not in serialised, (
        "the row's `default_data` value must not appear anywhere in the "
        "entity's attributes"
    )
    assert "outputs" not in serialised, (
        "a person's `notify.*` services are their devices; `explain` discloses "
        "them to a caller who asks about that person, this entity does not"
    )
