# ADR 0015: A refused notification raises `ServiceValidationError`, never fails silently

Date: 2026-09-07

## Status

Accepted.

## Context

End-to-end testing of the Cast voice adapter's first release showed that a
caller sending a message the adapter refuses (a deny-listed
`source_entity`, or invalid `data`) received an ordinary success response
from Home Assistant — the refusal was visible only in the adapter's own
logs. A caller has no reliable way to notice its message was dropped,
which is worse than a visible error: an alert that keeps "succeeding" while
never actually reaching anyone quietly erodes trust in every alert that
uses it.

## Decision

An adapter that refuses to deliver a message, for any documented reason
(a deny-listed `source_entity`, `data` that fails schema validation, and
so on), raises a translated `ServiceValidationError` and logs the refusal,
instead of returning normally. This applies uniformly across the suite's
`notify.*` adapters.

## Consequences

A caller that lists a refused adapter in its `notifiers:` sees a visible
error on every repeat of that alert, which is the correct signal — a loud,
repeated failure beats a silent one. AirPlay Notifier's first release
implements this from the start; Cast Notifier, released slightly earlier
without it, adopts it in its next patch release. Any future `notify.*`
adapter in the suite is expected to follow the same rule from its first
release.
