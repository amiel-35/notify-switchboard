# Known issues and accepted findings

Findings from the tester or reviewer that were explicitly accepted by the
orchestrator instead of blocking a release. Each entry: date, sprint, finding,
why accepted, planned resolution.

## 2026-09-06 — S1 — `alert` leaves an un-cancellable repeat timer in tests

`tests/acceptance/test_s1_actions.py::test_acknowledge_action_turns_off_the_row_alert_when_allowed`
and `::test_acknowledge_is_refused_for_an_alert_not_in_the_routing_table` both
end with a real `alert.*` still firing, which fails
pytest-homeassistant-custom-component's lingering-timer check at teardown.

This belongs to core, not to this integration, and acknowledging does **not**
fix it:

- `homeassistant/components/alert/entity.py`, `async_turn_off` only sets
  `self._ack = True`. It never calls `self._cancel()`; only `end_alerting`
  (the watched entity leaving the alert state) cancels the repeat. The
  acceptance tests never move the watched `binary_sensor`, so the repeat timer
  is still armed when the test ends.
- `AlertEntity._schedule_notify` does pass `cancel_on_shutdown=True`, but
  `homeassistant/helpers/event.py`, `_TrackPointUTCTime.async_attach` schedules
  with `loop.call_at(when, self)` — no arguments. Both
  `HomeAssistant._cancel_cancellable_timers` (`homeassistant/core.py`) and
  `verify_cleanup` (pytest-homeassistant-custom-component `plugins.py`) look
  for a `HassJob` in `handle._args`, find nothing, and so can never honour the
  flag. Reproduced with a two-line test that only sets up core's `alert`.

Accepted: `tests/conftest.py` overrides the `expected_lingering_timers`
fixture for exactly those two node ids, with the reasoning above. Nothing else
in the suite is affected. Planned resolution: an upstream issue against core so
that `async_track_point_in_utc_time` schedules in a way `cancel_on_shutdown`
can see, and/or so that `alert.turn_off` cancels its own repeat.

## 2026-09-06 — S1 — a real `alert.*` never exposes `message` or `done_message`

Brief item 8 asks observer mode to read the alert's `message` attribute on
`idle -> on` and its `done_message` on `-> idle`. `AlertEntity`
(`homeassistant/components/alert/entity.py`) has no `extra_state_attributes`
at all: both templates are rendered internally to build the `notifiers`
payload and are never surfaced on the entity's state.

Observer mode is implemented exactly as specified, so a real alert always
takes the fallback branch: the row's `name` on `idle -> on`, and the
translated `common.back_to_normal` on `-> idle`. Both branches are covered by
the acceptance suite, which drives a synthetic `alert.*`-shaped entity.

Accepted for S1. Planned resolution: an ADR before S2 decides whether the row
should own its own message templates, or whether to propose the attributes
upstream.

## 2026-09-06 — S1 — `mobile_app` no longer registers legacy notify services

`homeassistant/components/mobile_app/notify.py` in 2026.9.1 exposes Companion
push as a `MobileAppNotifyEntity`, not as a legacy `BaseNotificationService`
with a `targets` property. The `mobile_app_*` prefix check that decides which
outputs get buttons (brief item 5) therefore matches whatever the user typed
as an output, not something the modern `mobile_app` integration hands out.

Accepted for S1 because the contract is written in terms of legacy notify
service names and the acceptance suite mocks them. Planned resolution: revisit
once a real Companion device is wired to the dev instance — the router may need
to treat a `notify.*` **entity** as an output too, which is a contract change
and therefore an ADR.

## 2026-09-06 — S1 — the options flow edits one row at a time

Persons and targets are added or updated one row per step, keyed by
`entity_id` / `slug`. Re-submitting an existing key edits that row in place, so
`validate_*`'s `duplicate_person` / `duplicate_slug` rules are unreachable from
the UI and only guard a hand-edited `.storage` file. Renaming a slug means
adding the new row and removing the old one.

Accepted for S1: it keeps the whole table validated before every write
(doctrine §5) without a custom panel. Planned resolution: a nicer editor is a
card/S6 concern.
