# Architecture

## The proxy model

Notify Switchboard never delivers a notification. It receives a request on
`notify.switchboard[_<slug>]` (or the `NotifyEntity`), decides which
already-existing `notify.*` services should receive it, and calls them. It
creates no channel of its own and no dependency on an external service.

```
             state that persists              one-off fact
                    |                               |
             binary_sensor.*                  event.* / automation
                    |                               |
                 alert.*  -- notifiers --> notify.switchboard_<slug> <-- notify.send_message
          (repeat, ack, done)                       |                     (entity, degraded)
        (or: observer mode watches alert.*)         |
                                                    v
                       routing table: target -> class, priority, alert.*, audience
                                                    |  per person:
                                                    |  in the audience?
                                                    |  present, if the rule requires it?
                                                    |  silenced (schedule / input_boolean read, never owned)?
                                                    |  priority that overrides? active snooze?
                                                    v
                notify.mobile_app_<person>   notify.<voice adapter>   notify.persistent_notification
                                |
                 "Acknowledge" / "Snooze" --> router --> alert.turn_off (allow-list) / stored snooze
```

Cards (a separate repository) read `alert.*` and this integration's own
entities. There is no intermediate "house" sensor.

## Modules

| Module | Role |
|---|---|
| `router.py` | **Pure**: routing table, decision engine, action ids. No `hass`. |
| `dispatcher.py` | Every side effect: service calls, buttons, callbacks, observer mode, deferrals, counters, repairs. |
| `store.py` | `Store`-backed snoozes, night deferrals and temporary silences. |
| `legacy.py` | `notify.switchboard` and `notify.switchboard_<slug>`. |
| `services.py` | The five `notify_switchboard.*` UI services (v0.2, ADR-0016): schemas and registration only, every decision delegated to `dispatcher.py`. |
| `notify.py` | The degraded `NotifyEntity`. |
| `entity.py`, `sensor.py`, `binary_sensor.py`, `event.py` | Contract §3.5 entities. |
| `config_flow.py`, `validation.py` | Options flow and its pure validation rules. |

The pure/impure split is what makes the decision engine unit-testable at 100 %
branch coverage without a `HomeAssistant` instance.

## Input contract

See `docs/contract.md` (frozen). In short: `message`, `title`, `target` (a list
of routing-table slugs), and `data` carrying `priority`, `source_entity`, `tag`
and anything else, which is merged over the row's `default_data` and forwarded
unchanged.

## Output contract

For every output of every selected person, the router calls
`notify.<output>` with `message`, `title` and the merged `data`.

Decisions taken in Sprint 1, where the contract left room:

- **Companion buttons are added only to outputs whose service name starts with
  `mobile_app_`.** Other outputs get the merged `data` without `actions` and
  without `authenticationRequired`.
- **`authenticationRequired` is written both at the top level of `data` and on
  each action.** The acceptance suite pins the top-level key; the per-action
  key is what the Companion app actually reads.
- **`not_in_audience` is recorded but not counted.** The decision lists every
  configured person a row does not name, so diagnostics can show why somebody
  was quiet, but `sensor.switchboard_dropped_today` ignores that reason: the
  contract says such a person is "not considered", and counting them would
  make the daily figure meaningless in a house with several people.
- **`unknown_person` is counted.** A row whose `audience` names somebody the
  persons table does not know about (a hand-edited `.storage`, a person
  deleted after the row was written) is a real loss: the row asked for that
  person to be notified and nobody was. It is a separate reason from
  `not_in_audience` and it counts towards `sensor.switchboard_dropped_today`.
- **A partially recursive output list still delivers.** If a person has one
  `switchboard_*` output and one real one, the real one is used and a
  `recursion` drop is recorded alongside.
- **A silenced message with a `wake_time` is deferred, not dropped**, and is
  therefore not counted as a drop. Deferrals are de-duplicated on
  `(person, target, tag)`; an untagged message de-duplicates on
  `(person, target)`.
- **Deferred deliveries re-check the silence, and nothing else.** `wake_time`
  is a *prediction* that the night is over, not a promise: a schedule that runs
  late, a `notify_switchboard.silence` set in the small hours or a restart
  spanning the night would otherwise push the whole queue at somebody still
  asleep. So `_async_flush_deferrals` re-reads `is_person_silenced` and keeps a
  still-silenced message queued, re-arming for whichever comes first, the end of
  the temporary silence or the next wake time (`_async_rearm_deferral`).
  `critical` is delivered regardless, as it is everywhere else. The rest of the
  decision — audience, presence, snooze — is **not** re-run: the queued message
  goes straight to the person's outputs. See `docs/known-issues.md`.
- **The next wake time is built from a date, never by adding 24 hours** to an
  aware datetime, so a message queued the night of a DST change fires at the
  right local hour (`dispatcher.next_wake_time`).
- **A deferral whose wake time passed while Home Assistant was down is
  delivered at the next setup.** Each `DeferredMessage` carries `queued_at`;
  at startup `Switchboard._async_catch_up_deferrals` compares
  `next_wake_time(queued_at, wake_time)` with `dt_util.now()` and flushes what
  is already late, instead of rescheduling it for the following day. The
  `(person, target, tag)` key still de-duplicates, so nothing is sent twice.
- **Snooze resolves the acting person from `context.user_id` first.** The
  Companion webhook re-fires the action event with the registration's own
  context (`homeassistant/components/mobile_app/webhook.py`,
  `webhook_fire_event` → `registration_context(config_entry.data)` →
  `Context(user_id=…)`), and a `person.*` entity publishes the user it is
  linked to as a `user_id` attribute
  (`homeassistant/components/person/const.py`,
  `PersonEntityStateAttribute.USER_ID`). If a person in the row's audience
  matches, only that person is snoozed.
  Failing that, the Companion `device_id` is looked up directly and as a
  `("mobile_app", <id>)` identifier; the device's name, its user-given name and
  its config entry's `device_name` are turned into a service name exactly the
  way core does it — `slugify(f"mobile_app_{name}")`,
  `homeassistant/components/notify/legacy.py` — and matched against the
  persons' outputs. When nothing matches — the documented ambiguous case —
  every person in the row's audience is snoozed.
- **Outputs are stored without their `notify.` prefix.** `parse_person`
  normalises `notify.mobile_app_x` to `mobile_app_x`, so the two spellings a
  user may reasonably write behave identically for person resolution, for
  Companion-button gating and for the recursion check.
- **An output that does not exist is tolerated three times** (load order) and
  raises one `repairs` issue on the fourth consecutive miss. An output that
  *does* exist but raises on every call feeds the same counter and the same
  issue: from the user's point of view it is just as unusable. Any successful
  call clears the counter (`Switchboard.failing_outputs`).
- **A delivery where every output failed is a drop, not a routed message.**
  `sensor.switchboard_routed_today` counts notifications that actually went
  out; when no output of a person accepted the call, the reason
  `delivery_failed` is counted on `sensor.switchboard_dropped_today` instead.
  One working output out of several is still a delivery.

## UI services (v0.2, ADR-0016)

A card, a script or an automation cannot originate a
`mobile_app_notification_action` event, so everything the Companion buttons do
is also a domain service: `notify_switchboard.acknowledge`, `snooze`,
`unsnooze`, `silence`, `unsilence`. They are registered with the config entry
and removed on unload, so a reload never leaves a service pointing at a dead
`Switchboard`; `manifest.json`'s `single_config_entry` is what makes one entry
owning the domain's services safe.

Decisions taken in Sprint 2, where the contract left room:

- **Validation lives in one place.** `Switchboard.acknowledge_is_allowed`,
  `_require_target`, `_require_person`, `_require_persons` and
  `_async_store_snooze` are shared by the Companion path and the services; the
  only difference is what each does with a refusal. The event handler logs and
  returns (nobody is listening); the service raises `ServiceValidationError`
  with a `translation_key` resolved from the `exceptions` section of
  `strings.json`.
- **The voluptuous schemas are strict about shape, permissive about value.**
  `homeassistant/core.py`, `ServiceRegistry.async_call`, re-raises a schema's
  `vol.Invalid` as-is, and a `vol.Invalid` is not a `ServiceValidationError`.
  So `minutes: 0`, a duration the row does not offer, an unknown slug and an
  unknown person are all checked in the handler, never in the schema.
- **A recurring refusal raises a `repairs` issue, and fixing the cause clears
  it.** One bad call is answered to its caller; the same unknown target or
  person refused `MAX_INVALID_SERVICE_CALLS` times is a card nobody fixed, and
  gets an issue — the same posture as `MAX_CONSECUTIVE_OUTPUT_MISSES`, with two
  differences that matter. The count is **cumulative, not consecutive**: three
  refusals a week apart raise the issue just as three in a row do, because a
  card wired to a stale slug fires whenever somebody taps it. And an issue
  outlives the refusals that raised it, so it is deleted explicitly — when the
  same slug or person is accepted again, and at setup for every slug and person
  the (reloaded) table now knows about, which is what an options-flow fix
  amounts to.
- **Only `MAX_TRACKED_INVALID_SERVICE_CALLS` distinct bad values are tracked.**
  A caller producing a fresh invalid value on every call — a template rendering
  to garbage — would otherwise grow the counter dict and the *persisted* issue
  registry without bound. Past the cap, no new per-value issue is raised and a
  single aggregated `invalid_service_calls_many` stands for the rest.
- **Bounded arithmetic on `silence(minutes:)`.** `MIN_SILENCE_MINUTES ≤ minutes
  ≤ MAX_SILENCE_MINUTES` (1 … 1440) is enforced in the handler. The lower bound
  is ADR-0016's rule; the upper one exists because
  `dt_util.utcnow() + timedelta(minutes=...)` raises `OverflowError` — a plain
  `Exception`, not a `HomeAssistantError` — once the result leaves `datetime`'s
  range, which would reach the caller as a crash rather than as the translated
  refusal ADR-0015 promises.
- **The caller's context is carried, but not into the authorisation.**
  `alert.turn_off` gets a **child** of the caller's `Context`, not the caller's
  own: a non-empty `context.user_id` on an entity service call makes
  `homeassistant/helpers/service.py` run an auth lookup and a per-entity
  permission check, which would put the row's `allow_acknowledge` allow-list
  behind whatever entity policy the calling account has. The logbook resolves
  the parent context for attribution
  (`homeassistant/components/logbook/processor.py`). The
  `event.switchboard_delivery` entity, whose state write runs no permission
  check, gets the caller's context directly.
- **The five services are callable by any user, on purpose.** The wall tablet
  runs under a non-admin account and its cards are the main caller; the
  allow-list, not the caller's role, is what bounds them. See the addendum to
  ADR-0016 and `docs/known-issues.md`.

### The two silence sources

`is_person_silenced` is an **OR** of two independent sources:

| Source | Owned by | Lifetime |
|---|---|---|
| the person's `silence_entities` (`schedule.*`, `input_boolean.*`, …) | the user — read, never written | whatever the entity says |
| a `notify_switchboard.silence` | the router | until its stored expiry |

Both produce the same `silenced` drop reason, both are bypassed by
`priority: critical`, and neither is aware of the other. Temporary silences
live in the same `Store` as snoozes (`person -> until`) and expire twice over:
lazily, in `build_context`, the way snoozes already do; and on an
`async_track_point_in_time` timer per person, so
`binary_sensor.<person>_silenced` returns to `off` at the minute the silence
lifts rather than at the next notification. That entity gains an `until`
attribute while a temporary silence runs; `sources` keeps its Sprint 1
meaning (the configured entities only).

Night deferral is deliberately **not** extended to temporary silence: a
message silenced only by a `notify_switchboard.silence` is dropped, because
`wake_time` is the end of the *night*, not the end of an hour of requested
quiet. When a configured night silence is also active, the message is deferred
as before — nothing is lost. A temporary silence still running when that
deferral comes due holds it back (both sources are read at flush time), and the
flush is then re-armed for the end of the silence.

### Per-row texts and the template context

`message`, `done_message` and `default_title` are optional per-row strings,
absent by default. The two templates are rendered with
`Template(raw, hass).async_render({"alert": <State|None>}, parse_result=False)`
(`homeassistant/helpers/template/__init__.py`): `alert` is the row's
`alert_entity`'s current `State`, or `None` when the row has no alert or the
entity does not exist, so a row can write `{{ alert.attributes.level }}`
without waiting for a real `AlertEntity` to gain state attributes. A template
that raises is logged and treated as absent; so is one that renders to an
empty string. `parse_result=False` keeps a message a string rather than
letting a numeric-looking render become an `int`.

Resolution order, unchanged when the new fields are absent:

| Transition | Order |
|---|---|
| `idle -> on` | alert's `message` attribute → row's `message` template → row's `name` |
| `on\|off -> idle` | row's `done_message` template → alert's `done_message` attribute → translated `common.back_to_normal` |
| title | caller's `title` → row's `default_title` → (observer mode only) row's `name` |

The two orders differ because the contract and ADR-0016 order them
differently; on a real `alert.*`, which exposes no attributes at all, both
chains behave identically. `default_title` is applied per delivery, in
`_async_deliver`, not per request, so a call fanned out over several rows gets
each row's own default.

## Why both a legacy service and an entity

Home Assistant's `alert` integration lists `notifiers:` by legacy `notify.*`
service name; there is no way to point `alert` at a `NotifyEntity`
(`homeassistant/components/notify/legacy.py`). So the legacy service is the
main entry point, and its `targets` property is what creates one
`notify.switchboard_<slug>` service per routing-table row. The `NotifyEntity`
is the forward-looking surface and is documented as degraded: `send_message`
carries only `message` and `title`, so it routes to the default row with
priority `normal`.

The legacy service is registered **directly** (`BaseNotificationService.
async_setup` + `async_register_services`) rather than through
`discovery.async_load_platform`. The discovery route can only be undone with
`notify.async_reset_platform`, which cancels the `notify` integration's global
discovery dispatcher — after which the service never comes back on a config
entry reload.

## Observer mode (plan B, ADR-007)

For a row with `observer_mode`, the router watches the row's `alert.*` instead
of waiting to be called:

| Transition | What is routed |
|---|---|
| `idle -> on` | the alert's `message` attribute, else the row's `message` template, else the row's name |
| `on\|off -> idle` | the row's `done_message` template, else the alert's `done_message` attribute, else the translated `common.back_to_normal` |
| `on -> off` | nothing (the alert was acknowledged) |

`AlertEntity` in core 2026.9.1 exposes **no** state attributes at all, so on a
real alert the row's own templates (v0.2, ADR-0016) are what actually fires
today; absent them, the fallbacks are. See "Per-row texts and the template
context" above.

## Entities

Per person (`<p>` = the object_id of the `person.*` entity):
`binary_sensor.<p>_silenced`, `sensor.<p>_last_notification`,
`sensor.<p>_active_snoozes`, each on a virtual device named after the person.
Globally: `sensor.switchboard_routed_today`,
`sensor.switchboard_dropped_today` (attribute `reasons`, a
`{reason: count}` dict), `sensor.switchboard_deferred_today` (attribute
`queued`, a `{person: [target, ...]}` dict) and `event.switchboard_delivery`
with the four frozen event types. `deferred_today` is an **additional**
diagnostic entity, allowed by contract §3.5; it exists because a deferral is
neither routed nor dropped and was therefore invisible.

Counters reset at local midnight (`homeassistant/helpers/event.py`,
`async_track_time_change`). They are `SensorStateClass.TOTAL` with an explicit
`last_reset` set to the current local midnight, not `TOTAL_INCREASING`:
`TOTAL_INCREASING` would read the daily reset as a meter rollover and
compensate for it, which is the opposite of what happens.

Config entries are not unloaded when Home Assistant stops, so every timer the
switchboard schedules is cancelled both on unload and on
`EVENT_HOMEASSISTANT_STOP`.

## Persistence

One `Store` (`notify_switchboard.data`, version 1, minor version 3) holds the
snoozes (`(person, target) -> expiry`, expired lazily), the night deferrals and
the temporary silences (`person -> until`, expired lazily too). Minor version 2
added `queued_at` to every deferral; the migration lives in
`store.SwitchboardStorage._async_migrate_func` and stamps the existing rows
with the migration time, so an upgrade never fires a backlog. Minor version 3
added the `silences` list, which starts empty: an upgrade never invents a
silence. Any row that will not parse is dropped rather than fatal — a
hand-edited `.storage` file must not stop the entry from loading. The recorder
database is never touched.

## Roadmap

Each increment ships something usable on its own; there is no fixed duration
per sprint.

| Suite # | Increment | Testable how |
|---|---|---|
| Suite S0 | Foundations: repo, template, CI, dev instance | CI green on the skeleton; `hassfest` passes |
| Suite S1 | Router v0.1: routing table, per-person decision, acknowledge / snooze buttons, night deferral, observer mode, diagnostics, config flow | A test alert routes to a present phone, not to an absent one; silence blocks unless `critical`; acknowledging from a phone stops the repeat; a 1 h snooze holds across a restart |
| Suite S2 | Router v0.2: five UI services (acknowledge/snooze/unsnooze/silence/unsilence), temporary person-wide silence, per-row `message`/`done_message`/`default_title` | A card silences somebody for an hour and the message is dropped, not lost; a snooze the row does not offer is refused with a translated error |
| Suite S3 | `notify-cast` v0.1: a `notify` per Cast speaker that talks | An announcement is heard in the kitchen |
| Suite S4 | `notify-airplay` v0.1: same for AirPlay speakers | An announcement is heard on an AirPlay speaker |
| Suite S5 | `notify-alexa` v0.1: same via Alexa Media Player | An announcement is heard on an Echo |
| Suite S6 | Cards v0.1: alert bubble, silence tiles | The wall shows active alerts and can acknowledge them |
| Suite S7 | Blueprints + docs site | An external user routes an alert in 10 minutes |
| Suite S8 | HACS default submission, quality scale silver | HACS acceptance |

This repository (`notify-switchboard`) covers the router rows; the others live
in sibling repositories per the umbrella doctrine. The quickstart
(`docs/quickstart.md`) and the three importable blueprints
(`blueprints/automation/notify_switchboard/`) landed early, ahead of the
suite S7 row that planned them.

### Router roadmap

The router has its own sprint sequence inside those rows, numbered
independently of the suite roadmap above: suite S3 is `notify-cast`, router S3
is this release, and the two S7 rows have nothing to do with each other.
**Router S3 is done** and is what 0.3.0 ships.

| Router # | Router increment | State |
|---|---|---|
| Router S0-S2 | Foundations, the router itself, the UI services and the per-row texts | Shipped (0.1.0, 0.2.0) |
| Router S3 | Debts and robustness: translated entity names with frozen ids, parallel fan-out with a per-output timeout, `person.user_id` as the canonical callback link, actions registered in `async_setup` (ADR-0017) | **Done — 0.3.0** |
| Router S4 | Zero-config: propose a routing table from the `person.*` entities and the `alert:` blocks that already exist, so a fresh install is useful before anything is typed | Next |
| Router S5 | Night: turn `wake_time` into a real quiet-hours model (per-person windows, a digest of what was deferred) rather than a single instant | Planned |
| Router S6 | Escalation: what happens when nobody acknowledges — a second person, a louder output, a delay per row | Planned |
| Router S7 | Places: route on where somebody is, not only on whether they are home | Planned |

## Engineering rules learned

Two operational lessons, orthogonal to any single architectural decision,
that reviews and incidents turned up during development. They are process
and engineering discipline rather than choices about the system's shape, so
they live here rather than in an ADR.

### Legacy `notify` platform lifecycle

Reviews of the suite's Cast and AirPlay voice adapters surfaced the same
class of bug twice, for the same underlying reason: Home Assistant core
never retires a legacy `notify.*` service on its own, and never
re-registers one that already exists (`homeassistant/components/notify/
legacy.py` returns early in that case). Any integration that registers a
legacy `notify` platform must therefore handle this itself:

1. Remove its own service in `entry.async_on_unload`, and clear its own
   entry out of `hass.data[NOTIFY_SERVICES]` — otherwise a config entry
   reload leaves the old service in place and its options never take
   effect.
2. Read the live config entry on every call; never capture options once at
   setup.
3. Guard any state shared across calls (volume, timers) with a per-target
   lock and `try`/`finally`, and cancel timers tied to the entry's
   lifecycle.
4. Validate `data` against a schema, normalising `source_entity`
   (`ensure_list`, cast to `str`, case-folded) and rejecting it outright if
   it cannot be used (see ADR-0015 for what "rejecting" means to the
   caller).
5. Expose one device per config entry, with a `translation_key` rather than
   a literal `_attr_name`.
6. Cover, in tests: an options reload, unload/remove, a failed delivery, an
   overlapping call, and a player already busy.

### One agent, one git worktree

Two agents must never share a working copy. On one occasion an agent
working on documentation switched the checked-out branch out from under an
orchestrating session that was mid-commit, which then had to untangle the
resulting history by hand. The rule since: only the orchestrating session
works in a repository's primary checkout, and only when no agent is
currently running against it; every agent — and the orchestrator itself,
for its own concurrent fixes — works in its own
`git worktree add <dir> -b <branch> origin/main`, never in a shared copy.

## ADR index

| ADR | Title |
|---|---|
| [0001](ADR/0001-native-first.md) | Native first |
| [0002](ADR/0002-pure-proxy.md) | The router is a pure notify proxy |
| [0003](ADR/0003-voice-is-a-separate-adapter.md) | Voice is a separate adapter, never wired to alerts by default |
| [0004](ADR/0004-notifier-hub-rejected-as-base.md) | Notifier Hub rejected as a base |
| [0005](ADR/0005-public-mit-translated.md) | Public repositories, MIT license, English source with fr/es UI |
| [0006](ADR/0006-sprints.md) | Sprints are testable increments, not time boxes |
| [0007](ADR/0007-legacy-notify-service-with-targets.md) | Legacy notify service with per-target `targets`, `NotifyEntity` degraded, observer mode as plan B |
| [0008](ADR/0008-alert-identity-via-target.md) | Alert identity travels through the target, not through `data` |
| [0009](ADR/0009-secure-notification-actions.md) | Secure notification actions — allow-list, authentication, audit |
| [0010](ADR/0010-voice-and-security-are-configuration-rules.md) | "Voice is not an alert" and "no security through voice" are configuration rules, not code guarantees |
| [0011](ADR/0011-frozen-contract-and-contract-test.md) | Frozen input contract and a contract test |
| [0012](ADR/0012-roadmap-reordered.md) | Roadmap reordered — acknowledge, cards and blueprints before voice |
| [0013](ADR/0013-source-unavailability-as-blueprint.md) | Source-unavailability monitoring ships as a blueprint, not in the router |
| [0014](ADR/0014-cast-notifier-name.md) | The Cast voice adapter is named "Cast Notifier" |
| [0015](ADR/0015-refusals-raise-service-validation-error.md) | A refused notification raises `ServiceValidationError`, never fails silently |
| [0016](ADR/0016-ui-services-and-row-texts.md) | UI services (acknowledge/snooze/silence) and per-row message texts |
| [0017](ADR/0017-debts-and-robustness.md) | Debts and robustness — frozen ids under any language, parallel fan-out, canonical callbacks, services without an entry |
