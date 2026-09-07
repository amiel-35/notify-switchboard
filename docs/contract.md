# Notify Switchboard — Public contract (v0.6 addendum, frozen per ADR-011 until 1.0 changes it)

> English, because it will move to `docs/contract.md` in the `notify-switchboard`
> repository and is guarded by a contract test. Any change requires an ADR.
>
> v0.2 addendum (ADR-0016): five new services (`acknowledge`, `snooze`,
> `unsnooze`, `silence`, `unsilence`) and three new optional per-row texts
> (`message`, `done_message`, `default_title`). Everything else below is the
> v0 text, unchanged.
>
> v0.3 addendum (ADR-0017): one more frozen name
> (`sensor.switchboard_deferred_today`), the fan-out guarantees, the callback
> resolution order, and the availability of the five services without a loaded
> entry. Everything above and below stays the v0 / v0.2 text, unchanged.
>
> v0.4 addendum (ADR-0018): one read-only service (`notify_switchboard.explain`)
> with its response keys, one optional routing-table row key (`managed`), two
> more `repairs` keys, and the tag carried by a test message. Everything above
> and below stays the v0 / v0.2 / v0.3 text, unchanged.
>
> v0.5 addendum (ADR-0019): two more drop reasons (`expired`, `not_notified`),
> one global option and `data` key (`ttl_minutes`), one optional per-person key
> (`summary`), one optional routing-table row key (`clear_done`), one more
> `data` key (`switchboard_done`), and the default `tag` / `notification_id` a
> message carries when the caller supplies none. The four
> `event.switchboard_delivery` event types are unchanged. Everything above and
> below stays the v0 / v0.2 / v0.3 / v0.4 text, unchanged.
>
> v0.6 addendum (ADR-0020): two more frozen entity names
> (`sensor.switchboard_acknowledgements`, `sensor.switchboard_routing_table`),
> two more drop reasons (`max_deliveries`, `below_min_priority`), five optional
> routing-table row keys (`escalate_when_nobody_home`,
> `escalation_after_minutes`, `escalation_audience`, `max_deliveries`,
> `require_authentication`), one optional per-person key (`min_priority`), one
> state attribute a silence entity may carry (`min_priority`), one more
> `explain` response key (`escalated`), and the payload of the `acknowledged`
> event. The four `event.switchboard_delivery` event types and the three
> `explain` `decision` values are unchanged. Everything above and below stays
> the v0 / v0.2 / v0.3 / v0.4 / v0.5 text, unchanged.

## Names (public, must not change without a major version)

| Item | Value |
|---|---|
| Integration domain | `notify_switchboard` |
| Legacy notify service (default target) | `notify.switchboard` |
| Per-target services (legacy `targets` property) | `notify.switchboard_<target>` where `<target>` is the slug of a routing-table row |
| Notify entity (degraded path) | `notify.switchboard` entity, `notify.send_message` with `message` + `title` only |
| Event entity | `event.switchboard_delivery` with fixed `event_types`: `routed`, `dropped`, `acknowledged`, `snoozed` |
| Per-person entities | `binary_sensor.<person>_silenced`, `sensor.<person>_last_notification`, `sensor.<person>_active_snoozes` (unique_id = `<entry_id>:<person entity_id>:<kind>`) |
| Global entities | `sensor.switchboard_routed_today`, `sensor.switchboard_dropped_today`, `sensor.switchboard_deferred_today` (v0.3, ADR-0017), `sensor.switchboard_acknowledgements`, `sensor.switchboard_routing_table` (v0.6, ADR-0020) |
| UI services (v0.2, ADR-0016) | `notify_switchboard.acknowledge`, `notify_switchboard.snooze`, `notify_switchboard.unsnooze`, `notify_switchboard.silence`, `notify_switchboard.unsilence` |
| Read-only service (v0.4, ADR-0018) | `notify_switchboard.explain` (`SupportsResponse.ONLY`) |

## Input (legacy service call)

```yaml
action: notify.switchboard_<target>      # or notify.switchboard with target: [<target>]
data:
  message: "text"                        # required
  title: "text"                          # optional
  target: ["<target>", ...]              # optional on the default service; ignored on per-target services
  data:
    priority: info | normal | high | critical   # optional; overrides the target's default
    source_entity: sensor.xyz                   # optional; origin entity (voice deny-lists, diagnostics)
    tag: "string"                               # optional; passed through, used for de-duplication
    # any other key is merged (caller wins) into the target's default `data` and passed to outputs
```

Rules:
- `priority: critical` is the only value that bypasses a person's silence.
- Unknown `<target>` → the call is dropped with reason `unknown_target` and a `repairs` issue is raised once.
- The routing table row identifies the originating `alert.*` (optional). Nothing about the alert is expected in `data` (ADR-008).

## Routing decision (per person in the target's audience)

1. Person not in audience → not considered.
2. Presence rule of the row (`always` | `home_only` | `away_only`) evaluated on the `person.*` state.
3. Silence: any configured `schedule` or `input_boolean` for that person is `on` → dropped with reason `silenced`, unless `priority == critical`.
4. Active snooze for (person, target) → dropped with reason `snoozed`, unless `priority == critical`.
5. Otherwise routed to every `notify.*` output configured for that person.

Dropped calls are counted and exposed with their reasons; nothing is silently lost.

## Output (per selected person and output service)

```yaml
action: notify.<output>
data:
  message: <message>
  title: <title>
  data: <merged data> + switchboard buttons (see below)
```

- A failing output never prevents other outputs or persons.
- Recursion: an output that resolves to `notify.switchboard*` is rejected at config time and at runtime.

## Buttons and callbacks (Companion)

- Buttons are added only when the row allows them: `acknowledge` (if the row has an `alert.*` and allows acknowledgement), `snooze_<minutes>` (durations from the row).
- Button labels come from the integration translations (`common.*`) in the Home Assistant language.
- `authenticationRequired: true` is set by default when the row's priority is `high` or `critical`.
- Callback: `mobile_app_notification_action` with `action: switchboard:<ack|snooze>:<target>:<minutes?>`.
  - Acknowledge → `alert.turn_off` on the row's `alert.*` **only if that alert is in the routing table** (allow-list); otherwise refused and logged with `context.user_id`.
  - Snooze → stored per (person, target) with an expiry; persisted with `Store`; survives restarts.

## UI services (v0.2, ADR-0016)

For callers other than a Companion action — a card, a script, an automation —
the same actions are exposed as domain services. Unlike the Companion
callback above (an event handler with nobody to answer to, which logs and
returns on a refused action), every one of these services raises
`ServiceValidationError` on a refused or invalid call.

| Service | Fields | Effect |
|---|---|---|
| `notify_switchboard.acknowledge` | `target` (slug, required) | Same allow-list as the Companion Acknowledge button (`alert.turn_off` on the row's `alert.*`, only if the row is in the table, has an `alert_entity`, and allows acknowledgement); refused otherwise. Logs `context.user_id`. |
| `notify_switchboard.snooze` | `target` (slug, required), `minutes` (int, required), `person` (optional `person.*`; default: every person in the row's audience) | Same effect as the Companion snooze buttons; `minutes` must be one of the row's `snooze_minutes`, refused otherwise. |
| `notify_switchboard.unsnooze` | `target` (slug, required), `person` (optional; default: every person in the row's audience) | Clears the matching stored snooze(s) immediately. |
| `notify_switchboard.silence` | `person` (required), `minutes` (positive integer, required, `>= 1`) | Sets a temporary, person-wide silence, independent of that person's configured `silence_entities` (never touched). `minutes: 0` is invalid. Exposed through `binary_sensor.<person>_silenced` and persisted; routing to that person is dropped with reason `silenced` unless `priority == critical`, exactly like configured silence. |
| `notify_switchboard.unsilence` | `person` (required) | Lifts a temporary silence set by `silence`, immediately. |

None of these services introduces a new `event.switchboard_delivery` event
type; the four types stay exactly as frozen above.

## Per-row texts (v0.2, ADR-0016)

Three optional fields on a routing-table row, all absent/`None` by default:

- `message` — a template rendered with the row's alert's current state
  exposed as `alert` (or `None` if there is no alert or it does not exist).
  Used by observer mode's `idle → on` transition when the alert itself does
  not already carry a `message` attribute; falls back to the row's `name`
  when neither is present.
- `done_message` — the same idea for the `on|off → idle` transition; falls
  back to the alert's own `done_message` attribute, then to the translated
  `common.back_to_normal`.
- `default_title` — used as the outgoing `title` whenever the caller (a
  legacy `notify.switchboard[_<slug>]` call, or an observer-mode-generated
  message, which never had a caller to supply one) does not provide one.

These exist because a core `alert.*` exposes no `message`/`done_message`
state attribute at all (`docs/known-issues.md`); the row, not the alert, is
now the documented source of this text.

## v0.3 addendum (ADR-0017)

### Names

`sensor.switchboard_deferred_today` is a frozen public name, alongside
`sensor.switchboard_routed_today` and `sensor.switchboard_dropped_today` (see
the table above). It counts the messages queued for a person's `wake_time`
since local midnight: a deferral is neither routed nor dropped, and nothing
else exposes it.

Entity **ids** are frozen in the English form listed in the names table, in
every instance language; the **friendly names** are translated into the
instance language. A `fr` or `es` instance therefore shows a translated name
on `sensor.switchboard_routed_today`, never a translated entity id.

### Fan-out guarantees

All (person, output) deliveries of one routing decision are attempted
**concurrently**, each bounded by a per-output timeout of 30 seconds.

- A timeout, a missing service or an exception on one output never delays and
  never prevents any other output, of the same person or of another.
- A failed or timed-out output is recorded exactly as a failed delivery
  already was: the same repair after several consecutive failures, and — when
  *every* output of a person failed — the same `delivery_failed` drop reason,
  the same `sensor.switchboard_dropped_today` increment and the same `dropped`
  `event.switchboard_delivery` payload. No new drop reason, no new event type.
- **Counts are promised; order is not.** The relative order of the
  `event.switchboard_delivery` events of one decision, and the order in which
  outputs are called, are unspecified.
- The wall time of one routing decision is bounded by its slowest single
  output, not by the sum of its outputs.

### Callback resolution order

For a `mobile_app_notification_action` callback, the acting person is resolved
in this order:

1. `context.user_id` matched against the `user_id` state attribute of a
   `person.*` in the row's audience. This is the canonical link and is used
   whenever it resolves, whatever the event's `device_id` says.
2. The event's `device_id`, looked up in the device registry — a fallback,
   logged at DEBUG as such.
3. Neither resolves: the action applies to every person in the row's audience,
   as already documented.

A person who is in the audience of a row that adds Companion buttons
(`allow_acknowledge`, or a non-empty `snooze_minutes`) and whose `person.*`
carries no `user_id` raises one `person_without_user_id` repair, deleted when
the link is made and the entry reloaded.

### Service availability

The five `notify_switchboard.*` services of v0.2 exist as soon as the
integration is set up, whether or not a config entry is loaded. Called while
no entry is loaded, each raises `ServiceValidationError` with the translation
key `no_loaded_entry`. Their fields, effects and refusals are otherwise
exactly as documented above.

### Per-row texts: the `done_message` order is the one written above

For the `on|off → idle` transition: the row's `done_message` template, then
the alert's own `done_message` attribute, then the translated
`common.back_to_normal` — in that order. (For `message`, on `idle → on`, the
alert's own attribute still comes first.) ADR-0017 settles a disagreement
between this document and two non-normative ones; this document is
authoritative.

## v0.4 addendum (ADR-0018)

### `notify_switchboard.explain` — a read-only service

A sixth `notify_switchboard.*` service, registered like the other five as soon
as the integration is set up (v0.3 §"Service availability" applies to it
unchanged: with no loaded entry it raises `ServiceValidationError` with the
translation key `no_loaded_entry`). It is declared
`SupportsResponse.ONLY`: it must be called with `return_response: true`, and
it answers rather than acts.

| Field | Required | Meaning |
|---|---|---|
| `target` | yes | a routing-table slug |
| `priority` | no | `info` / `normal` / `high` / `critical`; defaults to the row's `default_priority`, exactly as `data.priority` does on a real call |
| `person` | no | a `person.*`; defaults to the row's whole audience |

The response is a mapping with three keys — `target` (the slug evaluated),
`priority` (the effective priority) and `persons`, itself a mapping **keyed by
`person.*` entity id**. Each person's value has exactly these keys:

| Key | Type | Meaning |
|---|---|---|
| `decision` | `routed` \| `deferred` \| `dropped` | what would happen to a message sent right now |
| `until` | ISO 8601 string, or `null` | when the message would be delivered; populated for `deferred` and for nothing else |
| `reason` | string, or `null` | one of the drop reasons already frozen above; populated for `dropped` and for nothing else. No new drop reason is introduced |
| `detail` | string | a human-readable, translated sentence naming what decided: which silence entity is on, when a snooze lifts, the presence rule against the person's current state, the outputs a routed message would reach. Always present and non-empty |
| `outputs` | list of `notify.*` service names | the services this message would be handed to; empty when `decision` is `dropped` |
| `missing_outputs` | list of `notify.*` service names | outputs configured for that person that are not registered services; computed whatever the decision |

Rules:

- **`explain` is a pure evaluation.** It calls no `notify.*` service, changes
  none of `sensor.switchboard_routed_today` /
  `sensor.switchboard_dropped_today` / `sensor.switchboard_deferred_today`,
  fires no `event.switchboard_delivery`, queues no deferral and persists
  nothing.
- An unknown `target`, or a `person` the router does not know, raises
  `ServiceValidationError` exactly as the five acting services do
  (translation keys `unknown_target` / `unknown_person`).
- A **known** person who is simply not in the row's audience is not an error:
  the answer is `decision: dropped`, `reason: not_in_audience`.

### `managed` — one optional routing-table row key

A routing-table row may carry `managed: true`. It is absent (and therefore
false) on every row written before v0.4, and it changes nothing about routing.

- The router creates one such row, slug `default`, the first time a person is
  added while the routing table is empty, and points `default_target` at it.
- While `managed` is true, that row's `audience` is every configured person:
  adding a person adds them to it.
- Editing the row through the options flow — any field — clears `managed`
  permanently. Nothing sets it back to true.

### Two more `repairs` keys

Both are `is_fixable: false`, severity `warning`, translated, raised once and
deleted when their cause disappears, exactly like `person_without_user_id`
(v0.3):

| Translation key | Raised when |
|---|---|
| `person_without_outputs` | a person who is in the audience of at least one row has no `outputs` at all |
| `alert_entity_missing` | a row's `alert_entity` is still absent from the state machine 60 seconds after the config entry was set up |

### The test-message tag

A message sent by the options flow's "test this person" / "test this target"
steps travels the normal routing path — it is counted, evented, deferred or
dropped like any other message — and carries `data.tag: switchboard-test`.
That value is public: a caller, an automation or a Companion channel may rely
on it to tell a test from the real thing.

## v0.5 addendum (ADR-0019)

### Two more drop reasons

The reason list of §"Routing decision" gains exactly two values. The four
`event.switchboard_delivery` event types — `routed`, `dropped`,
`acknowledged`, `snoozed` — are **unchanged**; both new reasons travel in the
existing `dropped` event and in the `reasons` attribute of
`sensor.switchboard_dropped_today`, and both count towards it.

| Reason | Meaning |
|---|---|
| `expired` | a deferred message whose time-to-live had run out when its flush came (see below). It is removed from the queue and never delivered |
| `not_notified` | a `done` message for a person who received no message at all during the episode it closes (see below) |

### `ttl_minutes` — a global option and a `data` key

`entry.options["ttl_minutes"]` is an optional mapping from priority to a
number of minutes, or `null` for "never expires":

```yaml
ttl_minutes:
  info: 120       # default
  normal: 720     # default
  high: null      # default
```

The mapping and each of its keys are optional; an absent value means the
default above. `critical` has no entry: a critical message is never deferred,
so it can never expire.

`data.ttl_minutes` on a call overrides the mapping for that message. The value
is a number of minutes; `0` means **this message never expires**.

A time-to-live applies to a **deferred** message and to nothing else. It is
evaluated at each flush (the wake-time flush, the early flush below, and the
catch-up flush after a restart) against the instant the message was queued;
when it has run out the message is dropped with reason `expired`.

### The wake-time summary, and the `summary` per-person key

A person row may carry `summary: false`; absent means `true`.

When more than one deferred message survives for a person at a flush — after
the expired ones and the ones the re-decision drops have been removed — and
that person's `summary` is on, they are delivered **one** notification per
output instead of one per message:

- `title`: the translated `common.summary_title`, carrying the number of lines
  as `{count}`;
- `message`: one line per surviving message, newest last, `\n`-joined;
- messages sharing a `tag` are collapsed to the last one, across rows;
- `data`: only the switchboard's own keys — `tag: switchboard-summary`,
  `notification_id: switchboard-summary` for the `persistent_notification`
  output, and the union of any `switchboard_*` keys of the collapsed
  survivors. No caller key, no row `default_data`, and **no Companion
  buttons**: neither `actions` nor `authenticationRequired`.

With `summary: false`, or with exactly one surviving message, the message is
delivered exactly as before: its own text, title, merged `data` and buttons.

A summary counts **one routed delivery per line**, not one per notification
and not one per queued message: what `sensor.switchboard_routed_today` reports
is what a person reads.

### A deferred message is re-decided in full at its flush

A flush re-runs the whole routing decision — audience, presence rule, snooze,
silence — against the world as it is at that moment, using the message's
**original** priority.

- Still routed: delivered (alone, or as one line of the summary).
- Dropped with reason `silenced`: kept queued and re-armed, as before.
- Dropped with any other reason: dropped for real, with that reason.

### An early flush when the silence ends

When the last of a person's configured `silence_entities` turns `off` and no
temporary `notify_switchboard.silence` is running for them, their deferred
messages are flushed immediately. `wake_time` remains the upper bound: nothing
waits longer than it did before.

### Episodes and the `done` message

An **episode** is one run of a routing-table row's `alert_entity`, from that
entity's `idle → on` transition to its `→ idle` transition. Episodes exist for
every row that names an `alert_entity`, in observer mode or not. For each one
the router remembers which persons actually received at least one of its
messages, and which outputs were called. The record survives a restart.

A **`done` message** — observer mode's `on|off → idle` message, or any call
carrying `data.switchboard_done: true` — reaches only the persons in that set.
Every other person in the row's audience is dropped with reason
`not_notified`. A row with no `alert_entity` has no episodes, so a
`switchboard_done: true` message on it is routed to the whole audience like
any other.

### The default `tag` and `notification_id`

Every outgoing message carries a deterministic identity when the caller gives
none:

| Message | default `data.tag` |
|---|---|
| any message on row `<slug>` | `switchboard-<slug>` |
| the `done` message of row `<slug>` | `switchboard-<slug>-done` |
| a wake-time summary | `switchboard-summary` |

`data.notification_id` defaults to the message's effective `tag` and is added
for the `persistent_notification` output only. A caller-supplied `tag` or
`notification_id` always wins.

### Closing an episode on the channels it used

This tidying-up applies to a row in **observer mode** only — the case where
the router is itself what announces the end; a row driven by its alert's own
`notifiers:` list sends its "back to normal" before the state reaches `idle`
(core's `end_alerting`), so clearing there would wipe the message that just
arrived. Episodes themselves, and the `not_notified` filter above, exist for
every row with an `alert_entity` either way.

When a row's `alert_entity` returns to `idle`, after the `done` message has
been routed:

- every `mobile_app_*` output that received a message of the episode is called
  with `message: clear_notification` and `data.tag` set to a tag the episode's
  messages carried — one call per such tag, which is one call in the ordinary
  case where nobody overrode `data.tag`;
- if the `persistent_notification` output received one,
  `persistent_notification.dismiss` is called with the matching
  `notification_id`;
- if the row carries the new optional key **`clear_done: true`** (absent means
  false), the `done` message itself is cleared the same way, on the
  `mobile_app_*` outputs that received it.

A clear is **not a message**: it is not counted, it fires no
`event.switchboard_delivery`, and it is subject to no routing rule.

## v0.6 addendum (ADR-0020)

Everything in this block is evaluated **at decision time**, from entities and
records that already exist. The router owns no timer and no counter of its own
for escalation; the only clock is the core `alert`'s own `repeat`. That is an
invariant of the design, not an implementation note, and §"Escalation after N
minutes" below states the granularity it costs.

### Two more frozen entity names

| Entity | State | Attributes |
|---|---|---|
| `sensor.switchboard_acknowledgements` | number of acknowledgements since local midnight | `last`, `by_target` |
| `sensor.switchboard_routing_table` | number of routing-table rows | `targets`, `persons` |

Both are global entities, in the frozen English form, in every instance
language (v0.3 §"Names" applies to them unchanged).

### Two more drop reasons

The reason list of §"Routing decision" gains exactly two values. The four
`event.switchboard_delivery` event types are **unchanged**; both new reasons
travel in the existing `dropped` event and in the `reasons` attribute of
`sensor.switchboard_dropped_today`, and both count towards it.

| Reason | Meaning |
|---|---|
| `max_deliveries` | this person has already received the row's `max_deliveries` deliveries during the current episode |
| `below_min_priority` | the call's effective priority is below this person's `min_priority` floor |

### New routing-table row keys

All five are optional and absent by default, so every row written before 0.6.0
keeps the exact dict it had and behaves exactly as it did.

| Key | Type | Default | Meaning |
|---|---|---|---|
| `escalate_when_nobody_home` | bool | `false` | see below |
| `escalation_after_minutes` | int > 0 | absent | see below; required together with `escalation_audience` |
| `escalation_audience` | list of `person.*` | absent | required together with `escalation_after_minutes` |
| `max_deliveries` | int > 0 | absent | see below |
| `require_authentication` | bool or `null` | `null` | see below |

### New per-person key

| Key | Type | Default | Meaning |
|---|---|---|---|
| `min_priority` | `info` / `normal` / `high` / `critical` | `info` | calls below it are dropped with reason `below_min_priority` |

Priorities rank `info < normal < high < critical`.

### `escalate_when_nobody_home`

At decision time, when the row carries `escalate_when_nobody_home: true` and
**no** person of the row's effective audience is in state `home`, the call's
priority becomes `critical` **for this decision only**: it bypasses silence and
snooze exactly as a caller-supplied `critical` does. The row's
`default_priority` and the caller's `data.priority` are not modified, and the
next call re-evaluates the question.

Only the literal state `home` counts as home; a named zone, `not_home`,
`unknown`, `unavailable` and an unknown entity all count as "not home". The
row's presence rule is unaffected — a `home_only` row with nobody home still
drops everybody with reason `presence`. An empty effective audience escalates
nothing.

### Escalation after N minutes

For a row that names an `alert_entity` and carries both
`escalation_after_minutes` and `escalation_audience`: when a call arrives, the
row's current episode has a known start at least that many minutes in the past,
and the row's `alert_entity` is in state `on` right now, then for that decision
only:

- `escalation_audience` is **added** to the row's audience. The added persons
  are ordinary members of the effective audience — presence, floor, silence,
  snooze and `max_deliveries` all apply to them — and they are not reported
  `not_in_audience`.
- the priority is raised **one step**: `normal → high`, `high → critical`.
  `info` and `critical` are unchanged.

"Still `on`" is the acknowledgement check: an acknowledged alert reads `off`,
so it does not escalate.

**Granularity.** The router is called when the alert calls it, so the
escalation happens at the **first repeat after N minutes** and the effective
delay is `N` rounded **up** to the alert's repeat interval. An alert with
`repeat: [15]` and `escalation_after_minutes: 20` escalates at 30 minutes.

### `max_deliveries`

Per **episode and person**: once that many routed deliveries of the row have
reached a person during the current episode, the next ones are dropped with
reason `max_deliveries`. A delivery is the unit
`sensor.switchboard_routed_today` already counts — one (person, target) pair
that reached at least one output.

- The count resets with the episode: a new episode starts every person's count
  at zero.
- A row with no `alert_entity` has no episodes, so the key is inert on it.
- A `done` message is never counted and is always allowed, whatever the cap.
  §"Episodes and the `done` message" (v0.5) still applies to it unchanged.
- `critical` does **not** bypass the cap. It bypasses a person's silence and
  snooze, not a bound the household put on a row.
- The cap is evaluated after presence, the priority floor, silence and snooze,
  so a delivery dropped for another reason keeps that reason and does not
  consume the budget.

### Priority floors

A call whose effective priority is below a person's `min_priority` is dropped
for that person with reason `below_min_priority`. The floor is evaluated after
the presence rule and before silence and snooze. `critical` is the top of the
rank, so it is never below a floor.

A silence entity that is `on` **and** carries a `min_priority` state attribute
silences only the calls **below** that value, with the existing reason
`silenced`; calls at or above it pass. A silence entity that is `on` and
carries no such attribute silences everything, as before. The documented way to
produce the attribute is a core `schedule` whose active block carries
`data: {min_priority: <p>}`:

```yaml
schedule:
  night:
    monday:
      - from: "22:30:00"
        to: "07:00:00"
        data:
          min_priority: high
```

A `min_priority` attribute whose value is not one of the four priorities is
ignored and the entity silences everything: a typo fails towards quiet.

### `require_authentication`

Governs the `authenticationRequired` flag on the row's Companion buttons, and
nothing else. `null` (or absent) is the rule of §"Buttons and callbacks",
unchanged: set when the message's effective priority is `high` or `critical`.
`true` always sets it; `false` never does. The effective priority a `null` row
reads is the escalated one.

It is not an authorisation decision: the ADR-0009 allow-list remains the only
thing that decides whether a row can be acknowledged at all.

### `explain` gains one response key

The response of `notify_switchboard.explain` is a mapping with **four** keys:
`target`, `priority`, `persons` and the new `escalated`.

| Value of `escalated` | Meaning |
|---|---|
| `null` | nothing escalated this decision |
| `"nobody_home"` | the `escalate_when_nobody_home` rule fired |
| `"after_minutes"` | the escalation-after-N-minutes rule fired |

`priority` reports the escalated priority and `persons` covers the effective
audience, escalation audience included. `escalated` is populated only when a
rule actually changed the decision — a raised priority, a widened audience, or
both; a rule whose condition holds but which would change nothing leaves it
`null`. When both rules fire, `escalated` is `"nobody_home"`.

The per-person keys are unchanged, and so are the three `decision` values; the
two new drop reasons travel in the existing `reason` key, and `detail` names
the floor or the cap that decided. `explain` remains a pure evaluation: it
consumes no `max_deliveries` budget and writes nothing.

### The `acknowledged` event payload

The payload of the `acknowledged` `event.switchboard_delivery` event is frozen
as:

```yaml
target: leak                 # the routing-table slug
alert_entity: alert.leak     # the row's alert
user_id: "01J..."            # the acting Home Assistant user, or null
person: person.alice         # that user's `person.*`, or null
```

`person` is resolved through the canonical link only — the `user_id` state
attribute of a `person.*`, step 1 of v0.3 §"Callback resolution order". The
`device_id` fallback is not used for authorship: `person` is `null` rather than
a guess.

### Acknowledgement records

Every acknowledgement that actually happens — through the Companion button or
through `notify_switchboard.acknowledge`, once the ADR-0009 allow-list has said
yes — is recorded as:

```yaml
target: leak
person: person.alice   # or null
user_id: "01J..."      # or null
at: "2026-09-07T03:12:44+00:00"
```

`sensor.switchboard_acknowledgements` exposes them: its **state** is the number
of records since local midnight, its `last` attribute is the most recent record
(or `null`), and its `by_target` attribute maps each row slug to that row's most
recent record. Only the state resets at local midnight; `last` and `by_target`
survive the reset, a reload and a restart, because the records are persisted.

A refused acknowledgement records nothing.

### `sensor.switchboard_routing_table`

Its state is the number of routing-table rows. Its two attributes are:

```yaml
targets:
  - slug: leak
    name: Fuite d'eau
    alert_entity: alert.leak        # or null
    snooze_minutes: [15, 60]
    allow_acknowledge: true
    audience: [person.alice, person.bob]
persons:
  - entity_id: person.alice
    wake_time: "07:00:00"           # or null
    summary: true
```

`targets` follows the order of the routing table and `persons` that of the
person rows. `wake_time` is the `"HH:MM:SS"` string the options carry.

The two lists carry **exactly** the keys shown. In particular the entity never
exposes `default_data` — the one row key that carries whatever the user put in
it, and therefore the one where a secret ends up — and it exposes no person
`outputs`. Nothing else is added to either list without a new ADR.

## Observer mode (plan B, ADR-007)

When enabled on a row, the router subscribes to the row's `alert.*` state and routes on `idle → on` (message from the row), routes the `done` message on `on|off → idle`, and stops on `on → off`. In this mode the alert does not need to list the router in `notifiers`.

## What this contract does not promise

- No voice, no calls, no external network: outputs are whatever `notify.*` services exist.
- The `NotifyEntity` path carries only `message` and `title` (Home Assistant limitation).
- Text of routed messages is not translated; only router-added labels are.
