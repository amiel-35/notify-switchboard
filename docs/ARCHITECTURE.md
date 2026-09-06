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
| `store.py` | `Store`-backed snoozes and night deferrals. |
| `legacy.py` | `notify.switchboard` and `notify.switchboard_<slug>`. |
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
- **Deferred deliveries do not re-run the decision.** `wake_time` is by
  definition the end of the night silence, so the queued message is handed
  straight to the person's outputs.
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
| `idle -> on` | the alert's `message` attribute, else the row's name |
| `on\|off -> idle` | the alert's `done_message` attribute, else the translated `common.back_to_normal` |
| `on -> off` | nothing (the alert was acknowledged) |

`AlertEntity` in core 2026.9.1 exposes **no** state attributes at all, so on a
real alert both fallbacks are what actually fires today. See
`docs/known-issues.md`.

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

One `Store` (`notify_switchboard.data`, version 1, minor version 2) holds the
snoozes (`(person, target) -> expiry`, expired lazily) and the night
deferrals. Minor version 2 added `queued_at` to every deferral; the migration
lives in `store.SwitchboardStorage._async_migrate_func` and stamps the
existing rows with the migration time, so an upgrade never fires a backlog.
The recorder database is never touched.

## Roadmap

Each increment ships something usable on its own; there is no fixed duration
per sprint.

| # | Increment | Testable how |
|---|---|---|
| S0 | Foundations: repo, template, CI, dev instance | CI green on the skeleton; `hassfest` passes |
| S1 | Router v0.1: routing table, per-person decision, acknowledge / snooze buttons, night deferral, observer mode, diagnostics, config flow | A test alert routes to a present phone, not to an absent one; silence blocks unless `critical`; acknowledging from a phone stops the repeat; a 1 h snooze holds across a restart |
| S2 | Router v0.2: per-class snooze bounds, burst windows, escalation | A burst of ten leaks becomes one notification |
| S3 | `notify-cast` v0.1: a `notify` per Cast speaker that talks | An announcement is heard in the kitchen |
| S4 | `notify-airplay` v0.1: same for AirPlay speakers | An announcement is heard on an AirPlay speaker |
| S5 | `notify-alexa` v0.1: same via Alexa Media Player | An announcement is heard on an Echo |
| S6 | Cards v0.1: alert bubble, silence tiles | The wall shows active alerts and can acknowledge them |
| S7 | Blueprints + docs site | An external user routes an alert in 10 minutes |
| S8 | HACS default submission, quality scale silver | HACS acceptance |

This repository (`notify-switchboard`) covers S0/S1/S2 of the router; the
other rows live in sibling repositories per the umbrella doctrine.

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
