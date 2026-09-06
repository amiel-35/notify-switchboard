# Notify Switchboard — Public contract (v0.2 addendum, frozen per ADR-011 until 1.0 changes it)

> English, because it will move to `docs/contract.md` in the `notify-switchboard`
> repository and is guarded by a contract test. Any change requires an ADR.
>
> v0.2 addendum (ADR-0016): five new services (`acknowledge`, `snooze`,
> `unsnooze`, `silence`, `unsilence`) and three new optional per-row texts
> (`message`, `done_message`, `default_title`). Everything else below is the
> v0 text, unchanged.

## Names (public, must not change without a major version)

| Item | Value |
|---|---|
| Integration domain | `notify_switchboard` |
| Legacy notify service (default target) | `notify.switchboard` |
| Per-target services (legacy `targets` property) | `notify.switchboard_<target>` where `<target>` is the slug of a routing-table row |
| Notify entity (degraded path) | `notify.switchboard` entity, `notify.send_message` with `message` + `title` only |
| Event entity | `event.switchboard_delivery` with fixed `event_types`: `routed`, `dropped`, `acknowledged`, `snoozed` |
| Per-person entities | `binary_sensor.<person>_silenced`, `sensor.<person>_last_notification`, `sensor.<person>_active_snoozes` (unique_id = `<entry_id>:<person entity_id>:<kind>`) |
| Global entities | `sensor.switchboard_routed_today`, `sensor.switchboard_dropped_today` |
| UI services (v0.2, ADR-0016) | `notify_switchboard.acknowledge`, `notify_switchboard.snooze`, `notify_switchboard.unsnooze`, `notify_switchboard.silence`, `notify_switchboard.unsilence` |

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

## Observer mode (plan B, ADR-007)

When enabled on a row, the router subscribes to the row's `alert.*` state and routes on `idle → on` (message from the row), routes the `done` message on `on|off → idle`, and stops on `on → off`. In this mode the alert does not need to list the router in `notifiers`.

## What this contract does not promise

- No voice, no calls, no external network: outputs are whatever `notify.*` services exist.
- The `NotifyEntity` path carries only `message` and `title` (Home Assistant limitation).
- Text of routed messages is not translated; only router-added labels are.
