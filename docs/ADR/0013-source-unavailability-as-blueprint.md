# ADR 0013: Source-unavailability monitoring ships as a blueprint, not in the router

Date: 2026-09-06

## Status

Accepted.

## Context

A recurring failure mode motivating this project is a sensor that silently
stops reporting: its `alert` never leaves `off`, not because the underlying
problem went away, but because nothing ever evaluated a condition to turn
it `on`. Detecting "this source has not reported in N minutes" and turning
that into an alert is generic, reusable logic, and it would be possible to
build it directly into the router.

## Decision

This capability is delivered as a blueprint — an automation template
distributed alongside the router, not code inside the `notify_switchboard`
integration itself. A blueprint composes with `binary_sensor`/template
entities that already exist in any Home Assistant instance and produces an
ordinary `alert.*`, which then routes through the switchboard exactly like
any other alert, with no special case in the router's own code.

## Consequences

The router's scope stays limited to distribution (ADR-0002); unavailability
detection is solved once, as a documented, forkable blueprint anyone can
adapt to their own sensors, rather than as a configuration surface the
router would have to maintain, version and test indefinitely. The
trade-off is one more moving part a new user has to install, which is why
it ships together with the quickstart documentation rather than as a
silent addition.
