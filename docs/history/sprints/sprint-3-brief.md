# Sprint 3 brief — Notify Switchboard v0.3.0 (debts and robustness; suite roadmap "S7")

> Two agents, in this order: a **spec agent** (writes ADR-0017, the contract
> addendum and the acceptance tests `tests/acceptance/test_s3_*.py`, all
> failing, on branch `spec/s3-router`, and opens a PR) and then a **coding
> agent** (branch `feat/s3-router`, makes them pass). English. Paths given by
> the orchestrator: core clone 2026.9.1 at `$HA_CORE_SRC`, venv at `$VENV`.
> Nobody touches the dev HA instance, `.github/workflows`, or (for the coding
> agent) `docs/contract.md` and the acceptance tests.

## Goal

Pay the debts that block a serious HACS review and make the router robust
under real load, without adding a single new user-facing concept. Every item
below is either a documented known issue, a wrong self-assessment, or a
correctness gap found by the 07/09 review of the code base.

## Scope (must)

1. **Translated entity names, frozen entity ids.** Every entity of this
   integration gets `_attr_has_entity_name = True` and a `translation_key`
   with `entity.<platform>.<key>.name` strings in `strings.json` and
   `translations/{en,fr,es}.json`, so a French or Spanish instance shows
   localized friendly names. The **entity ids do not change**: the contract
   freezes `binary_sensor.<person>_silenced`, `sensor.<person>_last_notification`,
   `sensor.<person>_active_snoozes`, `sensor.switchboard_routed_today`,
   `sensor.switchboard_dropped_today`, `sensor.switchboard_deferred_today`,
   `event.switchboard_delivery`. Use `Entity.suggested_object_id`
   (`homeassistant/helpers/entity.py`, property at ~line 748 in 2026.9.1) so
   the object id is generated from the frozen English form regardless of the
   instance language; cite the exact core mechanism in the PR. Existing
   registry entries keep their ids anyway; the requirement is for *new*
   installs in any language. Per-person entities are named after the
   person's friendly name plus the translated suffix.
2. **`sensor.switchboard_deferred_today` enters the frozen names** (it has
   existed in code since 0.1.0 and in `ARCHITECTURE.md`, never in the
   contract). ADR-0017 records it; `tests/acceptance/test_contract.py` pins it.
3. **Parallel fan-out with a per-output timeout.** Today
   `dispatcher.py` awaits each output of each person sequentially and calls
   `hass.services.async_call(..., blocking=True)` with no timeout. Change to:
   all (person, output) deliveries of one routing decision run concurrently
   (`asyncio.gather(..., return_exceptions=True)`), each wrapped in
   `asyncio.timeout(OUTPUT_TIMEOUT_SECONDS)` (constant, 30 s). A timeout or
   an exception on one output is recorded exactly like a failed delivery is
   today (same reason, same counters, same `event.switchboard_delivery`
   payload) and never delays or prevents the others. Order of events is not
   promised; counts are.
4. **`person.user_id` is the canonical link for Companion callbacks.** The
   `mobile_app_notification_action` handler resolves the acting person by
   `context.user_id` ↔ `person.user_id` first (core: `mobile_app/helpers.py`
   `registration_context`, `person/__init__.py` exposes `user_id`); the
   `device_id` path stays as a fallback and is logged at DEBUG as such. New
   repairs issue `person_without_user_id` (severity warning, translated,
   fixable = false) raised once per person who is in the audience of a row
   that adds Companion buttons (`allow_acknowledge` or non-empty
   `snooze_minutes`) but whose `person.*` has no `user_id`; deleted when the
   condition disappears (on reload).
5. **Services registered in `async_setup`, not `async_setup_entry`.** The
   quality-scale rule `action-setup` requires it; a service called while no
   entry is loaded raises `ServiceValidationError` with a translated message
   (`exceptions.no_loaded_entry`). Single-entry integration: the services
   act on the loaded entry.
6. **`done_message` order fixed in one place.** `docs/contract.md` and
   ADR-0016 disagree with `tests/acceptance/README.md` and
   `docs/sprints/sprint-2-brief.md` on the fallback order (known issue). The
   contract's order is authoritative: row `done_message` template → the
   alert's own `done_message` attribute → translated `common.back_to_normal`.
   The spec agent pins it with an acceptance test; the coding agent fixes the
   two other documents.
7. **Quality scale told the truth.** `quality_scale.yaml`: `action-setup`
   becomes `done` (after item 5), `docs-actions` becomes `done` (the
   `services.yaml` exists), `entity-translations` becomes `done` (after
   item 1), `brands` becomes `done` with the note "bundled in-repo icon (HA
   2026.3+)", and **every silver and gold rule is assessed** (`done`, `todo`
   with a one-line reason, or `exempt` with a one-line reason) — no more
   "not assessed yet".
8. **Documentation refreshed.** `README.md` no longer says the quickstart and
   blueprints are "planned for S7"; `docs/known-issues.md` entries resolved by
   this sprint are removed, the remaining ones kept; `docs/ARCHITECTURE.md`
   roadmap updated (S3 done, next: S4 zero-config, S5 night, S6 escalation,
   S7 places); `CHANGELOG.md` Unreleased filled.

## Out of scope (must not)

Any new routing concept (TTL, summaries, escalation, places, labels — later
sprints), cards, voice, workflows, the dev instance, editing the frozen
acceptance tests (coding agent), capturing a real Companion callback (needs
a physical phone; stays a known issue).

## Acceptance (spec agent writes; coding agent must not modify)

`tests/acceptance/test_s3_entities.py` — translated names: with the
instance language set to `fr` (see how core tests set
`hass.config.language` / translations cache), the friendly names are French
and the entity ids are exactly the frozen English ones; same with `en`;
`sensor.switchboard_deferred_today` exists.
`tests/acceptance/test_s3_fanout.py` — three outputs where one hangs
longer than the timeout (patch the constant to ~0.1 s in the test): the two
others are delivered, counters and `event.switchboard_delivery` record one
failure, total wall time is bounded by the timeout, not the sum.
`tests/acceptance/test_s3_callbacks.py` — a callback whose
`context.user_id` matches a person is resolved to that person even when
`device_id` is absent or points elsewhere; a person without `user_id` in a
row with buttons raises the `person_without_user_id` repair once; fixing
the person and reloading removes it.
`tests/acceptance/test_s3_services.py` — the five services exist right
after `async_setup` with no config entry; calling one then raises
`ServiceValidationError` with translation key `no_loaded_entry`.
`tests/acceptance/test_s3_done_message.py` — the fallback order of item 6.
`tests/acceptance/test_contract.py` — extended with `deferred_today` and
the entity-id freeze under a non-English language.

## Definition of done

All S1, S2 and S3 acceptance tests green unmodified; unit coverage of the
changed modules ≥ 90 %; ruff / mypy (core config) / hassfest green;
`strings.json` + en/fr/es complete (entities, repair, exception); docs of
item 8; PR description lists every core API used with its path in
`$HA_CORE_SRC`. Conventional commits on `feat/s3-router`; do not merge, do
not tag.
