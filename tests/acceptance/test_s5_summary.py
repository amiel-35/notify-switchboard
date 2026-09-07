"""One summary at the wake time (contract v0.5, ADR-0019 §2).

Eleven deferred messages used to be eleven notifications in a burst at 07:00.
From 0.5.0 a person whose `summary` option is on (the default) gets **one**
notification per output listing what happened, with messages sharing a `tag`
collapsed to the last one, and with none of the per-message payload that
cannot be merged — in particular no Companion buttons.

Nothing here asserts French or English words. The title is checked for the
count it must carry and for the fact that `common.summary_title` exists in
every shipped language; the lines are checked for the messages they must
contain and for their order. Choosing the wording is the coding agent's job
(same discipline as `test_s3_entities.py`).
"""

from __future__ import annotations

from datetime import datetime, timedelta

import homeassistant.util.dt as dt_util
import pytest
from homeassistant.helpers import translation
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.notify_switchboard.const import DOMAIN

from .conftest import make_entry, make_person, make_target

NIGHT = datetime(2026, 9, 10, 21, 30, tzinfo=dt_util.UTC)  # 23:30 Europe/Paris
MORNING = datetime(2026, 9, 11, 5, 5, tzinfo=dt_util.UTC)  # 07:05 Europe/Paris

SUMMARY_TITLE_KEY = f"component.{DOMAIN}.common.summary_title"


def _entry(hass, *, summary: bool = True):
    """Three rows, one silenced person with a 07:00 wake time.

    Row `b` carries an acknowledge button and a snooze button, so a message
    delivered on its own would carry `actions`: that is what makes the
    "no Companion buttons on a summary" assertion mean something.
    """
    return make_entry(
        hass,
        persons=[
            make_person(
                "person.alice",
                ["mobile_app_alice"],
                silence_entities=["input_boolean.alice_night"],
                wake_time="07:00:00",
                summary=summary,
            )
        ],
        targets=[
            make_target("a", "Row A", audience=["person.alice"]),
            make_target(
                "b",
                "Row B",
                audience=["person.alice"],
                alert_entity="alert.row_b",
                allow_acknowledge=True,
                snooze_minutes=[15],
            ),
            make_target("c", "Row C", audience=["person.alice"]),
        ],
        default_target="a",
    )


async def _queue_three(hass, freezer) -> None:
    """Queue three messages: two sharing the tag `x`, one untagged."""
    await hass.services.async_call(
        "notify",
        "switchboard_a",
        {"message": "first", "title": "Door", "data": {"tag": "x"}},
        blocking=True,
    )
    await hass.async_block_till_done()

    freezer.tick(timedelta(minutes=1))
    await hass.services.async_call(
        "notify",
        "switchboard_b",
        {"message": "second", "title": "Leak", "data": {"tag": "x"}},
        blocking=True,
    )
    await hass.async_block_till_done()

    freezer.tick(timedelta(minutes=1))
    await hass.services.async_call(
        "notify",
        "switchboard_c",
        {"message": "third", "title": "Pets"},
        blocking=True,
    )
    await hass.async_block_till_done()


async def _wake(hass, freezer) -> None:
    freezer.move_to(MORNING)
    hass.states.async_set("input_boolean.alice_night", "off")
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done()


async def test_three_deferrals_two_sharing_a_tag_become_one_two_line_summary(
    hass, enable_custom_integrations, install, mock_outputs, set_person, freezer
):
    """One notification, two lines, the collapsed pair represented by its last."""
    await hass.config.async_set_time_zone("Europe/Paris")
    calls = mock_outputs("mobile_app_alice")
    set_person("person.alice", "home")
    hass.states.async_set("input_boolean.alice_night", "on")

    freezer.move_to(NIGHT)
    await install(_entry(hass))
    await _queue_three(hass, freezer)
    assert len(calls["mobile_app_alice"]) == 0

    await _wake(hass, freezer)

    assert len(calls["mobile_app_alice"]) == 1, (
        "a person with `summary` on gets one notification per output at the "
        "wake time, not one per deferred message (ADR-0019 §2)"
    )
    payload = calls["mobile_app_alice"][0].data
    lines = payload["message"].splitlines()

    assert len(lines) == 2, (
        "the two messages tagged `x` collapse to one line; the untagged one "
        f"keeps its own. Got: {payload['message']!r}"
    )
    assert "second" in lines[0] and "Leak" in lines[0], (
        "a collapsed group is represented by its **last** message, title first"
    )
    assert "third" in lines[1] and "Pets" in lines[1], "newest last"
    assert "first" not in payload["message"], (
        "the earlier message of a collapsed tag is not listed"
    )


async def test_the_summary_title_carries_the_number_of_lines(
    hass, enable_custom_integrations, install, mock_outputs, set_person, freezer
):
    """`{count}` is what the reader can count in the body, not what was queued."""
    await hass.config.async_set_time_zone("Europe/Paris")
    calls = mock_outputs("mobile_app_alice")
    set_person("person.alice", "home")
    hass.states.async_set("input_boolean.alice_night", "on")

    freezer.move_to(NIGHT)
    await install(_entry(hass))
    await _queue_three(hass, freezer)
    await _wake(hass, freezer)

    title = calls["mobile_app_alice"][0].data.get("title")
    assert title, "a summary always carries a title (ADR-0019 §2)"
    assert "2" in title, (
        "three messages were queued but two of them share a tag, so the "
        f"summary lists two and must say two. Got: {title!r}"
    )
    assert "3" not in title


@pytest.mark.parametrize("language", ["en", "fr", "es"])
async def test_the_summary_title_is_translated_and_takes_a_count_placeholder(
    hass, enable_custom_integrations, install, language
):
    """`common.summary_title` ships in every language, with one `{count}`."""
    hass.config.language = language
    await install(_entry(hass))

    strings = await translation.async_get_translations(
        hass, language, "common", {DOMAIN}
    )

    assert SUMMARY_TITLE_KEY in strings, (
        f"translations/{language}.json must define {SUMMARY_TITLE_KEY} "
        "(ADR-0019 §2); the wording is the coding agent's choice"
    )
    assert "{count}" in strings[SUMMARY_TITLE_KEY], (
        "the summary title carries the number of lines as `{count}`"
    )


async def test_a_summary_carries_only_the_switchboards_own_data_keys(
    hass, enable_custom_integrations, install, mock_outputs, set_person, freezer
):
    """No caller key, no row default, and above all no Companion buttons.

    Row `b`'s message would carry an Acknowledge and a Snooze action if it were
    delivered on its own; a digest of three unrelated messages must not, since
    the button would act on an arbitrary one of them.
    """
    await hass.config.async_set_time_zone("Europe/Paris")
    calls = mock_outputs("mobile_app_alice")
    set_person("person.alice", "home")
    hass.states.async_set("input_boolean.alice_night", "on")

    freezer.move_to(NIGHT)
    await install(_entry(hass))
    await _queue_three(hass, freezer)
    await _wake(hass, freezer)

    data = calls["mobile_app_alice"][0].data.get("data", {})
    assert data == {"tag": "switchboard-summary"}, (
        "a summary's `data` is built, not merged: only the switchboard's own "
        f"keys survive (ADR-0019 §2). Got: {data!r}"
    )


async def test_summary_off_delivers_every_message_one_by_one(
    hass, enable_custom_integrations, install, mock_outputs, set_person, freezer
):
    """`summary: false` keeps the 0.4.0 behaviour, message by message.

    Three deferrals, three notifications: the tag collapse is part of building
    a digest, so it does not apply when there is no digest to build.

    Green against 0.4.0 on purpose: this is the negative half of the rule, and
    a summary that cannot be turned off is worse than no summary.
    """
    await hass.config.async_set_time_zone("Europe/Paris")
    calls = mock_outputs("mobile_app_alice")
    set_person("person.alice", "home")
    hass.states.async_set("input_boolean.alice_night", "on")

    freezer.move_to(NIGHT)
    await install(_entry(hass, summary=False))
    await _queue_three(hass, freezer)
    await _wake(hass, freezer)

    messages = sorted(call.data["message"] for call in calls["mobile_app_alice"])
    assert messages == ["first", "second", "third"], (
        "with `summary` off every surviving deferral is delivered on its own, "
        "cross-row tag or not (ADR-0019 §2)"
    )


async def test_a_single_survivor_is_delivered_plainly_not_summarised(
    hass, enable_custom_integrations, install, mock_outputs, set_person, freezer
):
    """One message is not a digest: text, title and buttons are its own."""
    await hass.config.async_set_time_zone("Europe/Paris")
    calls = mock_outputs("mobile_app_alice")
    set_person("person.alice", "home")
    hass.states.async_set("input_boolean.alice_night", "on")

    freezer.move_to(NIGHT)
    await install(_entry(hass))

    await hass.services.async_call(
        "notify",
        "switchboard_b",
        {"message": "the only one", "title": "Leak"},
        blocking=True,
    )
    await hass.async_block_till_done()

    await _wake(hass, freezer)

    assert len(calls["mobile_app_alice"]) == 1
    payload = calls["mobile_app_alice"][0].data
    assert payload["message"] == "the only one"
    assert payload["title"] == "Leak"

    data = payload.get("data", {})
    assert data.get("tag") == "switchboard-b", (
        "an untagged message gets the row's default tag (ADR-0019 §6), not "
        "the summary tag"
    )
    actions = {action["action"] for action in data.get("actions", [])}
    assert actions == {"switchboard:ack:b", "switchboard:snooze:b:15"}, (
        "a single survivor keeps its own Companion buttons"
    )
