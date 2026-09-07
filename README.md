# Notify Switchboard

[![MIT License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

A [Home Assistant](https://www.home-assistant.io/) custom integration that
acts as a pure `notify` **proxy**. It never delivers a notification itself:
it only forwards to `notify.*` services you already have configured
(Companion app, persistent notification, voice adapters, and so on).

## Why

Home Assistant already has the pieces a notification system needs: `alert`
for state that persists, `event` for one-off facts, `person` for presence,
`schedule`/`input_boolean` for do-not-disturb, and `notify` as the universal
send contract. What's missing is a per-person distribution layer that sits
in front of `notify.*` and decides who should be told, and when. Notify
Switchboard is that layer, kept as close to native Home Assistant as
possible — see [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the full
contract and rationale.

## The proxy model

Notify Switchboard exposes:

- `notify.switchboard`, and one `notify.switchboard_<slug>` per row of the
  routing table, so the core `alert` integration can name a row under
  `notifiers:`;
- a `NotifyEntity`, documented as degraded: `notify.send_message` carries only
  `message` and `title`, so it routes to the default row with priority
  `normal`.

A call carries `message`, `title` and `data` (`priority`, `source_entity`,
`tag`, and anything else, merged over the row's default data). For every
person in the row's audience the router checks, in order: the presence rule
against `person.*`, the person's silence entities, an active snooze — with
`priority: critical` overriding the last two — and then calls each of that
person's `notify.*` outputs.

On a Companion output it adds an **Acknowledge** button (when the row is tied
to an `alert.*` and allows it) and one **Snooze** button per configured
duration. Acknowledging turns that alert off, and only an alert listed in the
routing table. A message silenced during someone's night is not lost: it is
queued and delivered at their wake time.

## Install

Via [HACS](https://hacs.xyz/), as a custom repository:

1. HACS → Integrations → menu → Custom repositories.
2. Add `https://github.com/amiel-35/notify-switchboard`, category
   "Integration".
3. Install "Notify Switchboard", then restart Home Assistant.

## Configuration

Settings → Devices & services → Add integration → "Notify Switchboard".
Setup takes no input; the routing table is built from the integration's
options:

1. **Add a person** — pick a `person.*`, list the notify services that reach
   them (`mobile_app_alice`; the `notify.` prefix is accepted and stripped),
   optionally the
   entities whose `on` state means "silent", and a wake time.
2. **Add a target** — one row per alert: a slug (it becomes
   `notify.switchboard_<slug>`), a name, a default priority, the `alert.*` it
   is tied to, the audience, a presence rule, and the snooze durations to
   offer.
3. **Default target** — the row used by `notify.switchboard` when no target is
   given, and by the notify entity.

Then point an alert at it:

```yaml
alert:
  water_leak:
    name: Water leak
    entity_id: binary_sensor.leak_kitchen
    state: "on"
    repeat: [5, 15, 60]
    can_acknowledge: true
    notifiers:
      - switchboard_leak
```

## Services

Everything the notification buttons do is also a service, so a card, a script
or an automation can do it too. Each one refuses an invalid call with an
explicit error rather than doing nothing quietly.

| Service | Fields | What it does |
|---|---|---|
| `notify_switchboard.acknowledge` | `target` | Turns off the row's alert, if the row has one and allows it. |
| `notify_switchboard.snooze` | `target`, `minutes`, `person` (optional) | Stops that target for a while. `minutes` has to be one of the durations the row offers; without `person`, the whole audience is snoozed. |
| `notify_switchboard.unsnooze` | `target`, `person` (optional) | Lifts a snooze immediately. |
| `notify_switchboard.silence` | `person`, `minutes` | Silences somebody for a while, for every target, without touching their own silence entities. Only `critical` still gets through. |
| `notify_switchboard.unsilence` | `person` | Lifts that silence immediately. |

A silence set this way shows up in `binary_sensor.<person>_silenced` (with an
`until` attribute), survives a restart, and lifts on its own.

## Message text

Three optional fields per row, all empty by default:

- **Message template** and **Back-to-normal template** — used in observer mode
  instead of the row's bare name. The watched alert's state is available to
  the template as `alert`, so a row can write
  `Water on the floor, {{ alert.attributes.level }}`.
- **Default title** — the title used when the caller gives none, and for every
  message observer mode sends.

## Translations

The interface ships in English, French and Spanish — including the entity
names: `sensor.switchboard_routed_today` reads as "Routed today", "Acheminées
aujourd'hui" or "Encaminadas hoy" depending on the instance language, while
the **entity id itself never changes**, so an `alert:`, an automation or a card
written against the documented names keeps working in any language.

English and French are
written by the maintainer; **the Spanish translation
(`custom_components/notify_switchboard/translations/es.json`) is machine
translated and has not been reviewed by a native speaker** — corrections and
new languages are very welcome, one pull request per language.

## Removal

Settings → Devices & services → Notify Switchboard → delete. This removes
the `notify.switchboard` service and the entity; it does not touch the
`notify.*` services it forwarded to.

## Roadmap

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the sprint table and
the router's own roadmap. This release covers everything up to router S3: the
routing table, the per-person decision, acknowledge and snooze, night
deferral, observer mode, the diagnostic entities, the five services above, a
temporary per-person silence, the per-row message texts, and — since 0.3.0 —
translated entity names, a parallel fan-out bounded by a per-output timeout,
`person.user_id` as the canonical link for Companion callbacks, and actions
that exist whether or not the config entry is loaded.

Next: zero-config (S4), a real quiet-hours model (S5), escalation (S6) and
places (S7).

## Documentation

- [Contract](docs/contract.md) — the frozen public names and behaviour
  (`notify.switchboard`, `notify.switchboard_<target>`, `data.priority`,
  `data.source_entity`, observer mode) that this project commits to across
  minor versions.
- [Architecture](docs/ARCHITECTURE.md) — the proxy model, input/output
  contracts, the decisions Sprints 1 and 2 took where the contract left room
  (how the two silence sources combine, what a row template can read), and the
  sprint roadmap.
- [Known issues](docs/known-issues.md) — what was consciously left out, and
  why.
- [Quickstart](docs/quickstart.md) — route your first alert in ten minutes.
- [Blueprints](docs/blueprints.md) — the three importable automation
  blueprints shipped in `blueprints/automation/notify_switchboard/`.

## License

[MIT](LICENSE) © 2026 the maintainer

## How this project is built

This integration is written almost entirely by AI models, under the direction
and the responsibility of a single human maintainer, who owns every product
decision and tests each release on real hardware.
[`docs/how-this-is-built.md`](docs/how-this-is-built.md) sets out who does
what, what the specification-before-code discipline is meant to catch, and
what it does not catch — read it before deciding how much to trust this code.
