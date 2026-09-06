# ADR 0008: Alert identity travels through the target, not through `data`

Date: 2026-09-06

## Status

Accepted.

## Context

An `alert`'s `data` is static configuration, fixed at authoring time and
never templated per firing. If Notify Switchboard needed the caller to
carry a value such as "route me as a water-leak notification" inside
`data`, every `alert` would have to hard-code that value forever, and
nothing could compute or vary it at runtime. The router still needs, on
every call, to know unambiguously which row of its routing table applies —
the row is what carries the class, default priority, optional `alert.*`
link and audience.

## Decision

The identity of a call is the **target** it comes in on, not any key
inside `data`. Each routing-table row is exposed as its own legacy service
name, `notify.switchboard_<slug>`, generated through the legacy service's
`targets` property (ADR-0007). An `alert` states which row it belongs to
simply by listing that service name in its own `notifiers:` — nothing
needs to flow through `data` to convey identity. A caller that omits
`target` entirely gets the deployment's configured default row.

## Consequences

Routing a new alert through a given row is a one-line change to
`notifiers:`, requires no templating support from `alert`, and needs no
extra validation of arbitrary `data` content just to determine identity.
The trade-off is that renaming a row changes the service name its callers
must use; this is why the `notify.switchboard_<slug>` schema is one of the
names frozen at 1.0 (ADR-0011) rather than left free to evolve silently.
