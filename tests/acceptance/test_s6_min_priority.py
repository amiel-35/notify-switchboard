"""Priority floors — a person, and a schedule block, that let only the loud through.

Written before the Sprint 6 implementation exists, against:

- `docs/contract.md` §"v0.6 addendum (ADR-0020)" → "Priority floors"
- `docs/ADR/0020-bounded-declarative-escalation.md` §6
- `docs/sprints/sprint-6-brief.md` item 6

Until 0.5.0 a person is silent or not, and there is nothing in between. The two
floors here are the in-between: a standing one on the person row, and a
scheduled one carried by a silence entity — so a night can let a leak through
and hold the shopping list, with no automation and nothing of ours running.

The scheduled half leans on core's `schedule` and on nothing else of ours. A
`schedule`'s per-block `data:` is validated by
`CUSTOM_DATA_SCHEMA = vol.Schema({str: vol.Any(bool, str, int, float)})` and,
while that block is the active one, `Schedule._update`
(`$HA_CORE_SRC/homeassistant/components/schedule/__init__.py`) does
`self._attr_extra_state_attributes.update(current_data)` — so the floor is a
state attribute of an entity the router already reads, and the router reads it
the way it reads everything else about a silence entity: by attribute, never by
domain.

Priorities rank `info < normal < high < critical`.
"""

from __future__ import annotations

from .conftest import explain, make_entry, make_person, make_target


def _entry(
    hass,
    *,
    min_priority: str = "info",
    silence_entities: list[str] | None = None,
    default_priority: str = "normal",
):
    return make_entry(
        hass,
        persons=[
            make_person(
                "person.alice",
                ["mobile_app_alice"],
                min_priority=min_priority,
                silence_entities=silence_entities,
            )
        ],
        targets=[
            make_target(
                "leak",
                "Leak",
                audience=["person.alice"],
                default_priority=default_priority,
            )
        ],
        default_target="leak",
    )


async def _send(hass, *, priority: str | None = None, message: str = "Leak!"):
    payload: dict = {"message": message}
    if priority is not None:
        payload["data"] = {"priority": priority}
    await hass.services.async_call("notify", "switchboard_leak", payload, blocking=True)
    await hass.async_block_till_done()


# ---------------------------------------------------------------------------
# (a) the per-person floor
# ---------------------------------------------------------------------------


async def test_a_call_below_the_persons_floor_is_dropped_with_below_min_priority(
    hass,
    enable_custom_integrations,
    install,
    mock_outputs,
    set_person,
    drop_reasons,
):
    """Alice only wants `high` and above; a `normal` message never reaches her."""
    calls = mock_outputs("mobile_app_alice")
    set_person("person.alice", "home")
    await install(_entry(hass, min_priority="high"))

    await _send(hass, priority="normal")

    assert len(calls["mobile_app_alice"]) == 0
    assert "below_min_priority" in drop_reasons(), (
        "`below_min_priority` joins the frozen drop reasons in v0.6 "
        "(contract v0.6, ADR-0020 §6)"
    )


async def test_a_call_at_or_above_the_floor_passes(
    hass, enable_custom_integrations, install, mock_outputs, set_person
):
    """The floor is a floor, not a filter: `high` and `critical` both get through."""
    calls = mock_outputs("mobile_app_alice")
    set_person("person.alice", "home")
    await install(_entry(hass, min_priority="high"))

    await _send(hass, priority="high", message="at the floor")
    await _send(hass, priority="critical", message="above it")

    assert [call.data["message"] for call in calls["mobile_app_alice"]] == [
        "at the floor",
        "above it",
    ]


async def test_the_floor_is_evaluated_before_silence_and_snooze(
    hass,
    enable_custom_integrations,
    install,
    mock_outputs,
    set_person,
    drop_reasons,
):
    """A standing rule outranks a temporary state as an explanation.

    Alice is behind a night silence *and* has a `high` floor. Telling her "you
    were silenced" about a message her floor would have dropped anyway sends
    her to the wrong switch (ADR-0020 §6).
    """
    mock_outputs("mobile_app_alice")
    set_person("person.alice", "home")
    hass.states.async_set("input_boolean.alice_night", "on")
    await install(
        _entry(
            hass,
            min_priority="high",
            silence_entities=["input_boolean.alice_night"],
        )
    )

    await _send(hass, priority="normal")

    reasons = drop_reasons()
    assert "below_min_priority" in reasons
    assert "silenced" not in reasons


async def test_the_default_floor_drops_nothing(
    hass, enable_custom_integrations, install, mock_outputs, set_person
):
    """`info` is the bottom of the rank, so an absent key changes nothing."""
    calls = mock_outputs("mobile_app_alice")
    set_person("person.alice", "home")
    await install(_entry(hass))

    await _send(hass, priority="info")

    assert len(calls["mobile_app_alice"]) == 1


async def test_critical_is_never_below_a_floor(
    hass, enable_custom_integrations, install, mock_outputs, set_person
):
    """The top of the rank cannot be under anything; no bypass rule is needed."""
    calls = mock_outputs("mobile_app_alice")
    set_person("person.alice", "home")
    await install(_entry(hass, min_priority="critical"))

    await _send(hass, priority="critical")

    assert len(calls["mobile_app_alice"]) == 1


async def test_explain_names_the_floor_in_its_detail(
    hass, enable_custom_integrations, install, mock_outputs, set_person
):
    """ "Why didn't I get it?" — "because you asked for `high` and above"."""
    mock_outputs("mobile_app_alice")
    set_person("person.alice", "home")
    await install(_entry(hass, min_priority="high"))

    answer = (await explain(hass, target="leak", priority="normal"))["persons"][
        "person.alice"
    ]

    assert answer["decision"] == "dropped"
    assert answer["reason"] == "below_min_priority"
    assert "high" in answer["detail"], (
        "`detail` names the floor that decided; the four priority values are "
        f"frozen strings and are not translated. Got {answer['detail']!r}"
    )


# ---------------------------------------------------------------------------
# (b) the scheduled floor, carried by a silence entity
# ---------------------------------------------------------------------------


async def test_a_schedule_block_floor_silences_only_the_calls_below_it(
    hass,
    enable_custom_integrations,
    install,
    mock_outputs,
    set_person,
    schedule_silence,
    drop_reasons,
):
    """A night that holds the shopping list and lets the leak through."""
    calls = mock_outputs("mobile_app_alice")
    set_person("person.alice", "home")
    night = await schedule_silence("night", {"min_priority": "high"})
    await install(_entry(hass, silence_entities=[night]))

    await _send(hass, priority="normal", message="the shopping list")
    assert len(calls["mobile_app_alice"]) == 0
    assert "silenced" in drop_reasons(), (
        "a call below the block's floor is dropped with the existing "
        "`silenced` reason; no new reason is introduced (ADR-0020 §6)"
    )

    await _send(hass, priority="high", message="the leak")
    assert [call.data["message"] for call in calls["mobile_app_alice"]] == ["the leak"]


async def test_a_silence_entity_without_the_attribute_still_silences_everything(
    hass,
    enable_custom_integrations,
    install,
    mock_outputs,
    set_person,
    schedule_silence,
    drop_reasons,
):
    """The half of the rule that must not change: a plain silence is a silence."""
    calls = mock_outputs("mobile_app_alice")
    set_person("person.alice", "home")
    night = await schedule_silence("night")
    await install(_entry(hass, silence_entities=[night]))

    await _send(hass, priority="high")

    assert len(calls["mobile_app_alice"]) == 0
    assert "silenced" in drop_reasons()


async def test_an_unreadable_floor_silences_everything(
    hass,
    enable_custom_integrations,
    install,
    mock_outputs,
    set_person,
    schedule_silence,
    drop_reasons,
):
    """A typo fails towards quiet, never towards noise.

    `CUSTOM_DATA_SCHEMA` accepts any string, so `min_priority: loud` reaches
    the state attributes intact. It is not one of the four priorities, so the
    entity behaves as an ordinary silence (ADR-0020 §6).
    """
    calls = mock_outputs("mobile_app_alice")
    set_person("person.alice", "home")
    night = await schedule_silence("night", {"min_priority": "loud"})
    await install(_entry(hass, silence_entities=[night]))

    await _send(hass, priority="high")

    assert len(calls["mobile_app_alice"]) == 0
    assert "silenced" in drop_reasons()


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


async def test_explain_names_the_schedule_entity_that_holds_the_floor(
    hass,
    enable_custom_integrations,
    install,
    mock_outputs,
    set_person,
    schedule_silence,
):
    """Naming the entity is what sends the user to the right switch."""
    mock_outputs("mobile_app_alice")
    set_person("person.alice", "home")
    night = await schedule_silence("night", {"min_priority": "high"})
    await install(_entry(hass, silence_entities=[night]))

    answer = (await explain(hass, target="leak", priority="normal"))["persons"][
        "person.alice"
    ]

    assert answer["reason"] == "silenced"
    assert night in answer["detail"]
    assert "high" in answer["detail"], (
        "the `detail` of a floored silence names the floor as well as the "
        f"entity, or the user cannot tell why `high` got through. Got "
        f"{answer['detail']!r}"
    )
