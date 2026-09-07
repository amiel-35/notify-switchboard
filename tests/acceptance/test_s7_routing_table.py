"""`sensor.switchboard_routing_table` — the table, so cards stop copying it.

Written before the Sprint 7 implementation exists, against:

- `docs/contract.md` §"v0.7 addendum (ADR-0021)" → "`sensor.switchboard_routing_table`"
- `docs/ADR/0021-escalation-and-places-reduced.md` §3
- `docs/sprints/sprint-7-brief.md` item 3

Every card written against this integration so far re-declares the slugs, the
names, the snooze durations and the wake times in its own YAML, because nothing
exposes them — and that copy goes stale on the first options-flow edit,
silently.

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
                escalate_when_nobody_home=True,
            ),
            make_target("garage", "Garage", audience=["person.alice"]),
        ],
        default_target="leak",
    )


FROZEN_NAME = (
    "`sensor.switchboard_routing_table` is a frozen public name "
    "(contract v0.7, ADR-0021 §3)"
)


def _rows(state, key: str) -> dict[str, dict]:
    """Return one attribute list keyed by its identifying field."""
    assert state is not None, FROZEN_NAME
    identifier = "slug" if key == "targets" else "entity_id"
    return {row[identifier]: row for row in state.attributes[key]}


async def test_the_state_is_the_target_count_and_targets_reflect_the_options(
    hass, enable_custom_integrations, install, mock_outputs, routing_table_sensor
):
    """Two targets, and each one reported with the six fields a card needs."""
    mock_outputs("mobile_app_alice", "mobile_app_bob")
    await install(_entry(hass))

    state = routing_table_sensor()
    assert state is not None, FROZEN_NAME
    assert state.state == "2", "the state is the number of targets"

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
        "`alert_entity` is `null` on a target that names none, never absent: a "
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

    `escalate_when_nobody_home` is on the `leak` target of this fixture on
    purpose — a key ADR-0021 itself adds, and which still does not belong in
    the entity.
    """
    mock_outputs("mobile_app_alice", "mobile_app_bob")
    await install(_entry(hass))

    state = routing_table_sensor()
    assert state is not None, FROZEN_NAME
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
    """`default_data` is the one target key that carries whatever the user put in it.

    A webhook path, an API key, a phone number: state attributes are readable
    by anybody who can read the state machine, so the key is not exposed and
    neither is its content, anywhere in either list (ADR-0021 §3).
    """
    mock_outputs("mobile_app_alice", "mobile_app_bob")
    await install(_entry(hass))

    state = routing_table_sensor()
    assert state is not None, FROZEN_NAME
    serialised = json.dumps(
        {
            "targets": state.attributes["targets"],
            "persons": state.attributes["persons"],
        }
    )
    assert "default_data" not in serialised
    assert SECRET not in serialised, (
        "the target's `default_data` value must not appear anywhere in the "
        "entity's attributes"
    )
    assert "outputs" not in serialised, (
        "a person's `notify.*` services are their devices; `explain` discloses "
        "them to a caller who asks about that person, this entity does not"
    )


async def test_an_audience_reports_a_bare_output_verbatim(
    hass, enable_custom_integrations, install, mock_outputs, routing_table_sensor
):
    """`audience` is what the audience is, bare outputs included (ADR-0021 §5)."""
    mock_outputs("mobile_app_alice", "kitchen_speaker")
    await install(
        make_entry(
            hass,
            persons=[make_person("person.alice", ["mobile_app_alice"])],
            targets=[
                make_target(
                    "leak",
                    "Leak",
                    audience=["person.alice", "notify.kitchen_speaker"],
                )
            ],
            default_target="leak",
        )
    )

    targets = _rows(routing_table_sensor(), "targets")
    assert targets["leak"]["audience"] == ["person.alice", "notify.kitchen_speaker"]


async def test_both_attributes_are_excluded_from_the_recorder(
    hass, enable_custom_integrations, install, mock_outputs, routing_table_sensor
):
    """Configuration is not history: neither list is written to the database.

    Home Assistant publishes an entity's excluded attributes on the state
    object itself — `Entity.async_internal_added_to_hass` sets
    `self._state_info = {"unrecorded_attributes":
    self.__combined_unrecorded_attributes}`
    (`$HA_CORE_SRC/homeassistant/helpers/entity.py`), which is what
    `recorder/db_schema.py` reads when it serialises a state — so the promise
    is assertable without setting up the recorder. The declaration is the same
    `_unrecorded_attributes` mechanism `schedule` uses for its own custom block
    data.
    """
    mock_outputs("mobile_app_alice", "mobile_app_bob")
    await install(_entry(hass))

    state = routing_table_sensor()
    assert state is not None, FROZEN_NAME
    state_info = state.state_info
    assert state_info is not None, (
        "the entity must declare `_unrecorded_attributes`; a state written "
        "without any declaration carries no `state_info` at all"
    )
    unrecorded = set(state_info["unrecorded_attributes"])
    assert {"targets", "persons"} <= unrecorded, (
        "both attributes are excluded from the recorder (contract v0.7, "
        f"ADR-0021 §3); got {sorted(unrecorded)}"
    )
