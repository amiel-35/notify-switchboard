# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
  carries a reason (`not_in_audience`, `presence`, `silenced`, `snoozed`,
  `recursion`, `unknown_target`, `no_outputs`).
- **Companion buttons**: `Acknowledge` when the row has an alert and allows it,
  one `Snooze <n>` per configured duration, labels translated through the new
  `common` section, `authenticationRequired` on `high` and `critical` rows.
- **Companion callbacks**: acknowledging turns off the row's alert only when
  that alert is in the routing table (allow-list, refusals logged with
  `context.user_id`); snoozing stores `(person, target) -> expiry` in `Store`
  and survives a restart.
- **Night deferral**: a message silenced while the person is asleep is queued
  (latest wins per `tag`) and delivered at their wake time, correctly across
  midnight and across a DST change.
- **Observer mode**: watch a row's `alert.*` and route on `idle -> on` and
  `-> idle`, without being listed as a notifier.
- **Entities** of contract §3.5: `binary_sensor.<person>_silenced`,
  `sensor.<person>_last_notification`, `sensor.<person>_active_snoozes`,
  `sensor.switchboard_routed_today`, `sensor.switchboard_dropped_today` (with
  a `reasons` attribute), `event.switchboard_delivery`. Counters reset at local
  midnight.
- **Repairs**: one issue for an unknown target, one for an output missing for
  more than three consecutive calls.
- **Diagnostics** with `async_redact_data` on message bodies, plus the table,
  the snoozes, the deferrals and the last twenty decisions.
- `async_migrate_entry` and `ConfigEntry.version = 1` / `minor_version = 1`.
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
