# Sprint 6 brief — Notify Switchboard v0.6.0 (consolidation; suite roadmap "S10")

> Decided by the maintainer on 2026-09-07 after an independent product review of
> 0.1 → 0.5.1: **stop adding, consolidate.** Spec agent first (ADR-0020, contract
> v0.6 addendum, acceptance tests on the *shape* of the options flow and on the
> removed/renamed things), then coding agent. `$HA_CORE_SRC`, `$VENV` from the
> orchestrator. Nobody touches the dev instance or `.github/workflows`; the coding
> agent never edits `docs/contract.md`, `docs/ADR/` or acceptance test files.

## Goal

A newcomer meets **five fields** to create their first target, one vocabulary,
one honest quickstart, and a router whose documented promises match its code.
No new routing semantics.

## Scope (must)

1. **Target editor in two steps.** `target` step = `slug`, `name`, `alert_entity`,
   `audience`, `observer_mode` (five fields, that is all). A second, optional
   `target_advanced` step (reached from a menu entry "Advanced settings of a
   target", and offered as a link sentence after saving) holds everything else:
   `default_priority`, `presence_rule`, `allow_acknowledge`, `snooze_minutes`,
   `default_data`, `message`, `done_message`, `default_title`, `clear_done`.
   Defaults unchanged. The `target_saved` snippet step stays after the basic step.
2. **Person editor likewise**: `person_outputs` keeps `outputs` and
   `silence_entities`; `wake_time`, `summary` move to a `person_advanced` step.
   Wake time default: none (the router then uses the silence entity's own end —
   already the 0.5 early-flush behaviour — and, with no silence entity, delivers
   immediately, as today).
3. **Remove the dead `class` row key.** Nothing reads it (`router.py` stores it,
   no consumer). Removed from the schema, strings, docs, examples; a stored value
   is ignored, never migrated, never shown. ADR records it; `test_contract.py`
   pins that `class` is absent from the row keys.
4. **TTL defaults are documented defaults, not frozen values.** Contract v0.6
   addendum reclassifies `ttl_minutes` defaults (`info` 120, `normal` 720, `high`
   none) as "defaults that a minor version may change", exposed in the general
   options step with the same values.
5. **One vocabulary.** "target" everywhere for a routing-table row (strings,
   README, quickstart, ARCHITECTURE, known-issues, error messages); the legacy
   `target:` list of the notify service is called "the notify `target` list" the
   one time it is mentioned; "person" everywhere for `person.*`; silence /
   snooze / wake time / quiet hours each defined once in a **Glossary** section
   of README that the other docs link to. `fr`/`es`: "cible", "personne" etc.
   consistently.
6. **Quickstart and README aligned**: one duration claim (measure the real path
   on a fresh instance: it is "ten minutes" including the YAML `alert:` and a
   restart, say so), observer mode as the primary path in README too (the
   `notifiers:` example second), the five-line core `notify: platform: tts`
   recipe for speakers (already there), a "Migrating an existing installation"
   guide (`docs/migration-guide.md`): where to start when you have N inline
   `notify.mobile_app_x` calls and M `alert:` blocks, one target per alert, the
   `default` target first, `explain` to check, rollback = remove the row.
7. **ARCHITECTURE and known-issues truthful**: roadmap rows rewritten to the
   decided sequence (0.6.0 consolidation, 0.7.0 escalation-and-places reduced,
   later: labels, per-row auth, intents), "Suite S3/S4 Cast/AirPlay" marked
   superseded (done), no "planned for S7" leftovers; known-issues entries that
   describe accepted design (temporary silence owned by the router; episodes as a
   small persisted state; `not_in_audience` uncounted) moved to a new
   `docs/accepted-deviations.md` with the doctrine principle each one bends and
   why the maintainer accepted it.
8. **Upstream issue drafts** in `docs/upstream/` (English, ready to paste; the
   maintainer files them): `helpers/event.py` `cancel_on_shutdown` inoperative
   for `async_call_later` handles (with the reproduction), and `AlertEntity`
   never re-reading its watched entity at startup (with the consequence for
   long-lived alerts). Cite core lines.
9. **Cards README** (separate repository, separate small PR by another agent):
   "planned for 0.2.0" wording removed; feature matrix by router version
   (0.2 services, 0.4 explain, 0.5 summary tag); `target_map`/`snooze_minutes`
   still required until the routing-table entity ships in 0.7.0.

## Out of scope (must not)

Any new routing rule, entity, service or drop reason; escalation, places,
labels (0.7.0); store migrations beyond ignoring `class`.

## Acceptance (spec agent writes; coding agent must not modify)

`test_s6_target_editor.py` — the `target` step schema has exactly the five
fields; `target_advanced` holds the rest with unchanged defaults; a target
created through the basic step routes exactly as one created in 0.5 with
defaults; editing through advanced keeps basic values.
`test_s6_person_editor.py` — same split; a person without `wake_time` and with
a `schedule` silence flushes at the schedule's end (early flush) and is never
stuck.
`test_s6_class_removed.py` — a stored row with `class` loads and routes; the
key is absent from the schema and from the routing-table exposure (diagnostics).
`test_s6_vocabulary.py` — `strings.json` never uses "row" or "rule" for a
target; every `issues`/`exceptions` string that names a target uses "target".
`test_contract.py` — `class` absent; TTL defaults documented as changeable.

## Definition of done

S1–S6 acceptance green unmodified; unit coverage ≥ 90 % on changed modules;
ruff / `ruff format --check .` / mypy / hassfest; en/fr/es parity; version
0.6.0; the migration guide and glossary reviewed by the reviewer *as a
newcomer*; PR lists every core API with its path. Branch `feat/s6-router`;
do not merge, do not tag.
