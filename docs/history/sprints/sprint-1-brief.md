# Sprint 1 brief — Notify Switchboard v0.1.0 (router)

> For the coding agent. English. You receive: this brief, `docs/ARCHITECTURE.md`,
> `docs/contract.md`, the ADRs, the acceptance tests (already in `tests/acceptance/`,
> currently failing), and a local clone of Home Assistant core 2026.9.1 at
> `$HA_CORE_SRC`. Python/tooling venv: `$VENV`. The orchestrator provides both
> paths before the sprint starts. You never touch the dev HA
> instance, `.github/workflows`, or `docs/contract.md`.

## Goal

Ship a usable router: an `alert` that lists `switchboard_<target>` in its
`notifiers` is routed **per person** (presence, silence, snooze, priority),
with secure Acknowledge/Snooze buttons on Companion notifications, persisted
snoozes, an observer mode, diagnostic entities, and a complete config flow.
Everything in `docs/contract.md` v0 must hold.

## Scope (must)

1. **Routing table (config/options flow)** — rows = targets. Row fields: `slug`
   (public service suffix), `name`, `class` (free text, used for grouping and
   translations of nothing), `default_priority`, `alert_entity` (optional
   `alert.*`), `audience` (list of `person.*`), `presence_rule`
   (`always|home_only|away_only`), `allow_acknowledge` (bool),
   `snooze_minutes` (list of ints, empty = no snooze), `default_data` (yaml/json
   object merged under caller data), `observer_mode` (bool).
2. **Persons** — per `person.*`: list of output `notify.*` services; optional
   silence entities (`schedule.*`, `input_boolean.*`, any entity whose `on`
   means "silent"); `wake_time` (time; end of night silence used for deferrals).
3. **Legacy notify platform** — `notify.switchboard` + `targets` property
   yielding one service per row (`notify.switchboard_<slug>`). Decision engine
   in `router.py` as pure functions (no `hass` inside the decision itself) so
   it is unit-testable; side effects in a thin `Dispatcher`.
4. **Priority** — `info|normal|high|critical`; `critical` bypasses silence and
   snooze; `high|critical` sets `authenticationRequired: true` on Companion
   actions unless the row overrides.
5. **Buttons** — add `actions` to Companion outputs (only services whose name
   starts with `notify.mobile_app_`): `Acknowledge` when the row has an alert
   and allows it; one `Snooze <n>` per configured duration. Labels via
   `async_get_translations(hass, hass.config.language, "common", {DOMAIN})`;
   add a `common` section to `strings.json` (en/fr/es).
6. **Callbacks** — listen to `mobile_app_notification_action`; parse
   `switchboard:<ack|snooze>:<slug>[:<minutes>]`; acknowledge = `alert.turn_off`
   on the row's alert **only if that alert is in the table**; snooze = store
   `(person, slug) -> expiry` in `homeassistant.helpers.storage.Store` (v1),
   restore on startup, expire lazily. Identify the person from the event's
   `device_id` → device registry → the `mobile_app` config entry → match the
   person whose outputs include that `notify.mobile_app_*` service; if
   ambiguous, snooze for all persons in the audience of the row and log it.
7. **Night deferral** — if dropped for `silenced` and the person has
   `wake_time`, queue the message and deliver at `wake_time` (dedupe by `tag`;
   keep only the latest per (person, slug, tag)); persist the queue.
8. **Observer mode** — for rows with `observer_mode`, subscribe to the row's
   alert state (`async_track_state_change_event`): `idle→on` route the alert's
   `message` attribute if present else the row name; `→idle` route the
   `done_message` if the alert exposes one, else a translated "back to normal".
9. **Entities** — as in the contract §3.5 (`binary_sensor.<p>_silenced`,
   `sensor.<p>_last_notification`, `sensor.<p>_active_snoozes`,
   `sensor.switchboard_routed_today`, `sensor.switchboard_dropped_today` with
   `reasons` attribute, `event.switchboard_delivery`). One device for the
   router, one per person (via the person's device? no — create a virtual
   device per person named after the person). Counters reset at local midnight.
10. **Robustness** — a failing output logs and continues; outputs not yet
    registered at startup are retried on the next call (no repair); an output
    missing for >3 consecutive calls raises one `repairs` issue (fixable by
    editing the row); recursion (`notify.switchboard*` as output) rejected in
    the flow (`errors`) and at runtime (dropped, reason `recursion`).
11. **Diagnostics** — `async_get_config_entry_diagnostics` with
    `async_redact_data` on message bodies; include table, persons, snoozes,
    last 20 decisions.
12. **Migration** — `ConfigEntry.version = 1`, `minor_version = 1`,
    `async_migrate_entry` present (no-op for now, tested).
13. **NotifyEntity** — kept; routes to the default row with `normal`.

## Out of scope (must not)

Voice, calls, HTTP, new external dependencies, cards, blueprints, editing
`docs/contract.md`, editing workflows, touching the dev instance.

## Acceptance (tests provided; do not modify them)

`tests/acceptance/test_s1_routing.py`, `test_s1_actions.py`, `test_s1_persistence.py`,
`test_s1_observer.py`, `test_contract.py`. They cover: home/away routing;
silence vs `critical`; acknowledge allowed/refused; snooze retention and
expiry across a simulated restart; night deferral delivery at `wake_time`
across midnight and a DST change (`Europe/Paris`, 2026-10-25); failing
output isolation; recursion rejection; observer mode transitions; contract
names.

## Definition of done for this sprint

All acceptance tests green unmodified; your own unit tests for `router.py`
≥ 90 % branch coverage; ruff/mypy (core config)/hassfest green; `strings.json`
+ `en/fr/es` complete (`fr` natural, `es` labelled); `CHANGELOG` Unreleased
updated; `docs/ARCHITECTURE.md` updated where behaviour was decided; PR
description lists every core API used with its file path in the core clone.
Work on branch `feat/s1-router`; commit conventionally; do not merge.

## Lessons from neighbouring projects (see `docs/research/`, French)

- Slugs: normalise with `homeassistant.util.slugify`, reject collisions in the flow; test accents and apostrophes.
- Nothing in RAM only: snoozes, deferrals, tag de-duplication go through `Store`.
- Never touch the recorder database directly.
- A message outside its window is never lost: deferred, or counted as a drop with a reason.
- No custom panel; config flow + options flow only. Validate the full schema before writing options (concurrent edits).
- i18n from v0.1 (`en`, `fr`, `es`).
- Keep the door open for a "script" output later (a `notify` group or a notify facade of a script) — a frequent request elsewhere; do not implement now.
