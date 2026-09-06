# ADR 0009: Secure notification actions — allow-list, authentication, audit

Date: 2026-09-06

## Status

Accepted.

## Context

Companion push notifications carry actions that can immediately turn an
alert off or apply a snooze. An action arrives asynchronously, as a
`mobile_app_notification_action` event, with no request/response cycle the
way a service call has: whatever identifier it names could in principle be
stale, spoofed, or simply reference an alert that was never meant to be
dismissed this way. Unlocking the phone should not be assumed regardless of
which alert fired.

## Decision

The router only ever acts on an `alert.*` action if that entity is present
in its own routing table — an identifier for anything else is refused
outright, never silently accepted. Every acknowledgement logs the acting
`context.user_id`. Any row whose priority is `high` or `critical` gets
`authenticationRequired: true` by default on its Companion actions, so
acknowledging or snoozing a high-stakes alert requires unlocking the
device; a row can still opt out of this if its own configuration says so
explicitly.

## Consequences

A stray automation or a replayed event cannot use the action-callback path
to silence an alert outside the table, and every acknowledgement is
attributable to a Home Assistant user. High/critical alerts cannot be
dismissed from a locked screen, a small UX cost for the classes of alert
whose whole point is to require attention. The allow-list is read from the
live routing table on every call rather than cached, so a target removed
from the table stops being acknowledgeable immediately.
