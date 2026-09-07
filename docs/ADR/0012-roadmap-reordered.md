# ADR 0012: Roadmap reordered — acknowledge, cards and blueprints before voice

Date: 2026-09-06

## Status

Accepted.

## Context

The initial roadmap sketch placed a voice adapter early, close to the
router's foundations. Working through what a router actually needs before
it is worth deploying anywhere real — acknowledging an alert, snoozing it,
seeing it on a wall display, and a blueprint a newcomer can follow without
reading the code — showed that voice output is not on that critical path;
it is an independent, parallel feature with its own repository and no
dependency on the router's later increments.

## Decision

The roadmap is reordered so the router's v0.1 increment absorbs
acknowledge/snooze, the routing-table UI, presence and silence handling,
and observer mode together (previously split across two increments); cards
and blueprints/quickstart follow directly after. Voice adapters (Cast,
AirPlay) move later, and the Alexa adapter is deprioritised altogether:
Home Assistant core's own Alexa Devices integration already exposes
speak/announce entities that cover the same need.

## Consequences

A deployment gets a fully usable, acknowledgeable, snoozeable router with a
UI several increments earlier than under the original ordering, at the
cost of voice output arriving later. Because voice adapters have no
dependency on the router's later increments (ADR-0003), they can still be
picked up out of order if a deployment wants voice sooner — this ADR
changes sequencing, not the architecture.

**Correction (2026-09-07):** the Alexa reasoning above (core already exposes
speak/announce entities, so no dedicated adapter is needed) turns out to
apply to Cast and AirPlay too: core's legacy `platform: tts` notify platform
(`homeassistant/components/tts/notify.py`) speaks on any `media_player`,
Cast and AirPlay included. This does not change the sequencing decision
above, but the Cast/AirPlay rows it deprioritises-not-quite-to-zero are, in
practice, superseded rather than merely delayed — see
`docs/ARCHITECTURE.md`'s roadmap table.
