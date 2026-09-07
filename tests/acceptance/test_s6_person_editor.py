"""The person editor in two steps, and what an absent wake time means.

Written before the Sprint 6 implementation exists, against:

- `docs/contract.md` §"v0.6 addendum (ADR-0020)" → "`wake_time` is optional,
  and its absence has a meaning" and "Four options-flow step ids are public"
- `docs/ADR/0020-consolidation.md` §2 and §3
- `docs/sprints/sprint-6-brief.md` item 2

`person_outputs` keeps the two fields a first install has to fill — the notify
services and the silence entities — and `wake_time` and `summary` move to
`person_advanced`.

Moving `wake_time` behind a second step is only honest if leaving it empty
still protects the night. Up to 0.5.1 it does not: `_async_defer` refuses to
queue anything for a person with no wake time, so a silenced message is
dropped. ADR-0020 §3 decides the narrow case where that becomes a deferral —
a silence entity that publishes its own end, which in core 2026.9.1 means a
`schedule.*` and its `next_event` state attribute
(`$HA_CORE_SRC/homeassistant/components/schedule/const.py`,
`ScheduleEntityStateAttribute.NEXT_EVENT`) — and the last test here pins the
boundary: a silence with no end still drops, exactly as it always has.

Time is moved the way every S5 test moves it (see `README.md`, "Moving time"):
absolute UTC instants with the local equivalent in a comment. The flush test
fires **no timer** on purpose — the delivery has to be caused by the schedule
turning `off`, or an implementation that only reacts to a wake time would look
correct.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import homeassistant.util.dt as dt_util
import voluptuous as vol
from homeassistant.data_entry_flow import FlowResultType

from .conftest import make_entry, make_person, make_target, schema_field

# ADR-0020 §2: the two steps of the person editor.
OUTPUT_FIELDS = ["outputs", "silence_entities"]
ADVANCED_FIELDS = ["wake_time", "summary"]

NIGHT = datetime(2026, 9, 10, 21, 30, tzinfo=dt_util.UTC)  # 23:30 Europe/Paris
SEVEN_AM = datetime(2026, 9, 11, 5, 0, tzinfo=dt_util.UTC)  # 07:00 Europe/Paris
TOMORROW_NIGHT = datetime(2026, 9, 11, 21, 0, tzinfo=dt_util.UTC)  # 23:00 local


def _field_names(result) -> list[str]:
    """Return the keys of a flow step's schema, in declaration order."""
    return [str(marker) for marker in result["data_schema"].schema]


def _default(result, key: str) -> Any:
    """Return the default declared for one field, or None when it has none."""
    marker, _validator = schema_field(result, key)
    default = marker.default
    if default is vol.UNDEFINED:
        return None
    return default()


def _person(entry, entity_id: str) -> dict[str, Any]:
    """Return one person row of the stored options."""
    rows = [row for row in entry.options["persons"] if row["entity_id"] == entity_id]
    assert rows, f"no person {entity_id!r} in {entry.options['persons']}"
    return rows[0]


# ---------------------------------------------------------------------------
# The shape of the two steps
# ---------------------------------------------------------------------------


async def test_person_outputs_asks_exactly_two_things(
    hass, enable_custom_integrations, install, options_flow, mock_outputs
):
    """The one form a first install has to fill stays at two fields."""
    mock_outputs("mobile_app_alice")
    entry = await install(make_entry(hass, persons=[], targets=[], default_target=None))

    result = await options_flow(entry, "person", {"entity_id": "person.alice"})

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "person_outputs", (
        "`person_outputs` is a public step id (contract v0.6)"
    )
    assert _field_names(result) == OUTPUT_FIELDS, (
        "the wake time and the night summary are preferences, not "
        "prerequisites: they moved to `person_advanced` (ADR-0020 §2)"
    )


async def test_person_advanced_holds_the_wake_time_and_the_summary(
    hass, enable_custom_integrations, install, options_flow
):
    """The night settings, behind their own menu entry, with 0.5 defaults."""
    entry = await install(
        make_entry(
            hass,
            persons=[make_person("person.alice", ["mobile_app_alice"])],
            targets=[make_target("leak", "Leak", audience=["person.alice"])],
            default_target="leak",
        )
    )

    result = await options_flow(
        entry, "edit_person_advanced", {"entity_id": "person.alice"}
    )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "person_advanced", (
        "`person_advanced` is a public step id (contract v0.6), reached from "
        "the 'Advanced settings of a person' menu entry (ADR-0020 §2)"
    )
    assert _field_names(result) == ADVANCED_FIELDS
    assert _default(result, "wake_time") is None, (
        "the wake time has no default and never had one; ADR-0020 §3 gives "
        "its absence a meaning instead of inventing a value"
    )
    assert _default(result, "summary") is True, (
        "`summary` still defaults to on (contract v0.5); only the step it "
        "lives in moved"
    )


# ---------------------------------------------------------------------------
# The split must not lose anything
# ---------------------------------------------------------------------------


async def test_a_person_saved_without_the_advanced_step_has_no_wake_time(
    hass, enable_custom_integrations, install, options_flow, mock_outputs
):
    """Two answers, and the stored row is the 0.5 row for those two answers."""
    mock_outputs("mobile_app_alice")
    entry = await install(make_entry(hass, persons=[], targets=[], default_target=None))

    result = await options_flow(
        entry,
        "person",
        {"entity_id": "person.alice"},
        {"outputs": ["mobile_app_alice"], "silence_entities": []},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY

    assert _person(entry, "person.alice") == make_person(
        "person.alice", ["mobile_app_alice"]
    ), (
        "an untouched `summary` is still absent from the row and an untouched "
        "`wake_time` is still `None` (contract v0.5, kept by ADR-0020 §2)"
    )


async def test_editing_the_outputs_keeps_a_stored_wake_time(
    hass, enable_custom_integrations, install, options_flow, mock_outputs
):
    """Changing a phone must not be able to delete somebody's night."""
    mock_outputs("mobile_app_alice", "mobile_app_alice_watch")
    entry = await install(
        make_entry(
            hass,
            persons=[
                make_person(
                    "person.alice",
                    ["mobile_app_alice"],
                    silence_entities=["input_boolean.alice_night"],
                    wake_time="07:00:00",
                    summary=False,
                )
            ],
            targets=[make_target("leak", "Leak", audience=["person.alice"])],
            default_target="leak",
        )
    )

    result = await options_flow(
        entry,
        "edit_person",
        {"entity_id": "person.alice"},
        {
            "outputs": ["mobile_app_alice", "mobile_app_alice_watch"],
            "silence_entities": ["input_boolean.alice_night"],
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY

    row = _person(entry, "person.alice")
    assert row["outputs"] == ["mobile_app_alice", "mobile_app_alice_watch"]
    assert row["wake_time"] == "07:00:00", (
        "the basic step writes its own two fields and touches neither of the "
        "advanced ones (ADR-0020 §2)"
    )
    assert row["summary"] is False


# ---------------------------------------------------------------------------
# What an absent wake time means (ADR-0020 §3)
# ---------------------------------------------------------------------------


def _entry_with_schedule_silence(hass):
    """One person, no wake time, silenced by a `schedule.*`."""
    return make_entry(
        hass,
        persons=[
            make_person(
                "person.alice",
                ["mobile_app_alice"],
                silence_entities=["schedule.alice_night"],
            )
        ],
        targets=[make_target("leak", "Leak", audience=["person.alice"])],
        default_target="leak",
    )


async def test_without_a_wake_time_a_schedule_silence_defers_until_its_end(
    hass,
    enable_custom_integrations,
    install,
    mock_outputs,
    set_person,
    freezer,
    deferred_sensor,
    drop_reasons,
):
    """23:30: held back, not dropped; 07:00: delivered, with no timer fired."""
    await hass.config.async_set_time_zone("Europe/Paris")
    calls = mock_outputs("mobile_app_alice")
    set_person("person.alice", "home")

    freezer.move_to(NIGHT)
    # A `schedule.*` publishes the end of the block it is in, which is the
    # instant this deferral is bounded by (ADR-0020 §3).
    hass.states.async_set(
        "schedule.alice_night", "on", {"next_event": SEVEN_AM.isoformat()}
    )
    await install(_entry_with_schedule_silence(hass))

    await hass.services.async_call(
        "notify", "switchboard_leak", {"message": "queued at 23:30"}, blocking=True
    )
    await hass.async_block_till_done()

    assert len(calls["mobile_app_alice"]) == 0
    assert "silenced" not in drop_reasons(), (
        "a person with no wake time and a silence that ends is held back, not "
        "dropped: that is what makes the wake time genuinely optional "
        "(ADR-0020 §3)"
    )
    assert deferred_sensor().state == "1", (
        "a deferral made this way is a deferral like any other and is counted "
        "as one (contract v0.6)"
    )

    freezer.move_to(SEVEN_AM)
    hass.states.async_set(
        "schedule.alice_night", "off", {"next_event": TOMORROW_NIGHT.isoformat()}
    )
    await hass.async_block_till_done()

    assert [call.data["message"] for call in calls["mobile_app_alice"]] == [
        "queued at 23:30"
    ], (
        "the schedule turning `off` is what flushes the queue — the early "
        "flush of ADR-0019 §4, now reachable without a wake time"
    )


async def test_without_a_wake_time_a_silence_that_never_ends_still_drops(
    hass,
    enable_custom_integrations,
    install,
    mock_outputs,
    set_person,
    drop_reasons,
):
    """The boundary of §3, and the promise that nothing else changed.

    Green from the start, on purpose: an `input_boolean` publishes no end, so
    deferring against it would queue a message with no upper bound and nothing
    to report as `explain`'s `until`. Every installation that has left
    `wake_time` empty since 0.1.0 keeps the behaviour it has.
    """
    calls = mock_outputs("mobile_app_alice")
    set_person("person.alice", "home")
    hass.states.async_set("input_boolean.alice_night", "on")

    await install(
        make_entry(
            hass,
            persons=[
                make_person(
                    "person.alice",
                    ["mobile_app_alice"],
                    silence_entities=["input_boolean.alice_night"],
                )
            ],
            targets=[make_target("leak", "Leak", audience=["person.alice"])],
            default_target="leak",
        )
    )

    await hass.services.async_call(
        "notify", "switchboard_leak", {"message": "water"}, blocking=True
    )
    await hass.async_block_till_done()

    assert len(calls["mobile_app_alice"]) == 0
    assert "silenced" in drop_reasons(), (
        "a silence with no published end and no wake time drops, exactly as "
        "in v0.1 → v0.5 (contract v0.6, the table of §`wake_time`)"
    )
