# ADR 0006: Sprints are testable increments, not time boxes

Date: 2026-09-06

## Status

Accepted.

## Context

A fixed sprint length (e.g. two weeks) forces either shipping something
half-finished on the deadline or letting scope silently slip past it. This
is a side project with irregular available time.

## Decision

A "sprint" here is a functional increment with a concrete, testable
acceptance criterion (see the table in `docs/ARCHITECTURE.md`), not a time
box. It ends when its criterion is verifiably met — tests green, CI green,
played end-to-end on the development instance — not on a calendar date.
Each increment ships its own release (tag + GitHub release + updated
`CHANGELOG.md`).

## Consequences

Progress is measured in shipped, usable increments rather than elapsed
time. The roadmap order can change (e.g. voice before acknowledge/snooze)
when that better matches what is actually needed next, as already noted in
the umbrella doctrine.
