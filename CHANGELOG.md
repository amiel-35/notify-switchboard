# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

Router 0.2.0 — UI services (contract v0.2 addendum, ADR-0016).

### Added

- **Five `notify_switchboard.*` services** for callers that are not a
  Companion push notification — a card, a script, an automation:
  `acknowledge`, `snooze`, `unsnooze`, `silence`, `unsilence`. They reuse the
  Companion code paths and differ in one respect only: a service call has a
  caller, so a refused or invalid call raises a `ServiceValidationError` with a
  translated message instead of being logged and swallowed. `acknowledge`
  keeps the ADR-0009 allow-list; `snooze` additionally refuses a duration the
  row does not offer, and an explicit `person` outside the row's audience.
  Declared in `services.yaml`, with `en`/`fr`/`es` translations under
  `services` and `exceptions`.
- **Temporary, person-wide silence** (`silence` / `unsilence`), a second and
  independent source of silence the router owns: the person's configured
  `silence_entities` are still read, never touched. It is persisted in the
  same `Store` as snoozes (minor version 3, migrated), shows up in
  `binary_sensor.<person>_silenced` (with an `until` attribute while it runs),
  drops routing with the existing `silenced` reason, is bypassed by
  `priority: critical`, and expires both lazily and on its own timer — so the
  sensor goes back to `off` at the right minute, not at the next notification.
  `silence` with `minutes: 0` is refused; `unsilence` on somebody who is not
  silenced is a no-op, not an error.
- **Three optional per-row texts**: `message` and `done_message`, templates
  rendered with the row's alert's current state exposed as `alert`, and
  `default_title`, used as the outgoing title whenever the caller gave none —
  including every message observer mode generates. All three default to
  absent, so a routing table written for 0.1.0 behaves exactly as it did.
  This resolves the known-issues entry "a real `alert.*` never exposes
  `message` or `done_message`": the row, not the alert, is now the documented
  source of observer-mode text.
- **A `repairs` issue** when the same unknown target or unusable person is
  refused by a service three times in a row — a card left pointing at a
  renamed row, the counterpart of `MAX_CONSECUTIVE_OUTPUT_MISSES`.

### Changed

- `binary_sensor.<person>_silenced` is now true when **either** silence source
  is active. Its `sources` attribute keeps its 0.1.0 meaning (the configured
  entities).
- Observer mode's `idle -> on` text order is now: the alert's own `message`
  attribute, the row's `message` template, the row's name. Its
  `on|off -> idle` order is: the row's `done_message` template, the alert's
  own `done_message` attribute, the translated `common.back_to_normal`
  (contract §"Per-row texts" and ADR-0016 §3 both put the row first here).
  Absent the new fields, both chains end exactly where 0.1.0 ended.
- A message silenced only by a temporary silence is dropped with reason
  `silenced` rather than deferred: `wake_time` is documented as the end of the
  *night* silence, and queueing an hour of requested quiet until tomorrow
  morning would be the wrong kind of late. A configured night silence still
  defers, even when a temporary silence is running on top of it.
- The routing-table options flow gained the three new text fields; the two
  template fields use a `TemplateSelector`, which refuses unparsable Jinja.

## [0.1.0] - 2026-09-07

### Added

- **Routing table** in the options flow: people (their `notify.*` outputs,
  their silence entities, their wake time) and targets (slug, name, class,
  default priority, linked `alert.*`, audience, presence rule, acknowledgement,
  snooze durations, default data, observer mode), validated as a whole before
  anything is written.
- **Per-target legacy services**: `notify.switchboard_<slug>` for every row,
  alongside `notify.switchboard`, so an `alert` can name its row in
  `notifiers:`.
- **Decision engine** (`router.py`, pure functions): audience, presence rule,
  silence, active snooze, `critical` bypass, recursion rejection. Every drop
  carries a reason (`not_in_audience`, `unknown_person`, `presence`,
  `silenced`, `snoozed`, `recursion`, `unknown_target`, `no_outputs`,
  `delivery_failed`); only `not_in_audience` is left out of the daily count.
- **Companion buttons**: `Acknowledge` when the row has an alert and allows it,
  one `Snooze <n>` per configured duration, labels translated through the new
  `common` section, `authenticationRequired` on `high` and `critical` rows.
- **Companion callbacks**: acknowledging turns off the row's alert only when
  that alert is in the routing table (allow-list, refusals logged with
  `context.user_id`); snoozing stores `(person, target) -> expiry` in `Store`
  and survives a restart.
- **Night deferral**: a message silenced while the person is asleep is queued
  (latest wins per `tag`) and delivered at their wake time, correctly across
  midnight and across a DST change. A deferral whose wake time passed while
  Home Assistant was down is delivered at the next start, not a day later.
- **Observer mode**: watch a row's `alert.*` and route on `idle -> on` and
  `-> idle`, without being listed as a notifier.
- **Entities** of contract §3.5: `binary_sensor.<person>_silenced`,
  `sensor.<person>_last_notification`, `sensor.<person>_active_snoozes`,
  `sensor.switchboard_routed_today`, `sensor.switchboard_dropped_today` (with
  a `reasons` attribute), `event.switchboard_delivery`, plus the additional
  `sensor.switchboard_deferred_today` (attribute `queued`) so a queued night
  is not indistinguishable from a quiet one. Counters reset at local midnight
  and declare `last_reset`.
- **Repairs**: one issue for an unknown target, one for an output that has
  been unusable — missing, or raising on every call — for more than three
  consecutive calls.
- **Diagnostics** with `async_redact_data` on message bodies and every
  `default_data` value redacted (keys kept), plus the table, the snoozes, the
  deferrals and the last twenty decisions.
- `async_migrate_entry`, `async_remove_entry` (which deletes the stored
  document) and `ConfigEntry.version = 1` / `minor_version = 1`.
- Translations extended to the whole options flow, the repairs and the
  router-added labels, in `en`, `fr` and `es`.

### Changed

- The `NotifyEntity` is now explicitly the degraded path: it routes to the
  default row with priority `normal`.
- The legacy notify service is registered directly instead of through
  `discovery.async_load_platform`, so it survives a config entry reload.
- Options are no longer a flat `default_targets` list; the entry now stores
  `persons`, `targets` and `default_target`.

### Removed

- The pass-through `Router` of the scaffold.

### Upgrading from 0.0.1

The `NotifyEntity` unique_id changed. Setting the entry up now removes the
registry row left by the old scheme, so `notify.switchboard` is reused instead
of the entry appearing as an `unavailable` `notify.switchboard` plus a live
`notify.switchboard_2`. Nothing to do by hand.

### Known limitations

Detailed in [`docs/known-issues.md`](docs/known-issues.md):

- entity display names are hard-coded in English (their translation is
  planned; only the router-added button labels are translated today);
- `authenticationRequired` is derived from the row's priority and cannot be
  overridden per row;
- the options flow edits one person or one target per step;
- core's `alert` exposes neither `message` nor `done_message` as a state
  attribute, so observer mode always uses its fallbacks, and `alert.turn_off`
  does not cancel the repeat timer (both to be raised upstream);
- the Companion `device_id` path of the snooze callback has not been verified
  against a real device; `context.user_id` is tried first and does not depend
  on it.

[Unreleased]: https://github.com/amiel-35/notify-switchboard/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/amiel-35/notify-switchboard/compare/v0.0.1...v0.1.0
