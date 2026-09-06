# ADR 0011: Frozen input contract and a contract test

Date: 2026-09-06

## Status

Accepted.

## Context

This project exists to be depended on by users' own `alert:` configuration,
written once and expected to keep working across upgrades. Nothing stops an
implementation detail — a service name, a `data` key — from drifting during
active development unless it is explicitly called out as public and
pinned.

## Decision

The input contract — the `notify_switchboard` domain, the
`notify.switchboard` service, the `notify.switchboard_<slug>` schema, and
the `data.*` keys documented in `docs/contract.md` (`priority`,
`source_entity`, and the pass-through keys) — is frozen at 1.0. Renaming
any of these breaks every user's `alert:` configuration; it is treated not
as an ordinary breaking change but as something a versioned, documented
contract commits not to do casually. A dedicated contract test in the
acceptance suite pins the documented shape and fails the build the moment
it drifts unintentionally.

## Consequences

Changing a frozen name now requires a new ADR that says so explicitly and
updates `docs/contract.md`; a pull request that touches `contract.md`
without one is rejected on review. This slows down changing the public
surface, deliberately — everything else in the codebase (internal module
layout, the decision engine, dispatcher internals) stays free to change
without ceremony as long as the contract test remains green.
