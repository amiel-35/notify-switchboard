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

## 2026-09-07 — S1 — the Companion output prefix, and what it really matches

An earlier version of this entry claimed that `mobile_app` in 2026.9.1 no
longer registers legacy `notify.mobile_app_*` services. **That was wrong**, and
the correction is recorded here rather than deleted so the reasoning is
auditable.

In core 2026.9.1 (`homeassistant/components/mobile_app/`) Companion push is
still a legacy notify platform:

- `__init__.py`, line 110: `discovery.async_load_platform(hass,
  Platform.NOTIFY, DOMAIN, {}, config)` loads the notify platform at startup;
- `notify.py`, line 177, `async_get_service` returns a
  `MobileAppNotificationService(BaseNotificationService)` (line 187) whose
  `targets` property (line 192) is `push_registrations(hass)`, a
  `{device_name: webhook_id}` mapping of every push-capable registration.

So core does register one `notify.mobile_app_<device>` service per Companion
registration, and `BaseNotificationService.async_register_services`
(`homeassistant/components/notify/legacy.py`, line 275) names it
`slugify(f"{prefix}_{name}")` — that is, the **whole** string is slugified,
not the prefix plus a separately slugified device name. The switchboard now
composes candidate names the same way (`dispatcher.companion_service_name`);
composing them any other way silently fails to match on device names that end
in a separator or contain punctuation.

What remains true, and is the reason the `mobile_app_` prefix rule is kept: the
prefix is a **reliable** marker for "this output is a Companion push service",
because core builds every one of those names from the fixed `mobile_app`
platform prefix. Buttons are therefore added to outputs whose service name
starts with `mobile_app_` and to no others.

What is genuinely still unverified is the *callback* side: the `device_id`
carried by a `mobile_app_notification_action` event has not been observed on a
real device from this project, so the device-registry lookup in
`Switchboard._resolve_persons` is written defensively and is only the second
choice, after `context.user_id`. See the entry below.

## 2026-09-06 — S1 — the options flow edits one row at a time

Persons and targets are added or updated one row per step, keyed by
`entity_id` / `slug`. Re-submitting an existing key edits that row in place, so
`validate_*`'s `duplicate_person` / `duplicate_slug` rules are unreachable from
the UI and only guard a hand-edited `.storage` file. Renaming a slug means
adding the new row and removing the old one.

Accepted for S1: it keeps the whole table validated before every write
(doctrine §5) without a custom panel. Planned resolution: a nicer editor is a
card/S6 concern.
