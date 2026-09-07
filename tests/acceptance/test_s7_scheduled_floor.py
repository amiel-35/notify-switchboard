"""A scheduled priority floor — a night that holds the shopping list and lets the leak through.

Written before the Sprint 7 implementation exists, against:

- `docs/contract.md` §"v0.7 addendum (ADR-0021)" → "A scheduled priority floor"
- `docs/ADR/0021-escalation-and-places-reduced.md` §2
- `docs/sprints/sprint-7-brief.md` item 2

Until 0.6.0 a person is silent or not, and there is nothing in between. The
floor is the in-between, and it is carried by an entity the household already
owns rather than by an option of ours: a `schedule`'s per-block `data:` is
validated by `CUSTOM_DATA_SCHEMA = vol.Schema({str: vol.Any(bool, str, int,
float)})` and, while that block is the active one, `Schedule._update`
(`$HA_CORE_SRC/homeassistant/components/schedule/__init__.py`) does
`self._attr_extra_state_attributes.update(current_data)` — so the floor is a
state attribute of an entity the router already reads, and the router reads it
the way it reads everything else about a silence entity: by attribute, never by
domain.

Priorities rank `info < normal < high < critical`. There is **no** per-person
`min_priority` option (ADR-0021 §9) and **no** new drop reason.

**Two silence entities, on purpose.** What a silence the floor *catches* does
to a message is already decided and is not this sprint's business: a
`schedule.*` publishes the end of its current block, so ADR-0020 §3 **defers**
against it, while an `input_boolean` or a plain `binary_sensor` publishes no
end and drops with `silenced`. The tests below use whichever of the two makes
the assertion legible, and the last one pins that the floor changed only which
calls are caught.
"""

from __future__ import annotations

from .conftest import explain, make_entry, make_person, make_target

NIGHT = "binary_sensor.alice_night"


def _entry(
    hass,
    *,
    silence_entities: list[str] | None = None,
    wake_time: str | None = None,
):
    return make_entry(
        hass,
        persons=[
            make_person(
                "person.alice",
                ["mobile_app_alice"],
                silence_entities=silence_entities,
                wake_time=wake_time,
            )
        ],
        targets=[
            make_target("leak", "Leak", audience=["person.alice"]),
        ],
        default_target="leak",
    )


def _silence(hass, entity_id: str, floor: str | None = None) -> str:
    """Turn on one plain silence entity, optionally carrying a floor.

    Deliberately not a `schedule`: this entity publishes no end, so a call the
    silence catches is **dropped** with `silenced` (ADR-0020 §3) and the reason
    is assertable. It is also the case ADR-0021 §2 means when it says the
    router reads the attribute and never the domain.
    """
    attributes = {"min_priority": floor} if floor is not None else {}
    hass.states.async_set(entity_id, "on", attributes)
    return entity_id


async def _send(hass, *, priority: str | None = None, message: str = "Leak!"):
    payload: dict = {"message": message}
    if priority is not None:
        payload["data"] = {"priority": priority}
    await hass.services.async_call("notify", "switchboard_leak", payload, blocking=True)
    await hass.async_block_till_done()


def _messages(calls) -> list[str]:
    return [call.data["message"] for call in calls["mobile_app_alice"]]


async def test_a_schedule_block_floor_lets_the_calls_at_or_above_it_through(
    hass,
    enable_custom_integrations,
    install,
    mock_outputs,
    set_person,
    schedule_silence,
    deferred_sensor,
):
    """A night that holds the shopping list and lets the leak through."""
    calls = mock_outputs("mobile_app_alice")
    set_person("person.alice", "home")
    night = await schedule_silence("night", {"min_priority": "high"})
    await install(_entry(hass, silence_entities=[night]))

    await _send(hass, priority="normal", message="the shopping list")
    assert _messages(calls) == []
    assert deferred_sensor().state == "1", (
        "a call below the block's floor is caught by the silence exactly as an "
        "unfloored one is — and a `schedule` publishes the end of its block, so "
        "it is held rather than dropped (ADR-0020 §3, ADR-0021 §2)"
    )

    await _send(hass, priority="high", message="the leak")
    assert _messages(calls) == ["the leak"], (
        "a call at or above the floor is not caught at all (ADR-0021 §2)"
    )


async def test_a_silence_entity_without_the_attribute_still_holds_everything(
    hass,
    enable_custom_integrations,
    install,
    mock_outputs,
    set_person,
    schedule_silence,
    deferred_sensor,
):
    """The half of the rule that must not change: a plain silence is a silence."""
    calls = mock_outputs("mobile_app_alice")
    set_person("person.alice", "home")
    night = await schedule_silence("night")
    await install(_entry(hass, silence_entities=[night]))

    await _send(hass, priority="high")

    assert _messages(calls) == []
    assert deferred_sensor().state == "1"


async def test_an_unreadable_floor_holds_everything(
    hass,
    enable_custom_integrations,
    install,
    mock_outputs,
    set_person,
    schedule_silence,
    deferred_sensor,
):
    """A typo fails towards quiet, never towards noise.

    `CUSTOM_DATA_SCHEMA` accepts any string, so `min_priority: loud` reaches
    the state attributes intact. It is not one of the four priorities, so the
    entity behaves as an ordinary silence (ADR-0021 §2).
    """
    calls = mock_outputs("mobile_app_alice")
    set_person("person.alice", "home")
    night = await schedule_silence("night", {"min_priority": "loud"})
    await install(_entry(hass, silence_entities=[night]))

    await _send(hass, priority="high")

    assert _messages(calls) == []
    assert deferred_sensor().state == "1"


async def test_critical_still_bypasses_a_block_that_carries_a_floor(
    hass,
    enable_custom_integrations,
    install,
    mock_outputs,
    set_person,
    schedule_silence,
):
    """`critical` remains the one priority that bypasses a silence, floor or no floor."""
    calls = mock_outputs("mobile_app_alice")
    set_person("person.alice", "home")
    night = await schedule_silence("night", {"min_priority": "critical"})
    await install(_entry(hass, silence_entities=[night]))

    await _send(hass, priority="critical")

    assert len(calls["mobile_app_alice"]) == 1


async def test_the_router_reads_the_attribute_and_not_the_domain(
    hass, enable_custom_integrations, install, mock_outputs, set_person, drop_reasons
):
    """A plain `binary_sensor` that carries a floor is read like a `schedule`.

    Nowhere else does the router care what kind of entity a silence is — it
    asks `state == "on"` and nothing more (`router.state_is_on`) — and a domain
    check here would be the only exception in the module. This entity also
    publishes no end, so the call the floor catches is **dropped** with the
    existing `silenced` reason: no new reason is introduced (ADR-0021 §2).
    """
    calls = mock_outputs("mobile_app_alice")
    set_person("person.alice", "home")
    _silence(hass, NIGHT, "high")
    await install(_entry(hass, silence_entities=[NIGHT]))

    await _send(hass, priority="normal", message="the shopping list")
    assert _messages(calls) == []
    assert "silenced" in drop_reasons()

    await _send(hass, priority="high", message="the leak")
    assert _messages(calls) == ["the leak"]


async def test_the_strictest_of_two_floors_decides(
    hass, enable_custom_integrations, install, mock_outputs, set_person, drop_reasons
):
    """Silence is an OR across sources, and a floor narrows one source, not the union."""
    calls = mock_outputs("mobile_app_alice")
    set_person("person.alice", "home")
    lenient = _silence(hass, "binary_sensor.alice_evening", "normal")
    strict = _silence(hass, NIGHT, "high")
    await install(_entry(hass, silence_entities=[lenient, strict]))

    await _send(hass, priority="normal", message="held by the stricter one")
    assert _messages(calls) == []
    assert "silenced" in drop_reasons()

    await _send(hass, priority="high", message="above both")
    assert _messages(calls) == ["above both"], (
        "a call at or above every `on` floor passes (ADR-0021 §2)"
    )


async def test_a_floor_alongside_a_silence_that_carries_none_holds_everything(
    hass, enable_custom_integrations, install, mock_outputs, set_person, drop_reasons
):
    """One floor-less silence is enough: it silences everything, so the person is quiet."""
    calls = mock_outputs("mobile_app_alice")
    set_person("person.alice", "home")
    floored = _silence(hass, NIGHT, "info")
    plain = _silence(hass, "binary_sensor.alice_focus")
    await install(_entry(hass, silence_entities=[floored, plain]))

    await _send(hass, priority="high")

    assert _messages(calls) == []
    assert "silenced" in drop_reasons()


async def test_a_floor_changes_which_calls_are_caught_not_what_happens_to_them(
    hass,
    enable_custom_integrations,
    install,
    mock_outputs,
    set_person,
    schedule_silence,
    deferred_sensor,
):
    """A caught call is held for the wake time exactly as an unfloored one is."""
    calls = mock_outputs("mobile_app_alice")
    set_person("person.alice", "home")
    night = await schedule_silence("night", {"min_priority": "high"})
    await install(_entry(hass, silence_entities=[night], wake_time="07:00:00"))

    await _send(hass, priority="normal", message="held until morning")
    await _send(hass, priority="high", message="through now")

    assert _messages(calls) == ["through now"]
    assert deferred_sensor().state == "1", (
        "the floor decides which calls the silence catches; a caught call is "
        "deferred exactly as before (ADR-0021 §2)"
    )


async def test_explain_names_the_entity_that_holds_the_floor_and_the_floor_itself(
    hass, enable_custom_integrations, install, mock_outputs, set_person
):
    """Naming the entity is what sends the user to the right switch."""
    mock_outputs("mobile_app_alice")
    set_person("person.alice", "home")
    _silence(hass, NIGHT, "high")
    await install(_entry(hass, silence_entities=[NIGHT]))

    answer = (await explain(hass, target="leak", priority="normal"))["persons"][
        "person.alice"
    ]

    assert answer["reason"] == "silenced"
    assert NIGHT in answer["detail"]
    assert "high" in answer["detail"], (
        "the `detail` of a floored silence names the floor as well as the "
        "entity, or the user cannot tell why `high` got through. Got "
        f"{answer['detail']!r}"
    )
