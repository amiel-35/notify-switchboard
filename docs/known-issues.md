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
fixture for exactly those node ids, with the reasoning above — three of them
since Sprint 2, which reaches the same core bug through
`notify_switchboard.acknowledge` as well as through the Companion callback.
Nothing else in the suite is affected. Planned resolution: an upstream issue
against core so that `async_track_point_in_utc_time` schedules in a way
`cancel_on_shutdown` can see, and/or so that `alert.turn_off` cancels its own
repeat.

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

**Load-bearing from 0.4.0** (ADR-0018 §2). What was a rule the router applied
to outputs the user had typed is now also how the options flow *proposes*
them: for each `mobile_app` config entry whose `user_id` matches the person's,
`dispatcher.companion_service_name(entry.data["device_name"])` is offered
first and labelled as that person's own device. Composing the name any other
way — the prefix plus a separately slugified tail — would now silently propose
nothing for a device whose name contains punctuation, instead of silently
failing to match one. Nothing about the derivation itself changed; the entry
is kept because the reasoning is what makes it safe to build on.

## 2026-09-06 — S1 — the options flow edits one row at a time

Persons and targets are added or updated one row per step, keyed by
`entity_id` / `slug`. Re-submitting an existing key edits that row in place, so
`validate_*`'s `duplicate_person` / `duplicate_slug` rules are unreachable from
the UI and only guard a hand-edited `.storage` file. Renaming a slug means
adding the new row and removing the old one.

Accepted for S1: it keeps the whole table validated before every write
(doctrine §5) without a custom panel. Planned resolution: a nicer editor is a
card/S6 concern.

**Partly addressed in 0.2.0.** The step still writes one whole row at a time,
but it no longer opens empty: `Edit a person` / `Edit a target` pick the row and
`add_suggested_values_to_schema` pre-fills every field with what is stored, and
a validation error hands back what was typed. Before that, opening the target
form to change one word of `message` silently reset `done_message`,
`default_title`, `snooze_minutes` and `default_data` to their schema defaults on
submit — a data-loss bug, not a convenience gap.

**Still one row at a time in 0.4.0, and now more steps per row** (ADR-0018 §2
and §7): the person editor is split in two (`person` picks the `person.*`,
`person_outputs` edits it) because a form cannot react to a field it is
showing and the discovered outputs depend on which person was chosen, and the
row editor gains a `target_saved` confirmation step carrying the `alert:`
snippet. What 0.4.0 does remove is the *reason* most people meet this
limitation in their first hour: a fresh install no longer needs a hand-written
row at all, since the first person creates the managed `default` one. Planned
resolution unchanged: a nicer editor is a card concern.

## 2026-09-07 — S1 — the Companion `device_id` path is unverified on a real device

`Switchboard._resolve_persons` matches the `device_id` carried by a
`mobile_app_notification_action` event against the device registry, directly
and as a `("mobile_app", <id>)` identifier, then turns the device's name into
`slugify(f"mobile_app_{name}")` and looks for a person listing that output.
Every branch is unit tested against a synthetic registry, but **no event from
a real Companion device has ever been observed by this project**: whether the
`device_id` is the registry id, the webhook id, or the registration id is
inferred from core's source, not measured.

Accepted for S1 because it is now only the *second* resolution path:
`event.context.user_id` is tried first and is exact (see
`docs/ARCHITECTURE.md`), and when both fail the documented fallback snoozes
the whole audience — never the wrong person alone. Planned resolution:
capture one real callback on the dev instance and pin its shape in a test.

**Narrowed, not resolved, in 0.3.0** (ADR-0017 §4). Still unverified — that
needs a physical phone and stays out of scope. What changes is its status: the
`user_id` link becomes the *canonical* one in the contract rather than merely
the first tried, the `device_id` lookup is documented as a fallback and logged
at DEBUG as such, and a person who cannot be resolved through `user_id` while
sitting in a button-bearing row now raises a `person_without_user_id` repair
instead of silently landing in the audience-wide fallback.
`tests/acceptance/test_s3_callbacks.py` pins that a resolvable `user_id` is
never overridden by a `device_id` pointing elsewhere.

## 2026-09-07 — S3 — `Entity.suggested_object_id` does not freeze the id here

ADR-0017 §2 names `Entity.suggested_object_id`
(`homeassistant/helpers/entity.py`, property at line 747) as the override that
keeps the frozen English entity ids while the friendly names follow the
instance language. Implementing it showed that, in core 2026.9.1, it does not
do that for an entity that has both `has_entity_name` and a device — which is
every entity of this integration:

- `_async_derive_object_ids` (`homeassistant/helpers/entity_platform.py`,
  lines 1296-1329) leaves `is_base` True on the `entity.suggested_object_id`
  path, so the value is passed to the registry as `object_id_base`, not as
  `suggested_object_id`;
- `object_id_base` **is** composed with the device name
  (`homeassistant/helpers/entity_registry.py`, `_async_generate_entity_id` ->
  `_async_get_full_entity_name`), which yielded
  `sensor.switchboard_switchboard_routed_today` when this was tried.

Only `internal_integration_suggested_object_id` — what the platform records
when an entity sets `self.entity_id` itself
(`homeassistant/helpers/entity_platform.py`, lines 886-909) — reaches the
registry as the `suggested_object_id` that "has priority over
`object_id_base`" and "will not be prefixed with the device name".

Accepted, not a defect of the integration: ADR-0017 §2 explicitly allows the
`self.entity_id` route ("Either way the requirement is behavioural") and the
acceptance tests assert the behaviour, not the mechanism. 0.3.0 therefore keeps
setting `self.entity_id`, as 0.1.0 and 0.2.0 already did, and `entity.py`
carries the reasoning above so nobody "modernises" it back. Planned
resolution: an editorial correction to ADR-0017 §2 next time that ADR is
touched.

## 2026-09-07 — S1 — `authenticationRequired` cannot be overridden per row

The contract says `authenticationRequired: true` is set "by default" when the
row's priority is `high` or `critical`, and the brief adds "unless the row
overrides". No override exists: `AUTHENTICATED_PRIORITIES` is consulted
directly in `Switchboard._async_build_payload`, so a row cannot ask for an
unauthenticated Acknowledge on a `critical` alert, nor for an authenticated
one on an `info` alert.

Accepted for S1: adding a fourth state (unset / forced on / forced off) to
every routing-table row costs a field in the options flow, a migration and
three translations, for a case nobody has hit yet. Still open: the Sprint 2
brief lists `require_authentication` under "Out of scope (must not)", so 0.2.0
did not take it up even though it added three other per-row fields. Planned
resolution: a `require_authentication` tri-state on the row when a real use
case shows up.

## 2026-09-07 — S1 — two `alert` limitations to raise upstream

This entry exists so the follow-up is not lost:

1. `AlertEntity` (`homeassistant/components/alert/entity.py`) exposes no state
   attributes at all — both `message` and `done_message` are rendered
   internally to build the `notifiers` payload and never surfaced — so neither
   can be read by observer mode. **No longer blocking this integration**: the
   row now owns its own `message`/`done_message` templates (ADR-0016, shipped
   in 0.2.0), which is option (a) the original entry raised. The attribute is
   still checked first, for the day core changes its mind.
2. `alert.turn_off` sets `_ack` but never calls `self._cancel()`, so
   acknowledging leaves the repeat timer armed, and `cancel_on_shutdown` is
   unenforceable because `async_track_point_in_utc_time` schedules with
   `loop.call_at(when, self)` and no `HassJob` in `handle._args`. Still open,
   and still the reason `tests/conftest.py` tolerates a lingering timer for
   the three tests that drive a real alert.

Neither issue has been filed against home-assistant/core yet. Planned
resolution: file (2) and link the issue number here; (1) is now a
nice-to-have rather than a gap.

## 2026-09-07 — S2 — the UI services are not admin-restricted, by design

`notify_switchboard.acknowledge`, `snooze`, `unsnooze`, `silence` and
`unsilence` are callable by any Home Assistant user, administrator or not. This
came up in the Sprint 2 review and was decided, not overlooked: the wall tablet
runs under a **non-admin** account and its cards are the main caller, so an
admin-only domain would break the one surface ADR-0016 was written for while
leaving the Companion buttons — which are events, not service calls, and so
cannot be role-gated at all — as the only way to acknowledge anything.

What bounds them instead: the ADR-0009 allow-list (only an `alert.*` that is in
the routing table, on a row with `allow_acknowledge`), `context.user_id` logged
on every refusal and carried in the `acknowledged`/`snoozed` events, and
`authenticationRequired` still set on `high`/`critical` Companion buttons. The
full reasoning is the "Addendum (2026-09-07, post-review)" section of
[`ADR/0016`](ADR/0016-ui-services-and-row-texts.md).

Revisit if a household needs it — a child who keeps silencing the smoke alert,
a guest account. Planned resolution: an optional per-row flag next to
`allow_acknowledge` in a later version, never a blanket restriction on the
domain.

**One more non-admin service in 0.4.0**: `notify_switchboard.explain`
(ADR-0018 §1). It is the least dangerous of the six — it changes nothing at
all — but it does read the routing table back to whoever asks, including which
`notify.*` services a person's phone maps to. That is the same information the
options flow already shows, and the wall tablet's cards are the intended
caller, so the decision above is unchanged rather than re-taken.

## 2026-09-07 — S2 — a deferral now re-checks silence, but only silence

`Switchboard._async_flush_deferrals` used to trust its timer: whatever was
queued for a person went out at their `wake_time`, full stop. A night schedule
that runs late, a `notify_switchboard.silence` set in the small hours, or a
Home Assistant that came back up mid-night would therefore push the whole queue
at somebody still asleep — the exact notification the deferral exists to
prevent. Fixed in 0.2.0: the flush re-reads `is_person_silenced` and keeps a
still-silenced message queued, re-arming for whichever comes first, the end of
the temporary silence or the next wake time. `critical` is delivered regardless,
as it is everywhere else.

Still accepted, and this is the narrowed version of the old
`docs/ARCHITECTURE.md` line "deferred deliveries do not re-run the decision":
**only the silence is re-checked**, not the rest of the routing decision. A
person who left the row's audience, who is now away under a `home_only` rule, or
who has since snoozed that row, still gets their queued message at the wake
time. Nothing is lost that way, which is the property the deferral is for; the
cost is a message that a fresh decision might have dropped. Re-running `decide`
at flush time would need a `RoutingContext` for a request that no longer exists
and a rule for what to do with a message the second decision drops (deliver it
anyway? count it? re-queue it?), which is a design question, not a bug fix.
Planned resolution: decide it if somebody reports the case; today the wake time
is minutes away from the decision that queued the message.

A configured silence entity that goes `off` well before the wake time does not
trigger an early flush either: `_async_silence_changed` refreshes
`binary_sensor.<p>_silenced` but does not re-arm the deferral timer. The message
waits for the wake time, which is the documented promise.

## 2026-09-07 — S3 — two repairs that cannot clear themselves

Every repair this integration raises is deleted when its cause goes away, with
two exceptions that are ignorable in the UI rather than defects:
`unknown_target_<slug>` stays until the routing table is reloaded, so fixing
the *caller* instead of adding the row leaves it up, and `missing_output_<x>`
clears on the first call that succeeds, so an output that is still configured
but never called again keeps its warning. Neither can be observed by the
router — nothing tells it a service call it never sees would work now — so
both are safe to dismiss in Repairs.

**The two repairs added in 0.4.0 are not in that category** (ADR-0018 §5):
`person_without_outputs` is re-evaluated on every reload, and an options change
reloads the entry, so it disappears the moment the person is given an output;
`alert_entity_missing` is re-evaluated at each grace check after a reload, so
defining the missing `alert:` block and reloading clears it. This entry is kept
as it is — the two older cases are unchanged — so that the distinction stays on
the record: a repair this integration adds should be able to clear itself, and
the two that cannot are the exception rather than the pattern.
