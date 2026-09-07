# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

Router 0.3.0 — debts and robustness (contract v0.3 addendum, ADR-0017). No new
user-facing concept: no TTL, no summary, no escalation, no new option key.

### Added

- **Translated entity names, frozen entity ids.** Every entity of the
  integration is now named through an `entity.<platform>.<key>.name` string in
  `strings.json` and in `translations/{en,fr,es}.json`, so a French or Spanish
  instance reads French or Spanish names. The **entity ids do not change, in
  any language** — `binary_sensor.<person>_silenced`,
  `sensor.<person>_last_notification`, `sensor.<person>_active_snoozes`,
  `sensor.switchboard_routed_today`, `sensor.switchboard_dropped_today`,
  `sensor.switchboard_deferred_today` and `event.switchboard_delivery` stay
  exactly as documented, so no `alert:`, automation or card breaks. This is not
  automatic: `fr` and `es` are `NATIVE_ENTITY_IDS` languages, on which core
  builds object ids out of the *localized* name, which is why the ids are
  pinned explicitly (see `custom_components/notify_switchboard/entity.py`).
- **`sensor.switchboard_deferred_today` is a frozen public name.** It has
  existed in code since 0.1.0; it now sits in `docs/contract.md` next to its
  two siblings and is pinned by the contract test. Nothing about the entity
  changes.
- **A `person_without_user_id` repair.** Raised once per person who is in the
  audience of a row that adds Companion buttons (`allow_acknowledge`, or a
  non-empty `snooze_minutes`) and whose `person.*` is not linked to a Home
  Assistant user — the link Notify Switchboard needs to tell *who* pressed a
  button. Severity warning, not fixable from the repair itself (the link is
  made in Settings → People), translated, and deleted on the next reload once
  the link exists.

### Changed

- **Fan-out is parallel and bounded.** Every (person, output) delivery of one
  routing decision is now attempted concurrently, each wrapped in a 30 second
  per-output timeout (`dispatcher.OUTPUT_TIMEOUT_SECONDS`). A phone that is off
  the network no longer holds back everybody else's notification, and the wall
  time of a decision is bounded by its slowest single output rather than by the
  sum of them all. A timed-out or failing output is accounted for exactly as a
  failed delivery already was: same repair, same `delivery_failed` drop reason
  when *every* output of a person failed, same counter, same `dropped` event.
  No new drop reason and no new event type. The **order** of the resulting
  `event.switchboard_delivery` events is now explicitly not promised; the
  counts and the per-person outcomes still are.
- **`person.user_id` is the canonical link for Companion callbacks.** A
  callback whose `context.user_id` matches a `person.*` is attributed to that
  person, whatever the event's `device_id` says. The `device_id` lookup remains
  as a fallback only and is logged at DEBUG as such; it has still never been
  observed on a real device (`docs/known-issues.md`).
- **The five `notify_switchboard.*` actions are registered in `async_setup`**
  (quality-scale rule `action-setup`) and therefore exist whether or not a
  config entry is loaded. An automation that names one of them no longer fails
  its own validation at startup with "action not found" because an entry
  happened to be unloaded. Called while no entry is loaded, each raises a
  translated `ServiceValidationError` (`no_loaded_entry`). Unloading an entry
  removes their ability to act, not the actions themselves.
- **`quality_scale.yaml` tells the truth.** Every rule of every tier is
  assessed: `action-setup`, `docs-actions`, `entity-translations` and `brands`
  become `done`, and silver, gold and platinum are assessed rather than left
  out.

### Fixed

- **A lingering midnight timer when Home Assistant stops.** Config entries are
  not unloaded on shutdown, so nothing ran the switchboard's teardown: the
  daily counter reset armed by `async_track_time_change`, the
  `mobile_app_notification_action` bus listener and the state trackers all
  stayed attached to a loop that was going away. `EVENT_HOMEASSISTANT_STOP` now
  detaches everything, not just the deferral and silence timers. This was
  visible as an intermittent "Lingering timer after test …
  `Switchboard._async_reset_counters`" in the config-flow tests.
- **An ERROR with a traceback at every shutdown.** The teardown above kept the
  `EVENT_HOMEASSISTANT_STOP` unsub in the same list as the others and called it
  again from `async_shutdown`, after core's one-time listener had already
  removed it — so every single stop logged "Unable to remove unknown job
  listener" with a `ValueError`. The stop unsub now has its own slot and is
  called exactly once, whichever of the two paths runs.
- **`unknown_target` and `missing_output` repairs that never went away.** The
  issue registry is persisted and neither of those two was ever deleted, so the
  warning outlived the very change it asked for. Creating the missing routing
  row now clears its `unknown_target` repair on the reload; an output clears
  its `missing_output` repair on the first call that succeeds — restart or
  not, the deletion no longer depends on an in-memory counter — or when it is
  removed from every person's outputs.
- **A person lost from the counters.** When one person's delivery raised an
  unexpected error, the fan-out logged it and moved on without counting that
  person at all — neither routed nor dropped. It is now counted as
  `delivery_failed`, the same as any other delivery that reached nobody.
- **Per-person devices are named after the person.** The virtual device used
  the person's object_id titled (`person.alice` → "Alice"), ignoring the
  friendly name a user set in the UI ("Alice Martin"). It now uses the person's
  state name, falling back to the old form only when the person has no state
  yet.
- **`quality_scale.yaml` parses.** One unquoted comment containing ": " made
  the whole self-assessment file invalid YAML. A unit test now parses it and
  checks it assesses exactly hassfest's rule set for 2026.9.1.

### Documentation

- `docs/contract.md` gains a "v0.3 addendum (ADR-0017)" block; ADR-0017 records
  the four decisions and the one non-guarantee.
- The `done_message` fallback order is stated identically everywhere it appears
  (`docs/contract.md` is authoritative): the row's `done_message` template, then
  the alert's own `done_message` attribute, then the translated
  `common.back_to_normal`. `tests/acceptance/README.md` and
  `docs/sprints/sprint-2-brief.md`, which had it backwards, are corrected;
  `tests/acceptance/test_s3_done_message.py` pins it.
- `docs/known-issues.md`: the two entries this release resolves are removed, and
  one is added about what `Entity.suggested_object_id` actually does in core
  2026.9.1.
- `README.md` no longer says the quickstart and the blueprints are planned, and
  links `docs/how-this-is-built.md`.

## [0.2.0] - 2026-09-07

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
  `minutes` must be between 1 and 1440 (a day): anything outside that raises a
  translated `ServiceValidationError`, including the values large enough to make
  `datetime` arithmetic overflow. `unsilence` on somebody who is not silenced is
  a no-op, not an error.
- **Three optional per-row texts**: `message` and `done_message`, templates
  rendered with the row's alert's current state exposed as `alert`, and
  `default_title`, used as the outgoing title whenever the caller gave none —
  including every message observer mode generates. All three default to
  absent, so a routing table written for 0.1.0 behaves exactly as it did.
  This resolves the known-issues entry "a real `alert.*` never exposes
  `message` or `done_message`": the row, not the alert, is now the documented
  source of observer-mode text.
- **A `repairs` issue** when the same unknown target or unusable person has
  been refused by a service three times — a card left pointing at a renamed
  row, the counterpart of `MAX_CONSECUTIVE_OUTPUT_MISSES`. The count is
  **cumulative, not consecutive**: three refusals a week apart raise the issue
  just as three in a row do, because a card wired to a stale slug fires whenever
  somebody taps it rather than in bursts. It is reset — and the issue deleted —
  when that slug or person is accepted again, and at setup for everything the
  reloaded routing table now knows about, so fixing the cause in the options
  flow makes the warning go away. At most 20 distinct bad values get an issue
  of their own; past that a single `invalid_service_calls_many` stands for the
  rest, so a caller generating a fresh bad value every time cannot fill the
  (persisted) issue registry.

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
- **The options flow no longer forgets the row it is editing.** Two new menu
  entries, `Edit a person` and `Edit a target`, pick a row and open its form
  pre-filled with what is stored; a validation error now hands back what was
  typed instead of an empty form. The step writes the whole row, so opening it
  to change one word of `message` used to reset `done_message`,
  `default_title`, `snooze_minutes` and `default_data` to their defaults on
  submit.
- **A deferred message re-checks the silence before going out.** `wake_time` is
  a prediction that the night is over, not a promise: a schedule running late,
  a `notify_switchboard.silence` set in the small hours or a restart spanning
  the night used to push the whole queue at somebody still asleep. A
  still-silenced message stays queued and the flush is re-armed for whichever
  comes first, the end of the temporary silence or the next wake time.
  `critical` is delivered regardless. The rest of the routing decision is still
  not re-run (`docs/known-issues.md`).
- **Acknowledging carries the caller's context**, so the logbook credits the
  person who tapped the card or the Companion button rather than the
  integration. `alert.turn_off` gets a *child* of that context on purpose:
  core treats a non-empty `context.user_id` on an entity service call as an
  authorisation claim, and the row's ADR-0009 allow-list — not the caller's
  entity permissions — is what decides here. The `acknowledged` and `snoozed`
  `event.switchboard_delivery` events carry the caller's own context.
- Diagnostics now report the temporary `silences` alongside the snoozes and the
  deferrals. The three per-row texts stay unredacted: they are configuration
  the user typed, and it is their *rendered* output that is redacted.
- A temporary silence that expired while the entry was unloaded is now written
  back to the store when it is purged at setup, instead of only being dropped
  from memory.

### Known limitations

Added to [`docs/known-issues.md`](docs/known-issues.md); everything listed
under 0.1.0 that is still open stays open.

- The five services are **callable by any Home Assistant user, by design**.
  The wall tablet runs under a non-admin account and its cards are the main
  caller; what bounds them is the ADR-0009 allow-list, not the caller's role.
  `context.user_id` is logged and carried in the `acknowledged`/`snoozed`
  events, and Companion buttons keep `authenticationRequired` on `high` and
  `critical` rows. Revisit if a household needs it — the shape would be a
  per-row flag, not a restriction on the whole domain.
- A deferral re-checks the person's silence at flush time but **not** the rest
  of the routing decision: somebody who left the audience, went away under a
  `home_only` rule or snoozed the row since still receives their queued
  message.

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

[Unreleased]: https://github.com/amiel-35/notify-switchboard/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/amiel-35/notify-switchboard/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/amiel-35/notify-switchboard/compare/v0.0.1...v0.1.0
