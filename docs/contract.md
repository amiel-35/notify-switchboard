# Notify Switchboard — Public contract (v0, frozen per ADR-011 until 1.0 changes it)

> English, because it will move to `docs/contract.md` in the `notify-switchboard`
> repository and is guarded by a contract test. Any change requires an ADR.

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

## Observer mode (plan B, ADR-007)

When enabled on a row, the router subscribes to the row's `alert.*` state and routes on `idle → on` (message from the row), routes the `done` message on `on|off → idle`, and stops on `on → off`. In this mode the alert does not need to list the router in `notifiers`.

## What this contract does not promise

- No voice, no calls, no external network: outputs are whatever `notify.*` services exist.
- The `NotifyEntity` path carries only `message` and `title` (Home Assistant limitation).
- Text of routed messages is not translated; only router-added labels are.
