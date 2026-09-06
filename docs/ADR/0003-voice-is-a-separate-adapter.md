# ADR 0003: Voice is a separate adapter, never wired to alerts by default

Date: 2026-09-06

## Status

Accepted.

## Context

Voice output (a Cast speaker, an AirPlay speaker, an Echo) is tempting as
an alert channel because it is attention-grabbing, but it cannot ask for
acknowledgement, cannot be snoozed mid-sentence, and can leak sensitive
information (security/lock state) into a shared room.

## Decision

Voice adapters (`notify-cast`, `notify-airplay`, `notify-alexa`, each its
own repository) are `notify.*` services like any other, intended for
*information* the deployment chooses to route there (doorbell, a finished
cycle) — never wired to an `alert` by default. Text derived from
`alarm_control_panel.*` or `lock.*` must never reach a voice adapter.

## Consequences

A deployment that wants voice announcements for alerts must do so
explicitly, target by target, through its own routing configuration —
Notify Switchboard itself never assumes it. This keeps the safety property
easy to audit: grep the deployment's configuration for which classes route
to a voice `notify.*`, instead of having to trust router internals.
