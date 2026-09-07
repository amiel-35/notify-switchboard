"""Parallel fan-out with a per-output timeout (contract v0.3, ADR-0017 §3).

Written before the Sprint 3 implementation exists, against:

- `docs/contract.md` §"v0.3 addendum (ADR-0017)" → "Fan-out guarantees"
- `docs/ADR/0017-debts-and-robustness.md` §3
- `docs/sprints/sprint-3-brief.md` item 3

Two promises, and one explicit non-promise:

1. every (person, output) delivery of one routing decision is attempted
   concurrently, so the wall time of a decision is bounded by its slowest
   single output rather than by their sum;
2. that single output is itself bounded, by
   `dispatcher.OUTPUT_TIMEOUT_SECONDS` (30 s in production, patched to a
   fraction of a second here — the tests must not wait 30 s to prove a
   timeout, and the constant is the thing the ADR fixes, so patching it is
   patching the specification, not an internal);
3. the *order* of the resulting `event.switchboard_delivery` events is not
   promised. Nothing below asserts one.

A timed-out or failing output is accounted for exactly as it already was in
0.2.0 — same drop reason, same counter, same event payload — which is what
`test_every_output_timing_out_is_the_existing_delivery_failed_drop` pins.

Timings: every sleep below is measured against a patched timeout, and the
margins are wide enough (a factor of two or more) that a slow CI machine
fails the *sequential* implementation without failing the parallel one.
"""

from __future__ import annotations

import asyncio
import time
from unittest.mock import patch

import pytest
from homeassistant.core import ServiceCall

from .conftest import make_entry, make_person, make_target

# The name the implementation must give the per-output timeout
# (ADR-0017 §3). Patched, not read: the tests pin the behaviour it produces.
TIMEOUT_CONSTANT = (
    "custom_components.notify_switchboard.dispatcher.OUTPUT_TIMEOUT_SECONDS"
)

# Long enough that an output stuck on it is unmistakably a hang, short enough
# that a test which waits for it by mistake fails fast.
HANG_SECONDS = 5.0


def _slow_outputs(
    hass, *names: str, delay: float, calls: dict[str, list[ServiceCall]] | None = None
) -> dict[str, list[ServiceCall]]:
    """Register `notify.<name>` services that each take `delay` seconds.

    Returns the same {name: captured calls} mapping as the `mock_outputs`
    fixture, so the assertions read the same way; `async_mock_service` cannot
    be used here because it answers instantly and the point is the timing.
    """
    captured: dict[str, list[ServiceCall]] = calls if calls is not None else {}
    for name in names:
        captured.setdefault(name, [])

        async def _handler(call: ServiceCall, _name: str = name) -> None:
            await asyncio.sleep(delay)
            captured[_name].append(call)

        hass.services.async_register("notify", name, _handler)
    return captured


async def test_a_hanging_output_does_not_delay_or_prevent_the_others(
    hass, enable_custom_integrations, install, set_person
):
    """One output hangs; the two others are delivered, and quickly.

    Sequentially, this decision costs `fast + timeout + fast` (~0.7 s here).
    Concurrently it costs the timeout (~0.3 s). The assertion sits between the
    two, so it separates the two implementations rather than measuring the
    machine.
    """
    set_person("person.alice", "home")
    calls = _slow_outputs(hass, "mobile_app_one", "mobile_app_three", delay=0.2)
    _slow_outputs(hass, "mobile_app_stuck", delay=HANG_SECONDS, calls=calls)

    entry = make_entry(
        hass,
        persons=[
            make_person(
                "person.alice",
                ["mobile_app_one", "mobile_app_stuck", "mobile_app_three"],
            )
        ],
        targets=[make_target("leak", "Leak", audience=["person.alice"])],
        default_target="leak",
    )
    await install(entry)

    with patch(TIMEOUT_CONSTANT, 0.3):
        started = time.monotonic()
        await hass.services.async_call(
            "notify", "switchboard_leak", {"message": "Water"}, blocking=True
        )
        await hass.async_block_till_done()
        elapsed = time.monotonic() - started

    assert len(calls["mobile_app_one"]) == 1
    assert len(calls["mobile_app_three"]) == 1
    assert len(calls["mobile_app_stuck"]) == 0, (
        "the hanging output must be abandoned at the timeout, not awaited"
    )
    assert elapsed < 0.55, (
        f"the decision took {elapsed:.2f}s; bounded by the slowest single "
        "output (0.3 s), it cannot be the sum of a sequential fan-out"
    )
    assert elapsed < HANG_SECONDS / 2, "the hanging output was awaited to the end"


async def test_a_hanging_output_still_counts_the_person_as_routed(
    hass, enable_custom_integrations, install, set_person, routed_sensor, dropped_sensor
):
    """Unchanged accounting: at least one output went out, so it is a delivery."""
    set_person("person.alice", "home")
    calls = _slow_outputs(hass, "mobile_app_one", delay=0.0)
    _slow_outputs(hass, "mobile_app_stuck", delay=HANG_SECONDS, calls=calls)

    entry = make_entry(
        hass,
        persons=[make_person("person.alice", ["mobile_app_one", "mobile_app_stuck"])],
        targets=[make_target("leak", "Leak", audience=["person.alice"])],
        default_target="leak",
    )
    await install(entry)

    with patch(TIMEOUT_CONSTANT, 0.2):
        await hass.services.async_call(
            "notify", "switchboard_leak", {"message": "Water"}, blocking=True
        )
        await hass.async_block_till_done()

    assert routed_sensor().state == "1"
    assert dropped_sensor().state == "0"

    event_state = hass.states.get("event.switchboard_delivery")
    assert event_state.attributes["event_type"] == "routed"


async def test_every_output_timing_out_is_the_existing_delivery_failed_drop(
    hass, enable_custom_integrations, install, set_person, routed_sensor, dropped_sensor
):
    """ADR-0017 §3: a timeout is recorded exactly like today's failed delivery.

    Same reason (`delivery_failed`), same counter, same `dropped` event — no
    new drop reason and no new event type is introduced by the timeout.
    """
    set_person("person.alice", "home")
    _slow_outputs(hass, "mobile_app_stuck", delay=HANG_SECONDS)

    entry = make_entry(
        hass,
        persons=[make_person("person.alice", ["mobile_app_stuck"])],
        targets=[make_target("leak", "Leak", audience=["person.alice"])],
        default_target="leak",
    )
    await install(entry)

    with patch(TIMEOUT_CONSTANT, 0.2):
        await hass.services.async_call(
            "notify", "switchboard_leak", {"message": "Water"}, blocking=True
        )
        await hass.async_block_till_done()

    assert routed_sensor().state == "0"
    assert dropped_sensor().state == "1"
    assert "delivery_failed" in dropped_sensor().attributes["reasons"]

    event_state = hass.states.get("event.switchboard_delivery")
    assert event_state.attributes["event_type"] == "dropped"
    assert event_state.attributes["reason"] == "delivery_failed"
    assert event_state.attributes["person"] == "person.alice"
    assert event_state.attributes["target"] == "leak"


async def test_an_output_that_raises_does_not_prevent_the_others(
    hass, enable_custom_integrations, install, mock_outputs, set_person, routed_sensor
):
    """`return_exceptions=True`: an exception is a failed output, nothing more."""
    set_person("person.alice", "home")
    calls = mock_outputs("mobile_app_one")
    mock_outputs("mobile_app_broken", raise_exception=ValueError("push refused"))

    entry = make_entry(
        hass,
        persons=[make_person("person.alice", ["mobile_app_broken", "mobile_app_one"])],
        targets=[make_target("leak", "Leak", audience=["person.alice"])],
        default_target="leak",
    )
    await install(entry)

    await hass.services.async_call(
        "notify", "switchboard_leak", {"message": "Water"}, blocking=True
    )
    await hass.async_block_till_done()

    assert len(calls["mobile_app_one"]) == 1
    assert routed_sensor().state == "1"


@pytest.mark.timeout(30)
async def test_all_persons_of_one_decision_are_served_concurrently(
    hass, enable_custom_integrations, install, set_person, routed_sensor
):
    """Concurrency spans persons, not only the outputs of one person.

    Four slow deliveries (two persons x two outputs). Sequentially they cost
    ~1.2 s; concurrently, ~0.3 s.
    """
    set_person("person.alice", "home")
    set_person("person.bob", "home")
    calls = _slow_outputs(
        hass,
        "mobile_app_alice_phone",
        "mobile_app_alice_tablet",
        "mobile_app_bob_phone",
        "mobile_app_bob_tablet",
        delay=0.3,
    )

    entry = make_entry(
        hass,
        persons=[
            make_person(
                "person.alice", ["mobile_app_alice_phone", "mobile_app_alice_tablet"]
            ),
            make_person(
                "person.bob", ["mobile_app_bob_phone", "mobile_app_bob_tablet"]
            ),
        ],
        targets=[make_target("leak", "Leak", audience=["person.alice", "person.bob"])],
        default_target="leak",
    )
    await install(entry)

    started = time.monotonic()
    await hass.services.async_call(
        "notify", "switchboard_leak", {"message": "Water"}, blocking=True
    )
    await hass.async_block_till_done()
    elapsed = time.monotonic() - started

    for output in calls:
        assert len(calls[output]) == 1, f"{output} was not called"
    assert routed_sensor().state == "2"
    assert elapsed < 0.75, (
        f"four 0.3 s deliveries took {elapsed:.2f}s; concurrently they cost "
        "about 0.3 s, sequentially about 1.2 s"
    )
