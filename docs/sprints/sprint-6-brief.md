# Sprint 6 brief — Notify Switchboard v0.6.0 (bounded, declarative escalation; suite roadmap "S10")

> Spec agent first (ADR-0020, contract v0.6 addendum, failing acceptance
> tests `tests/acceptance/test_s6_*.py`, branch `spec/s6-router`, PR), then
> coding agent (branch `feat/s6-router`). English. `$HA_CORE_SRC`, `$VENV`
> from the orchestrator. No dev instance, no workflows; the coding agent
> never edits `docs/contract.md` or the acceptance tests.

## Guard-rail (the reason this sprint is "bounded")

The router owns **no timer and no counter of its own** for escalation. The
only clock is the core `alert`'s own `repeat` (each repeat calls the
notifier again); the only state is what the store already keeps per
episode. Every rule below is evaluated at decision time from entities that
exist. Anything that would need `async_call_later` to escalate is out.

## Scope (must)

1. **`escalate_when_nobody_home`** (row, bool, default false). At decision
   time, if no person of the row's audience is `home`, the call's priority
   becomes `critical` for this decision only (bypasses silence and snooze,
   triggers the critical payload of later sprints). `explain` shows it as
   `escalated: nobody_home`.
2. **Escalation audience after N minutes** (row: `escalation_after_minutes`
   int, `escalation_audience` list of persons; both optional, both required
   together). For rows with an `alert_entity`: when a call arrives for an
   episode that started at least N minutes ago (episode start = the alert's
   `idle → on` transition, already tracked for recipients) and the alert is
   still `on`, the escalation audience is added to the audience and the
   priority is raised one step (`normal → high`, `high → critical`; `info`
   stays `info`; `critical` stays). Documented granularity: the escalation
   happens at the first repeat after N minutes, so the effective delay is
   `N` rounded up to the alert's repeat interval. `explain` shows
   `escalated: after_minutes`.
3. **`max_deliveries`** (row, int, optional). Per (episode, person): after
   that many routed deliveries the next ones are dropped with the **new
   reason `max_deliveries`**; the `done` message is not counted and always
   allowed. Reset at episode end.
4. **Acknowledgement authorship.** On every acknowledgement (Companion
   button or `notify_switchboard.acknowledge`) the router records
   `{target, person or null, user_id, at}` and exposes it: new global entity
   `sensor.switchboard_acknowledgements` (state = count today, attributes
   `last` = the record above, `by_target` = last record per slug), plus the
   `acknowledged` event payload gains `user_id` and `person`. The
   acknowledgement record is persisted and restored.
5. **Routing table exposed for user interfaces.** New global entity
   `sensor.switchboard_routing_table` (state = number of rows, attributes
   `targets` = list of `{slug, name, alert_entity, snooze_minutes,
   allow_acknowledge, audience}` and `persons` = list of `{entity_id,
   wake_time, summary}`), so cards stop duplicating `target_map` /
   `wake_time` in their own config. No secrets, no `default_data`.
6. **Priority floor.** Per-person option `min_priority` (default `info`):
   calls below it are dropped with the **new reason `below_min_priority`**.
   Additionally, when a person's silence entity is a `schedule` whose
   currently active block carries `data: {min_priority: <p>}`
   (`$HA_CORE_SRC/homeassistant/components/schedule/__init__.py`, per-block
   `data` exposed as state attributes while the block is active), that
   block silences only calls below `<p>` (reason `silenced`) instead of
   everything. `explain` names the floor in `detail`.
7. **`require_authentication`** (row, bool or null, default null = today's
   rule "high/critical require it"). Explicit true/false overrides the
   default for that row's Companion buttons.

## Out of scope (must not)

Own timers, own repeat counters, changing `alert.repeat`, places, entity
outputs, critical payload (next sprint), cards (separate repository,
separate sprint that consumes items 4–5).

## Acceptance (spec agent writes; coding agent must not modify)

`test_s6_nobody_home.py`, `test_s6_escalation.py` (episode older than N ⇒
audience widened and priority raised at the next call; younger ⇒ not;
alert already off ⇒ not), `test_s6_max_deliveries.py`,
`test_s6_acknowledgements.py` (entity, event payload, persistence),
`test_s6_routing_table.py` (attributes reflect options; no `default_data`
leaked), `test_s6_min_priority.py` (person floor; schedule block floor),
`test_s6_require_authentication.py`, `test_contract.py` (two new entities,
two new reasons, new row/person keys).

## Definition of done

S1–S6 acceptance green unmodified; coverage ≥ 90 % on changed modules;
ruff / mypy / hassfest green; en/fr/es complete (options, entity names,
reasons); `docs/ARCHITECTURE.md` gains the "no own clock" rule in words;
`CHANGELOG.md`; PR lists every core API with its path. Branch
`feat/s6-router`; do not merge, do not tag.
