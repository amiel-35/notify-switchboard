# Notify Switchboard — Public contract (v0.7 addendum, frozen per ADR-011 until 1.0 changes it)

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
> `data` key (`switchboard_done`), and the default `tag` a
> message carries on Companion outputs when the caller supplies none, with
> `notification_id` on `persistent_notification`; other outputs receive the
> caller's data only. The four
> `event.switchboard_delivery` event types are unchanged. Everything above and
> below stays the v0 / v0.2 / v0.3 / v0.4 text, unchanged.
>
> v0.6 addendum (ADR-0020): `class` leaves the routing-table row keys (a
> stored one is ignored), `wake_time` becomes optional with a documented
> meaning when it is absent, the `ttl_minutes` defaults are reclassified as
> defaults a minor version may change, and four options-flow step ids become
> public names. Nothing is added and no routing rule changes. Everything
> above and below stays the v0 / v0.2 / v0.3 / v0.4 / v0.5 text, unchanged.
>
> v0.7 addendum (ADR-0021): one more frozen entity name
> (`sensor.switchboard_routing_table`), one optional target key
> (`escalate_when_nobody_home`), one global option (`critical_payload`), the
> `min_priority` state attribute a silence entity may carry, two `explain`
> top-level keys (`escalated`, `outputs`), two `acknowledged` payload keys
> (`user_id`, `person`), audience entries that are `notify.*` service names and
> outputs that are `notify.*` entity ids — and one **removal**:
> `data.priority` no longer reaches a `mobile_app_*` output. No service, no
> drop reason and no `event.switchboard_delivery` type is added. Everything
> above and below stays the v0 / v0.2 / v0.3 / v0.4 / v0.5 / v0.6 text,
> unchanged.

## Names (public, must not change without a major version)

| Item | Value |
|---|---|
| Integration domain | `notify_switchboard` |
| Legacy notify service (default target) | `notify.switchboard` |
| Per-target services (legacy `targets` property) | `notify.switchboard_<target>` where `<target>` is the slug of a routing-table row |
| Notify entity (degraded path) | `notify.switchboard` entity, `notify.send_message` with `message` + `title` only |
| Event entity | `event.switchboard_delivery` with fixed `event_types`: `routed`, `dropped`, `acknowledged`, `snoozed` |
| Per-person entities | `binary_sensor.<person>_silenced`, `sensor.<person>_last_notification`, `sensor.<person>_active_snoozes` (unique_id = `<entry_id>:<person entity_id>:<kind>`) |
| Global entities | `sensor.switchboard_routed_today`, `sensor.switchboard_dropped_today`, `sensor.switchboard_deferred_today` (v0.3, ADR-0017) |
| UI services (v0.2, ADR-0016) | `notify_switchboard.acknowledge`, `notify_switchboard.snooze`, `notify_switchboard.unsnooze`, `notify_switchboard.silence`, `notify_switchboard.unsilence` |
| Read-only service (v0.4, ADR-0018) | `notify_switchboard.explain` (`SupportsResponse.ONLY`) |
| Routing-table entity (v0.7, ADR-0021) | `sensor.switchboard_routing_table` |

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

These defaults are keys the **router** adds, so they only reach the outputs
that read them:

- the default `tag` is added on `mobile_app_*` outputs, and on the bare
  `persistent_notification` output, where it is the source of the id below;
- `data.notification_id` defaults to the message's effective `tag` and is added
  for the `persistent_notification` output only;
- `actions` and `authenticationRequired` are added on `mobile_app_*` outputs
  only, as they always have been.

Every other output receives exactly the caller's `data` merged with the row's
`default_data`, and nothing the router added: the router is a proxy
(ADR-0002), and an output that validates its `data` must not be forced to
tolerate keys it never asked for.

A caller-supplied `tag` or `notification_id` always wins and, being the
caller's own key rather than one the router invented, reaches every output.

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

This addendum **removes** one thing, **relaxes** one thing, **reclassifies**
one thing and **freezes** four names. It adds no service, no entity, no `data`
key, no drop reason and no `event.switchboard_delivery` type.

### `class` is no longer a routing-table row key

A routing-table row has no `class`. The key was never part of this document,
was never read by the router and was never exposed anywhere; from 0.6.0 it is
not written, not offered in the options flow, and **ignored** when a stored
row still carries one — never migrated, never shown, never deleted. It is also
stripped from the routing table a diagnostics dump exposes, so it cannot be
mistaken for something the router reads.

Removing it is not a breaking change: nothing may have depended on it, because
nothing ever read it back.

### `wake_time` is optional, and its absence has a meaning

`wake_time` is an optional key of a person row, as it always was. What v0.6
adds is the documented behaviour when it is **absent**:

| The person is silenced by | With a `wake_time` | Without a `wake_time` |
|---|---|---|
| a configured silence entity that publishes its own end (`schedule.*`, whose `next_event` attribute holds the end of the current block) | deferred until the wake time, flushed early when the last silence lifts (v0.5 §4) | **deferred until that end**, flushed by the same early flush |
| a configured silence entity that publishes no end (`input_boolean.*`, a Companion Focus `binary_sensor.*`) | deferred until the wake time | dropped with reason `silenced`, as in v0.1 → v0.5 |
| a temporary `notify_switchboard.silence` only | dropped with reason `silenced` | dropped with reason `silenced` |

A deferral made this way is a deferral like any other: it counts towards
`sensor.switchboard_deferred_today`, it is subject to `ttl_minutes`, it is
re-decided in full at its flush (v0.5 §3), it can be summarised (v0.5 §2), and
it is caught up after a restart. `explain` reports it as `decision: deferred`
with `until` set to that end — `until` keeps its frozen meaning of a real
instant, which is why the rule is scoped to silences that have one.

`priority: critical` still bypasses silence everywhere, so a critical message
is never deferred and never expires.

### The `ttl_minutes` defaults are defaults, not frozen values

The three values of v0.5 — `info` 120, `normal` 720, `high` `null` — are
**documented defaults that a minor version may change**. They are not part of
the frozen surface and no caller may rely on a particular number.

What *is* frozen is the mechanism, unchanged from v0.5: the option
`entry.options["ttl_minutes"]`, the per-call `data.ttl_minutes` override, the
meaning of `null`/absent ("never expires"), the meaning of `0` on a call
("this message never expires"), the absence of a `critical` entry, and the
`expired` drop reason. A household that needs a specific number states it;
the options flow always shows the values in force.

### Four options-flow step ids are public

Documentation, cards and support answers link to a Home Assistant options step
by its id. These four may not be renamed without an ADR:

| Step id | What it holds |
|---|---|
| `target` | the five fields that create a target: `slug`, `name`, `alert_entity`, `audience`, `observer_mode` |
| `target_advanced` | everything else on a target: `default_priority`, `presence_rule`, `allow_acknowledge`, `snooze_minutes`, `default_data`, `message`, `done_message`, `default_title`, `clear_done` |
| `person_outputs` | a person's `outputs` and `silence_entities` |
| `person_advanced` | a person's `wake_time` and `summary` |

Defaults are unchanged by the split, and the step a field lives in is the only
thing that moved: a target created through `target` alone is exactly the row
v0.5 wrote for the same five answers, minus `class`.

Steps not listed here — including the `target_saved` confirmation and the
pickers that lead to the advanced steps — are internal and may change.

### One word per concept

In every user-facing string, error message and document, a row of the routing
table is a **target**. The `target:` list of the legacy `notify.switchboard`
call is spelled "the notify `target` list" wherever it has to be distinguished
from it. A `person.*` is a **person**. `README.md` carries the glossary the
other documents link to.

## v0.7 addendum (ADR-0021)

This addendum **adds** one entity, one target key, one global option, one state
attribute the router reads, two `explain` keys, two `acknowledged` payload keys
and two new kinds of output — and **removes one thing** from what a Companion
output receives. The removal is stated on its own below, because it is the only
breaking change of 0.7.0. No service is added, no drop reason is added, and the
four `event.switchboard_delivery` types are unchanged.

### One more frozen name

`sensor.switchboard_routing_table` joins the frozen names table above, alongside
`sensor.switchboard_routed_today`, `sensor.switchboard_dropped_today` and
`sensor.switchboard_deferred_today`. Like them, its **entity id** is frozen in
the English form on an instance of any language; only its friendly name is
translated (v0.3 §"Names").

### `escalate_when_nobody_home` — one optional target key

A target may carry `escalate_when_nobody_home: true`. It is absent (and
therefore false) on every target written before 0.7.0.

When it is true and **no** person of the target's audience is in the literal
state `home` at decision time, the call's priority is raised **one step**, for
that decision only:

| From | To |
|---|---|
| `info` | `normal` |
| `normal` | `high` |
| `high` | `critical` |
| `critical` | `critical` (unchanged) |

The target's `default_priority` and the caller's `data.priority` are not
changed; the next call re-evaluates the question from scratch.

- Anything that is not the string `home` — a named zone, `not_home`, `unknown`,
  `unavailable`, a person the state machine has never heard of — counts as "not
  home".
- Bare outputs (below) have no presence and are never asked; a target whose
  audience holds no person escalates nothing.
- The presence rule is untouched. A `home_only` target with nobody home drops
  every person with reason `presence`, escalated or not.
- The escalated priority is the effective one everywhere downstream: the
  silence and snooze bypass, `authenticationRequired`, the `priority` of the
  `routed` event, and the critical payload below.

### A scheduled priority floor: the `min_priority` state attribute

A person's configured silence entity that is `on` **and** whose state
attributes carry `min_priority` silences only the calls **below** that value;
calls at or above it pass. The rank is `info < normal < high < critical`.

- The drop reason is the existing `silenced`. No reason is added.
- A silence entity that is `on` and carries no such attribute silences
  everything, as before.
- A `min_priority` whose value is not one of the four priority strings is
  ignored and the entity silences everything: an unreadable floor fails towards
  quiet.
- When several of a person's silence entities are `on`, the strictest decides:
  the person is silenced when any of them would silence this call.
- A temporary `notify_switchboard.silence` carries no floor and silences
  everything.
- A floor changes **which** calls a silence catches, not what happens to a
  caught call: it is still dropped with `silenced`, or deferred to a wake time
  or to the silence's own published end (v0.6), re-decided at its flush and
  summarised, exactly as before.
- `priority: critical` still bypasses every silence, floor or no floor.

The documented way to publish the attribute is a core `schedule`, whose active
block's `data:` becomes state attributes:

```yaml
schedule:
  night:
    monday:
      - from: "22:30:00"
        to: "07:00:00"
        data:
          min_priority: high
```

Any entity that is `on` and exposes the attribute is read the same way; the
router reads the attribute, never the domain.

There is no per-person `min_priority` option.

### `sensor.switchboard_routing_table`

Its **state** is the number of targets. It carries exactly two attributes:

| Attribute | Contents |
|---|---|
| `targets` | one entry per target, in the order of the routing table, with exactly the keys `slug`, `name`, `alert_entity`, `snooze_minutes`, `allow_acknowledge`, `audience` |
| `persons` | one entry per configured person, in options order, with exactly the keys `entity_id`, `wake_time`, `summary` |

`alert_entity` and `wake_time` are `null` when the row has none, never absent.
`wake_time` is the `"HH:MM:SS"` string the options carry. `audience` is
reported verbatim, bare outputs included.

Both lists are **closed**: nothing is added to either without an ADR. In
particular the entity never exposes `default_data` — the one target key that
carries whatever the user put in it — and never exposes a person's `outputs`.
A caller that needs to know what *would* happen has
`notify_switchboard.explain`.

Both attributes are excluded from the recorder: they are configuration, they
change only on an options edit, and their history is not worth a database row
per state write.

### The `acknowledged` event payload

The `acknowledged` `event.switchboard_delivery` payload carries `user_id` and
`person` alongside the `target` and `alert_entity` it already carried.

- `user_id` is the acting `context.user_id` — the service call's, or the
  Companion callback event's — or `null`.
- `person` is that user resolved through the **canonical** link only: the
  `user_id` state attribute of a `person.*` (v0.3 §"Callback resolution order",
  step 1). It is `null` when that does not resolve. The `device_id` fallback of
  step 2 is deliberately not used for authorship.

No entity and no stored record exposes acknowledgement authorship: the event is
where it lives.

### Bare outputs: an audience entry that is a `notify.*` service

An entry of a target's `audience` may be a `notify.*` **service name** instead
of a `person.*` entity id. The domain tells the two apart, and nothing else.

A bare output has:

- no presence, so no presence rule and no part in `escalate_when_nobody_home`;
- no silence, no snooze, no deferral, no time-to-live, no wake time, no
  summary — it is delivered now or it is not delivered;
- no Companion buttons, no `authenticationRequired`, no `notification_id` and
  no router-added `tag`. It receives exactly the caller's `data` merged with
  the target's `default_data`, and nothing the router invented.

It does take part in **episodes**: a bare output that received a message of an
episode receives that episode's `done` message, and one that did not is dropped
with `not_notified`, exactly like a person.

A delivered bare output is one routed delivery — counted in
`sensor.switchboard_routed_today`, reported in a `routed`
`event.switchboard_delivery` whose `person` key is `null`. One that does not
exist, times out or raises is a `delivery_failed` drop, with the same
consecutive-failure repair as a person's output. A bare output resolving to
`notify.switchboard*` is refused with the existing `recursion` reason, at
config time and at runtime.

No drop reason and no event type is added for any of this.

### Entity outputs: an output that is a `notify.*` entity id

An output — a person's, or a bare one — that is a `notify` **entity id** is
delivered with `notify.send_message`, carrying `message` and `title`.

- **Resolution order: a registered legacy service first, then an entity.** A
  legacy notify service and a notify entity share one namespace; an output that
  is a registered service is called as one, exactly as before, and only an
  output that is not becomes an entity call.
- **`data` is not carried.** `notify.send_message` accepts `message` and
  `title` and nothing else, so a target's `default_data`, a caller's `data`,
  the default `tag`, the Companion buttons and the critical payload below never
  reach an entity output. This is the same Home Assistant limitation the
  contract already records for this integration's own `notify.switchboard`
  entity.
- **A missing entity is a missing output.** An entity that is absent from the
  state machine, or whose state is `unavailable`, is treated exactly as a
  missing service: the same consecutive-failure repair, the same
  `delivery_failed` drop when it was a person's only output, and the same
  `missing_outputs` list in `explain`.
- **The recursion guard covers it.** `notify.switchboard` is this
  integration's own notify entity; naming it as an output is refused with the
  `recursion` reason, at config time and at runtime.

### `critical_payload` — a global option, and a critical push that is critical

`entry.options["critical_payload"]` is an optional boolean, **default true**;
absent means true.

While it is on, a message whose **effective** priority is `critical` — after
`escalate_when_nobody_home`, above — carries, on `mobile_app_*` outputs only,
the keys the Companion documentation gives for a critical notification:

| Registration `os_name` | Keys added under `data` |
|---|---|
| `ios`, `ipados`, `watchos` | `push: {sound: {name: "default", critical: 1, volume: 1.0}}` |
| `android` | `ttl: 0`, `priority: "high"`, `channel: "alarm_stream"` |
| anything else, absent, or no matching registration | both sets |

The OS is read from the `os_name` of the `mobile_app` config entry whose
registration produces that output's service name. Matching is
case-insensitive.

A key the caller — or the target's `default_data` — already wrote is never
overwritten. `push` counts as a **single** caller key: if the caller supplied
any `push` mapping, the router adds nothing under it, which is how a household
that prefers `push: {interruption-level: critical}` writes it.

With the option off, none of these keys is added. Nothing else in the message
changes, on any output.

### Breaking: `data.priority` no longer reaches a `mobile_app_*` output

Until 0.6.x, `data.priority` — the router's own input key, which selects the
effective priority — was merged into the `data` handed to every output,
Companion outputs included. From 0.7.0 the router **removes it** from the
`data` it forwards to a `mobile_app_*` output.

This is a change to what a Companion output receives, and it is stated here as
one rather than folded into the paragraph above:

- It happens **whatever** the priority is and **whatever** `critical_payload`
  says. Turning the option off does not put the key back.
- Android's Companion app reads `data.priority` and understands exactly one
  value, `high`. A caller who was relying on `data: {priority: high}` to make
  an Android notification urgent must stop: the router now sets
  `priority: "high"` itself, on a `critical` message, as part of the critical
  payload above.
- Every **other** output — a bare `notify.*`, a speaker, a webhook,
  `persistent_notification` — keeps receiving `priority` exactly as before. It
  is the caller's key and the router is a proxy.

### `explain` gains two top-level keys

The response of `notify_switchboard.explain` is a mapping with **five** keys:
`target`, `priority` and `persons` as before, plus

| Key | Type | Meaning |
|---|---|---|
| `escalated` | `"nobody_home"` or `null` | which rule raised this decision's priority. `null` when nothing did — including when the rule's condition held but the priority was already `critical` |
| `outputs` | list of `notify.*` service names | the target's bare outputs, in audience order; `[]` when it has none |

`priority` reports the **escalated** priority. Each person's value keeps
exactly the six keys v0.4 froze; a person silenced by a floored silence reports
`reason: silenced`, and their `detail` names both the entity that is on and the
floor it carries.

## Observer mode (plan B, ADR-007)

When enabled on a row, the router subscribes to the row's `alert.*` state and routes on `idle → on` (message from the row), routes the `done` message on `on|off → idle`, and stops on `on → off`. In this mode the alert does not need to list the router in `notifiers`.

## What this contract does not promise

- No voice, no calls, no external network: outputs are whatever `notify.*` services exist.
- The `NotifyEntity` path carries only `message` and `title` (Home Assistant limitation).
- Text of routed messages is not translated; only router-added labels are.
