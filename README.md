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
   them (`mobile_app_alice`, without the `notify.` prefix), optionally the
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

## Removal

Settings → Devices & services → Notify Switchboard → delete. This removes
the `notify.switchboard` service and the entity; it does not touch the
`notify.*` services it forwarded to.

## Roadmap

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the sprint table
(S0 → S8). This release covers S0 and S1: the routing table, the per-person
decision, acknowledge and snooze, night deferral, observer mode and the
diagnostic entities.

## Documentation

- [Contract](docs/contract.md) — the frozen public names and behaviour
  (`notify.switchboard`, `notify.switchboard_<target>`, `data.priority`,
  `data.source_entity`, observer mode) that this project commits to across
  minor versions.
- [Architecture](docs/ARCHITECTURE.md) — the proxy model, input/output
  contracts, the decisions Sprint 1 took where the contract left room, and the
  sprint roadmap.
- [Known issues](docs/known-issues.md) — what was consciously left out, and
  why.

A quickstart and importable blueprints are planned for S7.

## License

[MIT](LICENSE) © 2026 the maintainer
