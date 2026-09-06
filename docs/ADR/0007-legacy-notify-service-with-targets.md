# ADR 0007: Legacy notify service with per-target `targets`, `NotifyEntity` degraded, observer mode as plan B

Date: 2026-09-06

## Status

Accepted.

## Context

The `alert` integration only ever calls `notify.*` by legacy service name in
its `notifiers:` list; there is no way to point it at a `NotifyEntity`
(`homeassistant/components/notify/legacy.py`, tracked upstream as
core#164855: migrating `alert` to entities breaks it). `alert` itself has
been frozen by Home Assistant core since September 2025: its current
behaviour is stable, but not guaranteed to remain the model going forward.
Notify Switchboard needs an entry point `alert` can already use today, and a
credible answer to "what happens if the legacy service disappears".

## Decision

The main entry point is the legacy `notify` service
(`BaseNotificationService`). Its `targets` property generates one
`notify.switchboard_<slug>` service per row of the routing table configured
in the UI. Because an `alert`'s `data` is static and cannot be templated,
this is how an `alert` tells the router which row it belongs to: it simply
lists `switchboard_<slug>` in its own `notifiers:`. A `NotifyEntity` is
exposed in addition, documented as degraded — the entity API carries
neither `target` nor `data` (upstream issue #3684 is open), so it routes
through the default row at `normal` priority. As a hedge against the legacy
service being removed, the router can instead watch the `alert.*` entities
referenced in its table directly (`on` → route, `idle` → done, `off` →
silence) and stop needing to be a notifier at all. This "observer mode"
ships as an opt-in setting from v0.1, so the fallback is exercised by the
acceptance suite, not just described in a document.

## Consequences

`alert`-based deployments are fully supported today through the legacy
service. If the legacy service is ever removed, observer mode is already
implemented and tested, at the cost of losing whatever payload a real
`notify` call would have carried — it falls back to the row's own name,
later improved by per-row message text (ADR-0016). `NotifyEntity` remains
the forward-looking surface, ready to take over once `alert` can target it.
