# ADR 0004: Notifier Hub rejected as a base

Date: 2026-09-06

## Status

Accepted.

## Context

Notifier Hub is an existing community project that already routes
notifications in Home Assistant. Building on top of it, rather than
starting a new integration, was considered.

## Decision

Notifier Hub is not used as the base for Notify Switchboard: it routes
globally rather than per person, its do-not-disturb handling has no effect
on push delivery, it does not expose a `notify` platform (so `alert`
cannot list it under `notifiers:`), and its repository has been inactive.
Its `confirmation` and `escalate` concepts are kept as inspiration for
future sprints (see the S2 row in `docs/ARCHITECTURE.md`), not as code.

## Consequences

Notify Switchboard is written from scratch against the current Home
Assistant `notify`/`alert`/`person` APIs, with its own config flow and
entity model, at the cost of not reusing whatever community adoption
Notifier Hub already had.
