# `cancel_on_shutdown` is silently ignored for `async_call_later` / `async_call_at` / `async_track_point_in_time`

> Draft for `home-assistant/core`. Checked against **2026.9.1**.
> Suggested labels: `core`, `bug`.

## The problem

`HassJob(..., cancel_on_shutdown=True)` documents that the job's timer is
cancelled when Home Assistant stops. For the three most commonly used timer
helpers it has no effect at all: the handle is left scheduled, and nothing
warns.

`HomeAssistant._cancel_cancellable_timers` only cancels a handle whose **first
scheduled argument** is the `HassJob` itself
(`homeassistant/core.py`, lines 1265-1274):

```python
def _cancel_cancellable_timers(self) -> None:
    """Cancel timer handles marked as cancellable."""
    for handle in get_scheduled_timer_handles(self.loop):
        if (
            not handle.cancelled()
            and (args := handle._args)  # noqa: SLF001
            and type(job := args[0]) is HassJob
            and job.cancel_on_shutdown
        ):
            handle.cancel()
```

None of the three helpers below schedules the job in that position.

**`async_call_later`** (`homeassistant/helpers/event.py`, line 1552) ends at
line 1570 with:

```python
return loop.call_at(loop.time() + delay, _run_async_call_action, hass, job).cancel
```

so `handle._args` is `(hass, job)` and `args[0]` is the `HomeAssistant`
object, never a `HassJob`.

**`async_call_at`** (line 1532) has the same shape at line 1548:

```python
return hass.loop.call_at(loop_time, _run_async_call_action, hass, job).cancel
```

**`async_track_point_in_time`** (line 1420) goes through
`_TrackPointUTCTime` (line 1454), whose `async_attach` (line 1461) schedules
the dataclass instance itself at line 1464:

```python
self._cancel_callback = loop.call_at(
    loop.time() + self.expected_fire_timestamp - time.time(), self
)
```

so `args[0]` is a `_TrackPointUTCTime`, and the same test fails. (Line 1485,
in the rescheduling path, has the same shape.)

## Why it matters in core itself

`AlertEntity._schedule_notify`
(`homeassistant/components/alert/entity.py`, line 128) passes the flag
through `async_track_point_in_time` at line 132:

```python
self._cancel = async_track_point_in_time(
    self.hass,
    HassJob(self._notify, name="Schedule notify alert", cancel_on_shutdown=True),
    next_msg,
)
```

The intent is unambiguous, and it is not honoured: an alert that is firing
when Home Assistant stops leaves its repeat timer scheduled. In practice this
shows up as "Lingering timer after test" failures for anything that sets up a
real `alert` and does not end it explicitly — `alert.turn_off` only sets
`_ack`, so only `end_alerting` clears the timer.

## Reproduction

```python
import asyncio

from homeassistant.core import HassJob, HomeAssistant, callback
from homeassistant.helpers.event import async_call_later
from homeassistant.util.async_ import get_scheduled_timer_handles


async def main() -> None:
    hass = HomeAssistant("/tmp/ha-repro")

    @callback
    def _cb(_now):
        pass

    async_call_later(hass, 3600, HassJob(_cb, "repro", cancel_on_shutdown=True))

    before = [h for h in get_scheduled_timer_handles(hass.loop) if not h.cancelled()]
    hass._cancel_cancellable_timers()
    after = [h for h in get_scheduled_timer_handles(hass.loop) if not h.cancelled()]

    print("scheduled before:", len(before), "still scheduled after:", len(after))
    print("args[0] type:", type(before[-1]._args[0]).__name__)


asyncio.run(main())
```

Output on 2026.9.1:

```
scheduled before: 1 still scheduled after: 1
args[0] type: HomeAssistant
```

Expected: `still scheduled after: 0`.

## Possible fixes

Not a preference, just what the options look like from outside:

1. **Make `_cancel_cancellable_timers` look for the job rather than assume its
   position** — scan `handle._args` for a `HassJob` with `cancel_on_shutdown`,
   and give `_TrackPointUTCTime` (and its siblings around lines 1589, 1667 and
   1760, which have the same `async_attach` shape) a way to expose the job it
   holds. This fixes every helper at once and needs no call-site change.
2. **Schedule the job first** — `loop.call_at(when, _run_async_call_action,
   job, hass)` with the argument order of `_run_async_call_action` swapped.
   Smallest change, but it only fixes the two `call_*` helpers and leaves the
   `_Track*` dataclasses out.
3. **Document the flag as applying only to jobs scheduled directly**, and drop
   it from `AlertEntity._schedule_notify`, which would at least stop it from
   reading as a guarantee.

Happy to open a PR for whichever shape a maintainer prefers.

## Environment

- Home Assistant core 2026.9.1
- Reproduced with the `HomeAssistant` object alone; no integration involved.
