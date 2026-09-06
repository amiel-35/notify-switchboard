# ADR 0001: Native first

Date: 2026-09-06

## Status

Accepted.

## Context

Home Assistant already ships the building blocks a notification system
needs: `alert` for state that persists and its own lifecycle (repeat,
acknowledge, return to normal), `event` for one-off facts, `person` for
presence, `schedule`/`input_boolean` for silence windows and do-not-disturb,
and `notify` as the universal send/receive contract. It would be possible
to reimplement pieces of this (a custom alert state machine, a custom
presence tracker) inside Notify Switchboard.

## Decision

Nothing that Home Assistant already provides is reimplemented. `alert`
remains the source of truth for persistent state, `event` for point-in-time
facts, `person` for presence, `schedule`/`input_boolean` for silence
windows, and `notify` as the only contract Notify Switchboard speaks, in
and out.

## Consequences

Notify Switchboard has a narrow, well-defined job: distribution. It cannot
drift from `alert`'s own acknowledge/repeat semantics because it does not
reimplement them. It does mean Notify Switchboard depends on `alert` and
`person` behaving the way core Home Assistant documents them; changes to
those integrations are a risk tracked in `docs/ARCHITECTURE.md`.
