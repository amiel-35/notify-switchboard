# ADR 0014: The Cast voice adapter is named "Cast Notifier"

Date: 2026-09-07

## Status

Accepted.

## Context

The Cast voice adapter needed a public repository name and domain. "Google
Home Notifier" was the working name during early design, matching the
product family the adapter primarily targets.

## Decision

The repository and domain are named Cast Notifier (`cast-notifier`,
`cast_notifier`), not Google Home Notifier: that name already belongs to an
unrelated Node.js project with the same purpose and roughly 574 stars, and
"Cast" more accurately covers the range of devices the adapter actually
targets — Chromecast and Nest Hub displays, not only Google Home speakers.
The "X Notifier" naming style is kept for consistency with the rest of the
suite's voice adapters (AirPlay Notifier, and an Alexa Notifier if one is
ever built).

## Consequences

No end-user documentation or HACS listing is ever published under the
"Google Home Notifier" name, avoiding both a naming clash and confusion
with the existing Node.js project. The rename happened before the
adapter's first tagged release, so no installs or HACS repository
registrations needed to migrate.
