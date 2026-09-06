# Quickstart: route your first alert in 10 minutes

This walks you through installing Notify Switchboard and routing one real
alert — a water leak — end to end: config, a routing-table row, an `alert:`
that uses it, and a test from Developer tools. It follows the public
contract in [`contract.md`](contract.md); read that file if you need the
exact rules (which priority overrides silence, what happens with an unknown
target, and so on).

> Names used below (`notify.switchboard`, `notify.switchboard_<target>`,
> `data.priority`, `data.source_entity`) are frozen (see the header of
> [`contract.md`](contract.md)) — they will not change without a major
> version, so it is safe to build automations and blueprints against them
> today.

## 1. Install via HACS

1. In Home Assistant, open **HACS → Integrations**, then the **⋮** menu →
   **Custom repositories**.
2. Add `https://github.com/amiel-35/notify-switchboard`, category
   **Integration**.
3. Find **Notify Switchboard** in HACS, click **Download**, then restart
   Home Assistant when prompted.

## 2. Add the integration

**Settings → Devices & services → Add integration** → search for
**Notify Switchboard**. Setup takes no input — a single instance is created
and immediately registers:

- the `notify.switchboard` service (so `alert:` can list it), and
- a `notify.switchboard` entity (the degraded path, see step 7).

## 3. Add a person and an output

Open the integration's **Configure** button, then its persons section, and
add one entry per person who should ever be notified:

- **Person**: the `person.*` entity (e.g. `person.alice`).
- **Outputs**: one or more existing `notify.*` services to actually deliver
  to this person — typically their Companion app's notify service (e.g.
  `mobile_app_alice`), enter it **without** the `notify.` prefix.
- **Silence entities** (optional): any `schedule.*` or `input_boolean.*`
  whose `on` state should mean "do not disturb this person" (a night
  schedule, a manual "focus mode" toggle, ...).
- **Wake time** (optional): when the person's night silence ends, so a
  message dropped for silence during the night is delivered then instead of
  lost.

Repeat for every person. You need at least one before adding a target.

## 4. Add a target row

Still in **Configure**, open the targets section and add a row:

| Field | What to put | Example |
|---|---|---|
| Slug | short id; becomes `notify.switchboard_<slug>` | `leak` |
| Name | display name | Water leak |
| Class | free-text grouping (never a hardcoded value) | building |
| Default priority | `info` \| `normal` \| `high` \| `critical` | high |
| Alert entity (optional) | the `alert.*` this row is tied to, for Acknowledge | `alert.leak_kitchen` |
| Audience | which persons from step 3 should hear about this | Alice, Bob |
| Presence rule | `always` \| `home_only` \| `away_only` | always |
| Allow acknowledge | shows an Acknowledge button on Companion | on |
| Snooze durations | minutes; empty = no snooze button | 15, 60 |
| Observer mode | see step 8; leave off for now | off |

Saving this row is what makes `notify.switchboard_leak` exist as a service —
until a row's slug is `leak`, calling that service drops with
`unknown_target` and raises a single repair issue.

## 5. Write the `alert:`

`alert:` is native, YAML-only Home Assistant — a blueprint cannot create it
(see [`docs/blueprints.md`](blueprints.md)). Copy
[`docs/examples/alert_leak.yaml`](examples/alert_leak.yaml) into your
configuration (directly under an `alert:` key, or a package), pointing
`entity_id` at your real sensor:

```yaml
alert:
  leak_kitchen:
    name: "Kitchen leak sensor"
    entity_id: binary_sensor.leak_kitchen
    repeat: [5, 15, 60]
    message: "Water leak detected: {{ state_attr('binary_sensor.leak_kitchen', 'friendly_name') }}."
    done_message: "Kitchen leak sensor is dry again."
    title: "Leak"
    notifiers:
      - switchboard_leak
```

The `notifiers:` entry — the target's slug, **without** the `notify.`
prefix — is the only place the alert tells Notify Switchboard who it is
(the alert's own `data` cannot be templated, so nothing about the alert
needs to travel through `data`; see ADR-008 in the doctrine).

## 6. Restart and test from Developer tools

Restart Home Assistant so the new row's service and the `alert:` entity both
load. Then, **Developer tools → Actions**, pick `notify.switchboard_leak`
(or `notify.switchboard` with `target: [leak]`), and call it directly to
check routing before wiring a real sensor:

```yaml
action: notify.switchboard_leak
data:
  message: "Test leak notification"
  data:
    priority: high
    source_entity: binary_sensor.leak_kitchen
```

You should see it arrive on every output configured for every person in the
row's audience who is currently present (or every person, if
`presence_rule: always`) and not silenced. If someone is silenced, only
`priority: critical` will still reach them.

## 7. Acknowledge and snooze from the phone

If the row has `alert_entity` set and `allow_acknowledge: on`, Companion
notifications get action buttons:

- **Acknowledge** → sends `mobile_app_notification_action` with
  `action: switchboard:ack:leak`. The router only calls `alert.turn_off` on
  `alert.leak_kitchen` because that entity is this row's `alert_entity` (an
  allow-list — an arbitrary alert id in the action string is refused and
  logged with the acting user's id).
- **Snooze `<n>`** (one button per configured duration) → sends
  `action: switchboard:snooze:leak:<n>`, e.g. `switchboard:snooze:leak:60`
  for an hour. Snoozes are stored per (person, target), survive a Home
  Assistant restart, and expire on their own.

## 8. Read the diagnostic sensors

- `sensor.switchboard_routed_today` / `sensor.switchboard_dropped_today` —
  daily counters, reset at local midnight. The dropped sensor exposes a
  `reasons` attribute (things like `silenced`, `snoozed`, `unknown_target`,
  `recursion`) so a drop is never silent.
- Per person: `binary_sensor.<person>_silenced`,
  `sensor.<person>_last_notification`, `sensor.<person>_active_snoozes`.

If `sensor.switchboard_dropped_today` climbs and you did not expect it,
check its `reasons` attribute first — it tells you *why* before you go
digging through logs.

## Two other paths worth knowing about

- **Degraded path (`NotifyEntity`)**: automations that call
  `action: notify.send_message` targeted at the `notify.switchboard` entity
  reach the router too, but only `message` and `title` make the trip (a
  Home Assistant limitation — `NotifyEntity` has no `target` or `data`).
  They route through the **default target** at `normal` priority. Use the
  legacy `notify.switchboard_<target>` / `notify.switchboard` services
  above whenever you need a specific target, a priority, or
  `source_entity`.
- **Observer mode**: if the legacy `notify.*` service platform is ever
  retired upstream, a row with `observer_mode: on` keeps working without
  being listed in any `notifiers:` — the router watches that row's
  `alert_entity` state directly (`idle → on` routes the alert's message,
  `→ idle` routes the done message, `on → off` just stops). It is
  implemented and tested from v0.1, not a future promise; turn it on for a
  row today if you would rather not touch the `alert:`'s `notifiers:` list
  at all.

## Next

- One-off facts instead of a lasting alert (a door opened, a delivery
  arrived, a machine finished its cycle)? See
  [`docs/blueprints.md`](blueprints.md) for three ready-made automation
  blueprints, including the "a sensor went silent and nobody noticed" case.
- Full field-by-field behaviour: [`contract.md`](contract.md).
