"""Router-added `data` keys reach only the outputs that understand them.

ADR-0019 §6, amendment 2026-09-07 (2). The router is a pure proxy (ADR-0002):
the caller's `data`, merged under the row's `default_data`, is what an output
receives. The three keys the router adds for itself are scoped to the output
that documents them:

- `tag`, `actions`, `authenticationRequired` -> `mobile_app_*` outputs
  (`tag` also travels to `persistent_notification`, where it is the source of
  the `notification_id`);
- `notification_id` -> the bare `persistent_notification` output.

Any other output -- a Telegram bot, a speaker adapter, an e-mail notifier --
gets the caller's keys and nothing else. Sibling adapters refuse unknown
`data` keys by design (AirPlay Notifier validates its `data` with voluptuous'
default `PREVENT_EXTRA`; Assist Satellite Notifier checks an explicit
`ALLOWED_DATA_KEYS`), so a router key landing on one of them is not noise: it
is a `ServiceValidationError` on every single call.

A caller-supplied `data.tag` is the caller's own key, not a router one, and
still reaches every output.
"""

from __future__ import annotations

from datetime import datetime

import homeassistant.util.dt as dt_util
from pytest_homeassistant_custom_component.common import (
    async_fire_time_changed,
    async_mock_service,
)

from .conftest import make_entry, make_person, make_target

SPEAKER = "speaker_y"
PHONE = "mobile_app_x"
UI = "persistent_notification"

NIGHT = datetime(2026, 9, 10, 21, 30, tzinfo=dt_util.UTC)  # 23:30 Europe/Paris
MORNING = datetime(2026, 9, 11, 5, 5, tzinfo=dt_util.UTC)  # 07:05 Europe/Paris


def _entry(hass):
    """One person, three outputs, one row with buttons and a `default_data`."""
    return make_entry(
        hass,
        persons=[make_person("person.alice", [PHONE, UI, SPEAKER])],
        targets=[
            make_target(
                "leak",
                "Leak",
                audience=["person.alice"],
                allow_acknowledge=True,
                snooze_minutes=[15],
                default_data={"channel": "family"},
            )
        ],
        default_target="leak",
    )


def _mock_ui(hass) -> list:
    """Mock `notify.persistent_notification` *after* the entry is up.

    `notify`'s own setup registers the real service (core
    `components/notify/__init__.py`, `async_setup`) and replaces a mock made
    earlier (`core.py`, `ServiceRegistry._async_register`).
    """
    return async_mock_service(hass, "notify", UI)


async def test_router_keys_reach_only_the_outputs_that_understand_them(
    hass, enable_custom_integrations, install, mock_outputs, set_person
):
    """One message, three outputs, three different `data` payloads."""
    calls = mock_outputs(PHONE, SPEAKER)
    set_person("person.alice", "home")

    await install(_entry(hass))
    calls[UI] = _mock_ui(hass)

    await hass.services.async_call(
        "notify",
        "switchboard_leak",
        {"message": "m", "data": {"volume": 0.5}},
        blocking=True,
    )
    await hass.async_block_till_done()

    phone = calls[PHONE][0].data["data"]
    assert phone["tag"] == "switchboard-leak", (
        "the Companion output is the one that reads `data.tag` (ADR-0019 §6)"
    )
    assert {action["action"] for action in phone["actions"]} == {
        "switchboard:ack:leak",
        "switchboard:snooze:leak:15",
    }

    ui = calls[UI][0].data["data"]
    assert ui["notification_id"] == "switchboard-leak"
    assert ui["tag"] == "switchboard-leak"
    assert "actions" not in ui

    speaker = calls[SPEAKER][0].data.get("data", {})
    assert speaker == {"channel": "family", "volume": 0.5}, (
        "an output that is neither Companion nor `persistent_notification` "
        "receives the caller's `data` merged with the row's `default_data` and "
        "nothing the router added (ADR-0019 §6, amendment 2026-09-07 (2)). "
        f"Got: {speaker!r}"
    )


async def test_a_caller_supplied_tag_still_reaches_every_output(
    hass, enable_custom_integrations, install, mock_outputs, set_person
):
    """`data.tag` from the caller is the caller's key: it is proxied, not scoped."""
    calls = mock_outputs(PHONE, SPEAKER)
    set_person("person.alice", "home")

    await install(_entry(hass))
    calls[UI] = _mock_ui(hass)

    await hass.services.async_call(
        "notify",
        "switchboard_leak",
        {"message": "m", "data": {"tag": "mine"}},
        blocking=True,
    )
    await hass.async_block_till_done()

    assert calls[PHONE][0].data["data"]["tag"] == "mine"
    assert calls[UI][0].data["data"]["tag"] == "mine"
    assert calls[UI][0].data["data"]["notification_id"] == "mine"
    assert calls[SPEAKER][0].data["data"]["tag"] == "mine", (
        "the router never removes a key the caller wrote; only the keys it "
        "adds itself are scoped to the outputs that understand them"
    )


async def test_the_summary_tag_is_scoped_the_same_way(
    hass, enable_custom_integrations, install, mock_outputs, set_person, freezer
):
    """A wake-time digest is a router-built payload: its tag is scoped too.

    `switchboard-summary` is a name the router chose for a message it composed
    itself (ADR-0019 §2), so it belongs on the outputs that read a `tag` and
    nowhere else. A digest's `data` holds nothing but the switchboard's own
    keys, so a plain output receives no `data` at all.
    """
    await hass.config.async_set_time_zone("Europe/Paris")
    calls = mock_outputs(PHONE, SPEAKER)
    set_person("person.alice", "home")
    hass.states.async_set("input_boolean.alice_night", "on")

    entry = make_entry(
        hass,
        persons=[
            make_person(
                "person.alice",
                [PHONE, SPEAKER],
                silence_entities=["input_boolean.alice_night"],
                wake_time="07:00:00",
            )
        ],
        targets=[
            make_target("a", "Row A", audience=["person.alice"]),
            make_target("b", "Row B", audience=["person.alice"]),
        ],
        default_target="a",
    )
    freezer.move_to(NIGHT)
    await install(entry)

    for slug in ("a", "b"):
        await hass.services.async_call(
            "notify", f"switchboard_{slug}", {"message": slug}, blocking=True
        )
        await hass.async_block_till_done()

    freezer.move_to(MORNING)
    hass.states.async_set("input_boolean.alice_night", "off")
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done()

    assert len(calls[PHONE]) == 1
    assert calls[PHONE][0].data["data"]["tag"] == "switchboard-summary"

    assert len(calls[SPEAKER]) == 1
    assert calls[SPEAKER][0].data.get("data", {}) == {}, (
        "the summary tag is the router's own name for the digest, so it stops "
        "at the outputs that read a tag (ADR-0019 §6, amendment "
        "2026-09-07 (2))"
    )
