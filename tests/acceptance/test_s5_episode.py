"""Episodes and who was actually told (contract v0.5, ADR-0019 §5).

"Back to normal" is a strange thing to receive about a problem you never heard
of. Until 0.4.0 the `done` message went to the whole audience of the row,
including the people who were silenced, away or snoozed while the alert was
firing.

From 0.5.0 the router remembers, per **episode** — one run of the row's
`alert_entity`, from `idle → on` to `→ idle` — which persons actually received
at least one of its messages, and a `done` message reaches only them. Everyone
else in the audience is dropped with the new reason `not_notified`.

These tests drive a **real** `alert.*` (the `real_alert` fixture), because the
episode boundaries are that entity's own transitions and nothing else. Ending
the alert goes through `end_alerting`
(`$HA_CORE_SRC/homeassistant/components/alert/entity.py`), which cancels the
repeat timer — unlike `alert.turn_off`, which only sets `_ack` — so no test
here needs the `expected_lingering_timers` override `tests/conftest.py` grants
the three S1/S2 tests that acknowledge one.

Both ways of producing a `done` message are covered: observer mode's
`on|off → idle` transition, and the new documented `data.switchboard_done: true`
key a blueprint sets on a call it makes itself.
"""

from __future__ import annotations

from .conftest import make_entry, make_person, make_target


def _persons():
    """Alice hears everything; Bob is silenced with no wake time, so he is dropped."""
    return [
        make_person("person.alice", ["mobile_app_alice"]),
        make_person(
            "person.bob",
            ["mobile_app_bob"],
            silence_entities=["input_boolean.bob_night"],
        ),
    ]


def _entry(hass, *, observer_mode: bool, alert_entity: str | None = "alert.leak"):
    return make_entry(
        hass,
        persons=_persons(),
        targets=[
            make_target(
                "leak",
                "Leak",
                alert_entity=alert_entity,
                observer_mode=observer_mode,
                audience=["person.alice", "person.bob"],
                message="Leak!",
                done_message="All good",
            )
        ],
        default_target="leak",
    )


async def _arrange(hass, set_person, mock_outputs):
    calls = mock_outputs("mobile_app_alice", "mobile_app_bob")
    set_person("person.alice", "home")
    set_person("person.bob", "home")
    hass.states.async_set("input_boolean.bob_night", "on")
    await hass.async_block_till_done()
    return calls


async def test_the_done_message_reaches_only_the_persons_the_episode_reached(
    hass,
    enable_custom_integrations,
    install,
    mock_outputs,
    set_person,
    real_alert,
    drop_reasons,
):
    """Observer mode: Alice was told about the leak, Bob was not."""
    calls = await _arrange(hass, set_person, mock_outputs)
    alert = await real_alert("leak")
    await install(_entry(hass, observer_mode=True))

    await alert.begin()
    assert [call.data["message"] for call in calls["mobile_app_alice"]] == ["Leak!"]
    assert len(calls["mobile_app_bob"]) == 0

    await alert.end()

    assert [call.data["message"] for call in calls["mobile_app_alice"]] == [
        "Leak!",
        "All good",
    ]
    assert len(calls["mobile_app_bob"]) == 0, (
        "Bob never heard about the leak, so 'back to normal' means nothing to "
        "him (ADR-0019 §5)"
    )
    assert "not_notified" in drop_reasons(), (
        "nothing is silently lost: the person who does not get the done "
        "message is dropped with a reason of their own"
    )


async def test_the_episode_recipients_survive_a_reload(
    hass,
    hass_storage,
    enable_custom_integrations,
    install,
    mock_outputs,
    set_person,
    real_alert,
    drop_reasons,
):
    """A restart in the middle of a leak must not widen the done message.

    The config entry is unloaded and set up again on the same `hass_storage`
    while the alert is still firing — the same stand-in for a restart
    `test_s1_persistence.py` uses for snoozes.
    """
    calls = await _arrange(hass, set_person, mock_outputs)
    alert = await real_alert("leak")
    entry = await install(_entry(hass, observer_mode=True))

    await alert.begin()
    assert len(calls["mobile_app_alice"]) == 1

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    await alert.end()

    assert [call.data["message"] for call in calls["mobile_app_alice"]] == [
        "Leak!",
        "All good",
    ]
    assert len(calls["mobile_app_bob"]) == 0, (
        "the episode's recipients are persisted with the snoozes and the "
        "deferrals (ADR-0019 §5), so a reload does not forget who was told"
    )
    assert "not_notified" in drop_reasons()


async def test_switchboard_done_marks_a_done_message_on_a_non_observer_row(
    hass,
    enable_custom_integrations,
    install,
    mock_outputs,
    set_person,
    real_alert,
    drop_reasons,
):
    """The documented key a blueprint sets on the call it makes itself.

    The row is not in observer mode: its `alert:` block calls
    `notify.switchboard_leak` through its own `notifiers:` list, which is what
    the two service calls below stand in for.
    """
    calls = await _arrange(hass, set_person, mock_outputs)
    alert = await real_alert("leak")
    await install(_entry(hass, observer_mode=False))

    await alert.begin()
    await hass.services.async_call(
        "notify", "switchboard_leak", {"message": "Leak!"}, blocking=True
    )
    await hass.async_block_till_done()
    assert len(calls["mobile_app_alice"]) == 1
    assert len(calls["mobile_app_bob"]) == 0

    await alert.end()
    await hass.services.async_call(
        "notify",
        "switchboard_leak",
        {"message": "All good", "data": {"switchboard_done": True}},
        blocking=True,
    )
    await hass.async_block_till_done()

    assert [call.data["message"] for call in calls["mobile_app_alice"]] == [
        "Leak!",
        "All good",
    ]
    assert len(calls["mobile_app_bob"]) == 0
    assert "not_notified" in drop_reasons()


async def test_an_ordinary_message_is_not_filtered_by_the_episode(
    hass, enable_custom_integrations, install, mock_outputs, set_person, real_alert
):
    """Only a `done` message is filtered; the leak itself still tries everybody.

    Bob is dropped here too, but with `silenced` — the ordinary reason — not
    with `not_notified`. An implementation that filtered every message by the
    episode would make a row with an alert unreachable for anybody who missed
    its first message.
    """
    calls = await _arrange(hass, set_person, mock_outputs)
    alert = await real_alert("leak")
    await install(_entry(hass, observer_mode=False))

    await alert.begin()
    hass.states.async_set("input_boolean.bob_night", "off")
    await hass.async_block_till_done()

    await hass.services.async_call(
        "notify", "switchboard_leak", {"message": "still leaking"}, blocking=True
    )
    await hass.async_block_till_done()

    assert len(calls["mobile_app_alice"]) == 1
    assert len(calls["mobile_app_bob"]) == 1, (
        "Bob's silence lifted mid-episode; the next message of the episode "
        "reaches him like any other (ADR-0019 §5)"
    )

    await alert.end()


async def test_a_row_without_an_alert_entity_has_no_episodes(
    hass, enable_custom_integrations, install, mock_outputs, set_person, drop_reasons
):
    """No alert, no episode, no filter: a `done` message goes to the audience.

    Green against 0.4.0 on purpose. `not_notified` must be reachable only
    through a row that actually has episodes; otherwise the key would silence
    every household that never wrote an `alert:` block.
    """
    calls = await _arrange(hass, set_person, mock_outputs)
    hass.states.async_set("input_boolean.bob_night", "off")
    await hass.async_block_till_done()
    await install(_entry(hass, observer_mode=False, alert_entity=None))

    await hass.services.async_call(
        "notify",
        "switchboard_leak",
        {"message": "All good", "data": {"switchboard_done": True}},
        blocking=True,
    )
    await hass.async_block_till_done()

    assert len(calls["mobile_app_alice"]) == 1
    assert len(calls["mobile_app_bob"]) == 1
    assert "not_notified" not in drop_reasons()
