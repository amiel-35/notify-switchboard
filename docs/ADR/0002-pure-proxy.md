# ADR 0002: The router is a pure notify proxy

Date: 2026-09-06

## Status

Accepted.

## Context

A notification router could plausibly own a delivery channel of its own
(e.g. sending push notifications directly via a cloud service), which
would simplify some features (delivery receipts, rich formatting) at the
cost of becoming another notification silo that other tools would need to
integrate against.

## Decision

Notify Switchboard presents itself as a `notify.*` (both the legacy
service and a `NotifyEntity`), never sends anything by itself, and only
ever calls other, already-configured `notify.*` services. It introduces no
dependency on any external delivery service.

## Consequences

Every delivery mechanism a user already has configured in Home Assistant
(Companion app, cast/voice adapters, persistent notification, email, ...)
keeps working through Notify Switchboard without any adapter code living
in this repository. The trade-off is that Notify Switchboard cannot offer
features that depend on knowing the delivery channel's own capabilities
beyond what `data` already carries; those stay in the receiving `notify.*`
implementation.
