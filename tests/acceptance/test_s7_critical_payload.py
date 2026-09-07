"""The critical payload — a `critical` message that a phone actually plays.

Written before the Sprint 7 implementation exists, against:

- `docs/contract.md` §"v0.7 addendum (ADR-0021)" → "`critical_payload`" and
  "Breaking: `data.priority` no longer reaches a `mobile_app_*` output"
- `docs/ADR/0021-escalation-and-places-reduced.md` §7
- `docs/sprints/sprint-7-brief.md` item 7

The router has had four priorities since 0.1.0 and `critical` has meant exactly
one thing to a phone: nothing. It bypasses a silence *inside the router* and
then arrives as an ordinary push, which a phone in Do Not Disturb does not
play. The keys that change that are the Companion documentation's
(<https://companion.home-assistant.io/docs/notifications/critical-notifications/>):
on iOS `push.sound: {name: default, critical: 1, volume: 1.0}`, on Android
`ttl: 0`, `priority: high` and `channel: alarm_stream`.

The OS is read from the registration — the `os_name` of the `mobile_app` config
entry whose device name produces that output's service name
(`$HA_CORE_SRC/homeassistant/components/mobile_app/const.py`, `ATTR_OS_NAME`) —
and an OS the router cannot identify gets **both** sets, because the keys of
one are inert on the other and a phone that rings is better than a phone that
is quiet because a registration predates a field.

And the defect that comes with all this: `data.priority` is the router's own
input key, and the router has been forwarding it to Companion outputs since
v0, where Android reads `data.priority` and understands exactly one value,
`high`. From 0.7.0 it is stripped — always, whatever the priority and whatever
the option says — and the router writes `priority: high` itself when the
message really is critical.
"""

from __future__ import annotations

from .conftest import make_entry, make_mobile_app_entry, make_person, make_target

IOS_PUSH = {"sound": {"name": "default", "critical": 1, "volume": 1.0}}
ANDROID_KEYS = {"ttl": 0, "priority": "high", "channel": "alarm_stream"}

PHONE = "mobile_app_phone_one"


def _entry(
    hass,
    *,
    os_name: str = "iOS",
    critical_payload: bool | None = None,
    default_priority: str = "normal",
    escalate: bool = False,
    outputs: list[str] | None = None,
):
    """One person, one Companion registration whose OS the test chooses."""
    make_mobile_app_entry(
        hass, device_name="Phone One", user_id="user-alice", os_name=os_name
    )
    return make_entry(
        hass,
        persons=[make_person("person.alice", outputs or [PHONE])],
        targets=[
            make_target(
                "leak",
                "Leak",
                audience=["person.alice"],
                default_priority=default_priority,
                escalate_when_nobody_home=escalate,
            )
        ],
        default_target="leak",
        critical_payload=critical_payload,
    )


async def _send(hass, **data):
    payload: dict = {"message": "Leak!"}
    if data:
        payload["data"] = data
    await hass.services.async_call("notify", "switchboard_leak", payload, blocking=True)
    await hass.async_block_till_done()


def _sent(calls, name: str = PHONE) -> dict:
    assert len(calls[name]) == 1, f"expected exactly one call to {name}"
    return calls[name][0].data.get("data", {})


async def test_an_ios_registration_gets_the_push_sound_keys(
    hass, enable_custom_integrations, install, mock_outputs, set_person
):
    """The keys that make an iPhone ring through Do Not Disturb."""
    calls = mock_outputs(PHONE)
    set_person("person.alice", "home")
    await install(_entry(hass, os_name="iOS"))

    await _send(hass, priority="critical")

    data = _sent(calls)
    assert data.get("push") == IOS_PUSH, (
        "a critical message on an iOS registration carries "
        "`push.sound: {name: default, critical: 1, volume: 1.0}` "
        "(contract v0.7, ADR-0021 §7)"
    )
    assert "channel" not in data, "the Android keys are not sent to a known iPhone"
    assert "ttl" not in data


async def test_an_android_registration_gets_ttl_priority_and_the_alarm_channel(
    hass, enable_custom_integrations, install, mock_outputs, set_person
):
    """The keys that make an Android device ring on a silent ringer."""
    calls = mock_outputs(PHONE)
    set_person("person.alice", "home")
    await install(_entry(hass, os_name="Android"))

    await _send(hass, priority="critical")

    data = _sent(calls)
    for key, value in ANDROID_KEYS.items():
        assert data.get(key) == value, (
            f"a critical message on an Android registration carries {key}: "
            f"{value!r} (contract v0.7, ADR-0021 §7)"
        )
    assert "push" not in data, "the iOS keys are not sent to a known Android device"


async def test_an_unknown_os_gets_both_sets(
    hass, enable_custom_integrations, install, mock_outputs, set_person
):
    """Both is right rather than neither: the keys of one OS are inert on the other."""
    calls = mock_outputs(PHONE)
    set_person("person.alice", "home")
    await install(_entry(hass, os_name="SailfishOS"))

    await _send(hass, priority="critical")

    data = _sent(calls)
    assert data.get("push") == IOS_PUSH
    for key, value in ANDROID_KEYS.items():
        assert data.get(key) == value


async def test_a_caller_key_wins_and_push_counts_as_one_key(
    hass, enable_custom_integrations, install, mock_outputs, set_person
):
    """The escape hatch the Companion page documents is one key: `push`.

    A household that prefers `push: {interruption-level: critical}` to the
    sound form writes it, and the router adds nothing under `push` at all —
    merging into a nested mapping the caller wrote is where a rule like this
    stops being predictable (ADR-0021 §7).
    """
    calls = mock_outputs(PHONE)
    set_person("person.alice", "home")
    await install(_entry(hass, os_name="SailfishOS"))

    await _send(
        hass,
        priority="critical",
        channel="my_alerts",
        push={"interruption-level": "critical"},
    )

    data = _sent(calls)
    assert data["push"] == {"interruption-level": "critical"}, (
        "`push` counts as a single caller key: nothing is added under it"
    )
    assert data["channel"] == "my_alerts", "a caller-set key is never overwritten"
    assert data["ttl"] == 0, "the keys the caller did not write are still added"
    assert data["priority"] == "high"


async def test_the_option_off_adds_nothing_and_still_strips_priority(
    hass, enable_custom_integrations, install, mock_outputs, set_person
):
    """`critical_payload: false` turns off the addition, never the removal."""
    calls = mock_outputs(PHONE)
    set_person("person.alice", "home")
    await install(_entry(hass, os_name="Android", critical_payload=False))

    await _send(hass, priority="critical")

    data = _sent(calls)
    assert "push" not in data
    assert "channel" not in data
    assert "ttl" not in data
    assert "priority" not in data, (
        "the strip happens whatever the priority is and whatever the option "
        "says; turning the option off does not put the key back "
        "(contract v0.7, §Breaking)"
    )


async def test_priority_never_reaches_a_companion_output(
    hass, enable_custom_integrations, install, mock_outputs, set_person
):
    """The breaking change, on an ordinary message: `data.priority` is the router's."""
    calls = mock_outputs(PHONE)
    set_person("person.alice", "home")
    await install(_entry(hass))

    await _send(hass, priority="high")

    data = _sent(calls)
    assert "priority" not in data, (
        "`data.priority` selects the effective priority and has never been a "
        "Companion key; Android reads it and knows only `high` "
        "(contract v0.7, §Breaking)"
    )


async def test_priority_still_reaches_every_other_output(
    hass, enable_custom_integrations, install, mock_outputs, set_person
):
    """The strip is scoped to Companion outputs; elsewhere the router is a proxy."""
    calls = mock_outputs(PHONE, "kitchen_speaker")
    set_person("person.alice", "home")
    await install(_entry(hass, outputs=[PHONE, "kitchen_speaker"]))

    await _send(hass, priority="high")

    assert _sent(calls, "kitchen_speaker").get("priority") == "high", (
        "`priority` is the caller's own key and reaches every output that is "
        "not a `mobile_app_*` one, exactly as before"
    )


async def test_a_non_critical_message_gets_no_critical_payload(
    hass, enable_custom_integrations, install, mock_outputs, set_person
):
    """The line an over-eager implementation crosses first."""
    calls = mock_outputs(PHONE)
    set_person("person.alice", "home")
    await install(_entry(hass, os_name="Android"))

    await _send(hass, priority="normal")

    data = _sent(calls)
    assert "push" not in data
    assert "channel" not in data
    assert "ttl" not in data


async def test_an_escalated_message_carries_the_critical_payload(
    hass, enable_custom_integrations, install, mock_outputs, set_person
):
    """ "Effective" means after the escalation: it is the message that was sent."""
    calls = mock_outputs(PHONE)
    set_person("person.alice", "not_home")
    await install(_entry(hass, os_name="iOS", default_priority="high", escalate=True))

    await _send(hass)

    data = _sent(calls)
    assert data.get("push") == IOS_PUSH, (
        "a `high` message raised to `critical` by an empty house is a critical "
        "message in every respect (ADR-0021 §1 and §7)"
    )
