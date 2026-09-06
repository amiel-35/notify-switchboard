# ADR 0010: "Voice is not an alert" and "no security through voice" are configuration rules, not code guarantees

Date: 2026-09-06

## Status

Accepted.

## Context

Two safety properties matter to any deployment: an alert should not
silently degrade into a spoken announcement nobody has to acknowledge, and
text derived from an alarm panel or a lock should never be read aloud where
anyone within earshot can hear it. Neither property can be enforced purely
in code without either hard-coding domain knowledge the router should not
own ("this alert is security", "this notify is voice"), or refusing
configurations a deployment might have a legitimate reason to want — a
security summary spoken to a phone-verified administrator, for instance.

## Decision

Both properties are documented as strong configuration recommendations,
not code-enforced invariants. Voice adapters are `notify.*` services like
any other, meant for *information* a deployment chooses to route there,
never wired into an `alert` by default (ADR-0003); text derived from
`alarm_control_panel.*` or `lock.*` should never be handed to a voice
adapter. Nothing in the router prevents a configuration from doing either
anyway. Voice adapters instead offer an optional deny-list on
`data.source_entity`, matched against the entity domains it lists, for
deployments that want the code to help enforce the rule.

## Consequences

A deployment remains free to break either rule if it chooses to — the
router does not become the arbiter of what counts as sensitive. Anyone
building a voice adapter, or auditing a deployment's routing table, needs
to read this ADR rather than assume the software guarantees the invariant
end to end; the deny-list is opt-in and only as complete as the entities a
caller actually names in `data.source_entity`.
