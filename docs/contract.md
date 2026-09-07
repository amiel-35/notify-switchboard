# Notify Switchboard — Public contract (v0.4 addendum, frozen per ADR-011 until 1.0 changes it)

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

## Observer mode (plan B, ADR-007)

When enabled on a row, the router subscribes to the row's `alert.*` state and routes on `idle → on` (message from the row), routes the `done` message on `on|off → idle`, and stops on `on → off`. In this mode the alert does not need to list the router in `notifiers`.

## What this contract does not promise

- No voice, no calls, no external network: outputs are whatever `notify.*` services exist.
- The `NotifyEntity` path carries only `message` and `title` (Home Assistant limitation).
- Text of routed messages is not translated; only router-added labels are.
