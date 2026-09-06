# ADR 0005: Public repositories, MIT license, English source with fr/es UI

Date: 2026-09-06

## Status

Accepted.

## Context

This project starts as infrastructure for one household but is intended to
be usable, and contributable to, by anyone running Home Assistant.

## Decision

Every repository in the suite (this router, the voice adapters, the cards)
is public, licensed MIT, and written in English (code, comments, README,
CHANGELOG, ADRs). The user-facing interface (`strings.json` / config and
options flow copy) is translated: English is the source of truth, French
and Spanish are maintained alongside it and kept complete.

## Consequences

Nothing household-specific can live in code or committed configuration;
anything specific to one deployment is external configuration, applied
after installation (see `docs/ARCHITECTURE.md`, "Why both a legacy service
and an entity" and the roadmap). Every new user-facing string change must
ship with its French and Spanish translation in the same pull request;
`tests/test_translations.py` enforces that the three files expose the same
keys.
