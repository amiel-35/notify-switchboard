"""Closing the loop on phones and in the UI (contract v0.5, ADR-0019 §6).

A leak that was fixed at 03:20 leaves its 03:00 notification on every phone
for ever, because nothing ever told the device it was stale — and the router
could not have told it anyway, since it knew neither which devices had it nor
under what name.

0.5.0 gives every message a deterministic identity (`data.tag`
`switchboard-<slug>`, `data.notification_id` mirroring it on the
`persistent_notification` output) and, when the episode ends, clears what it
sent: `message: clear_notification` to each `mobile_app_*` output that
received the episode, and `persistent_notification.dismiss` for the matching
id.

Core APIs this pins:

- `$HA_CORE_SRC/homeassistant/components/mobile_app/const.py`,
  `CLEAR_NOTIFICATION = "clear_notification"` — the literal the Companion app
  reads as "remove the notification with this tag". Core forwards the payload
  to the push relay untouched; the only place it reads the literal itself is
  `mobile_app/live_activity/__init__.py`
  (`if data.get(ATTR_MESSAGE) == CLEAR_NOTIFICATION`), which ends the Live
  Activity for the same tag. So the router sends it as an ordinary
  `notify.mobile_app_<device>` call, which is what these tests capture.
- `$HA_CORE_SRC/homeassistant/components/notify/__init__.py`, the
  `notify.persistent_notification` service handler, which reads
  `data[pn.ATTR_NOTIFICATION_ID]` and hands it to `pn.async_create` — the
  reason a persistent notification can be replaced and dismissed by name.
- `$HA_CORE_SRC/homeassistant/components/persistent_notification/__init__.py`,
  `ATTR_NOTIFICATION_ID`, `SCHEMA_SERVICE_NOTIFICATION` and the `dismiss`
  service, which is what the router calls to close the UI half.
"""

from __future__ import annotations

from .conftest import make_entry, make_person, make_target

CLEAR = "clear_notification"


def _entry(hass, *, clear_done: bool = False, outputs=None):
    return make_entry(
        hass,
        persons=[
            make_person(
                "person.alice", outputs or ["mobile_app_alice", "persistent_notification"]
            )
        ],
        targets=[
            make_target(
                "leak",
                "Leak",
                alert_entity="alert.leak",
                observer_mode=True,
                audience=["person.alice"],
                message="Leak!",
                done_message="All good",
                clear_done=clear_done,
            )
        ],
        default_target="leak",
    )


def _messages(calls) -> list[str]:
    return [call.data["message"] for call in calls]


async def test_a_message_carries_the_default_tag_and_notification_id(
    hass, enable_custom_integrations, install, mock_outputs, set_person
):
    """`switchboard-<slug>` on both, so a repeat updates instead of stacking.

    The id is added for the `persistent_notification` output only: every other
    output would get a key it has no use for.
    """
    calls = mock_outputs("mobile_app_alice", "persistent_notification")
    set_person("person.alice", "home")
    await install(_entry(hass))

    await hass.services.async_call(
        "notify", "switchboard_leak", {"message": "Leak!"}, blocking=True
    )
    await hass.async_block_till_done()

    phone = calls["mobile_app_alice"][0].data["data"]
    assert phone["tag"] == "switchboard-leak", (
        "a caller that supplies no tag still gets a deterministic one "
        "(ADR-0019 §6)"
    )
    assert "notification_id" not in phone

    ui = calls["persistent_notification"][0].data["data"]
    assert ui["tag"] == "switchboard-leak"
    assert ui["notification_id"] == "switchboard-leak", (
        "the legacy `notify.persistent_notification` service reads "
        "`data.notification_id` (core `components/notify/__init__.py`), which "
        "is what makes the notification replaceable and dismissable"
    )


async def test_a_caller_supplied_tag_and_notification_id_win(
    hass, enable_custom_integrations, install, mock_outputs, set_person
):
    """The default only fills a gap; it never overrides a caller."""
    calls = mock_outputs("mobile_app_alice", "persistent_notification")
    set_person("person.alice", "home")
    await install(_entry(hass))

    await hass.services.async_call(
        "notify",
        "switchboard_leak",
        {"message": "Leak!", "data": {"tag": "mine", "notification_id": "also-mine"}},
        blocking=True,
    )
    await hass.async_block_till_done()

    assert calls["mobile_app_alice"][0].data["data"]["tag"] == "mine"
    ui = calls["persistent_notification"][0].data["data"]
    assert ui["tag"] == "mine"
    assert ui["notification_id"] == "also-mine"


async def test_ending_an_episode_clears_the_phone_and_dismisses_the_ui(
    hass, enable_custom_integrations, install, mock_outputs, set_person, real_alert,
    dismissals,
):
    """The whole point: nothing stale is left behind on either channel."""
    calls = mock_outputs("mobile_app_alice", "persistent_notification")
    set_person("person.alice", "home")
    alert = await real_alert("leak")
    await install(_entry(hass))

    await alert.begin()
    assert _messages(calls["mobile_app_alice"]) == ["Leak!"]

    await alert.end()

    assert _messages(calls["mobile_app_alice"]) == ["Leak!", "All good", CLEAR], (
        "the done message first, then the clear (ADR-0019 §6)"
    )
    clear = calls["mobile_app_alice"][-1].data["data"]
    assert clear == {"tag": "switchboard-leak"}, (
        "the clear names the episode's tag and carries nothing else"
    )

    assert len(dismissals) == 1
    assert dismissals[0].data["notification_id"] == "switchboard-leak"


async def test_the_done_message_has_a_tag_of_its_own_and_is_kept_by_default(
    hass, enable_custom_integrations, install, mock_outputs, set_person, real_alert
):
    """`clear_done` is off by default, so "back to normal" must survive the clear.

    That is only possible because the done message does not share the
    episode's tag: clearing `switchboard-leak` would otherwise take it with it.
    """
    calls = mock_outputs("mobile_app_alice", "persistent_notification")
    set_person("person.alice", "home")
    alert = await real_alert("leak")
    await install(_entry(hass))

    await alert.begin()
    await alert.end()

    done = next(
        call for call in calls["mobile_app_alice"] if call.data["message"] == "All good"
    )
    assert done.data["data"]["tag"] == "switchboard-leak-done", (
        "the done message's default tag is the row's, suffixed `-done` "
        "(ADR-0019 §6)"
    )
    cleared_tags = [
        call.data["data"]["tag"]
        for call in calls["mobile_app_alice"]
        if call.data["message"] == CLEAR
    ]
    assert cleared_tags == ["switchboard-leak"], (
        "with `clear_done` off, the done message is not cleared"
    )


async def test_clear_done_also_clears_the_done_message(
    hass, enable_custom_integrations, install, mock_outputs, set_person, real_alert
):
    """With the row option on, "back to normal" rings and then tidies itself away."""
    calls = mock_outputs("mobile_app_alice", "persistent_notification")
    set_person("person.alice", "home")
    alert = await real_alert("leak")
    await install(_entry(hass, clear_done=True))

    await alert.begin()
    await alert.end()

    assert _messages(calls["mobile_app_alice"]) == [
        "Leak!",
        "All good",
        CLEAR,
        CLEAR,
    ]
    cleared_tags = [
        call.data["data"]["tag"]
        for call in calls["mobile_app_alice"]
        if call.data["message"] == CLEAR
    ]
    assert cleared_tags == ["switchboard-leak", "switchboard-leak-done"]


async def test_a_clear_is_not_a_message(
    hass, enable_custom_integrations, install, mock_outputs, set_person, real_alert,
    routed_sensor, dropped_sensor,
):
    """Housekeeping on a channel is not a notification: it is not counted.

    Two real messages go out during this episode — the alert and the done —
    and `sensor.switchboard_routed_today` must say two, not three or four.
    """
    calls = mock_outputs("mobile_app_alice", "persistent_notification")
    set_person("person.alice", "home")
    alert = await real_alert("leak")
    await install(_entry(hass, clear_done=True))

    await alert.begin()
    await alert.end()

    assert routed_sensor().state == "2", (
        "a clear is not routed (ADR-0019 §6); only 'Leak!' and 'All good' are"
    )
    assert dropped_sensor().state == "0"
    assert len([c for c in calls["mobile_app_alice"] if c.data["message"] == CLEAR]) == 2


async def test_nothing_is_cleared_on_an_output_the_episode_never_reached(
    hass, enable_custom_integrations, install, mock_outputs, set_person, real_alert,
    dismissals,
):
    """The clear follows the episode's own record, not the current configuration.

    Alice has no `persistent_notification` output here, so the UI half of the
    loop has nothing to close and `persistent_notification.dismiss` must not
    be called at all.
    """
    calls = mock_outputs("mobile_app_alice")
    set_person("person.alice", "home")
    alert = await real_alert("leak")
    await install(_entry(hass, outputs=["mobile_app_alice"]))

    await alert.begin()
    await alert.end()

    assert _messages(calls["mobile_app_alice"]) == ["Leak!", "All good", CLEAR]
    assert dismissals == []
