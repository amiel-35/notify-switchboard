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

Notify Switchboard exposes two things:

- the legacy `notify.switchboard` service, so the core `alert` integration
  can list it under `notifiers:`;
- a modern `NotifyEntity`, for automations and future action buttons.

Both accept `message`, `title` and `data` (including `data.class`,
`data.priority`, `data.alert_entity`) and forward, unchanged, to whichever
`notify.*` services a `Router` selects. In this first release the router is
a pass-through: it always calls every configured default target. Per-person
routing (presence, do-not-disturb, snoozes) is on the roadmap.

## Install

Via [HACS](https://hacs.xyz/), as a custom repository:

1. HACS → Integrations → menu → Custom repositories.
2. Add `https://github.com/amiel-35/notify-switchboard`, category
   "Integration".
3. Install "Notify Switchboard", then restart Home Assistant.

## Configuration

Settings → Devices & services → Add integration → "Notify Switchboard".
Setup takes no input. Then open the integration's options to set the
**default targets**: a comma-separated list of notify service names, e.g.

```
notify.mobile_app_maintainer, notify.persistent_notification
```

## Removal

Settings → Devices & services → Notify Switchboard → delete. This removes
the `notify.switchboard` service and the entity; it does not touch the
`notify.*` services it forwarded to.

## Roadmap

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the sprint table
(S0 → S8). This release covers S0/S1: skeleton, contracts, and a working
pass-through.

## License

[MIT](LICENSE) © 2026 the maintainer
