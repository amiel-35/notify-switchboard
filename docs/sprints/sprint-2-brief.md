# Sprint 2 brief — Notify Switchboard v0.2.0 (UI services)

> For the coding agent. English. You receive: this brief,
> `docs/ARCHITECTURE.md`, `docs/contract.md` (now a v0.2 addendum),
> `docs/ADR/0016-ui-services-and-row-texts.md`, `docs/known-issues.md`, the
> acceptance tests (already in `tests/acceptance/`, `test_s2_*.py` currently
> failing), and a local clone of Home Assistant core 2026.9.1 at
> `$HA_CORE_SRC`. Python/tooling venv: `$VENV`. The orchestrator provides both
> paths before the sprint starts. You never touch the dev HA instance,
> `.github/workflows`, or `docs/contract.md` — that document was already
> amended once for this sprint, under ADR-0016, before you started; do not
> amend it again.

## Goal

Give a future UI (cards, scripts, automations — anything that is not a
Companion push notification) a way to do everything the Companion buttons
already do, plus one new thing they cannot: a temporary, person-wide
silence. Ship this as five domain services with the validation discipline of
a real service (raise, don't just log), and give the router a second source
of message text so observer mode stops being limited to the row's bare name
on every real alert.

## Scope (must)

1. **`notify_switchboard.acknowledge`** — `target` (slug, required). Same
   allow-list as the Companion Acknowledge button (ADR-0009): `alert.turn_off`
   on the row's `alert.*`, only if the row is in the table, has an
   `alert_entity`, and `allow_acknowledge` is true. Unknown `target`, or a
   known target that fails the allow-list, both raise
   `ServiceValidationError`. Logs `context.user_id` from the call.
2. **`notify_switchboard.snooze`** — `target` (slug, required), `minutes`
   (int, required), `person` (optional `person.*`, default: every person in
   the row's audience). `minutes` must be one of the row's configured
   `snooze_minutes`; any other value raises `ServiceValidationError`. An
   explicit `person` not in the row's audience (or not a known person) also
   raises. Persisted the same way Companion-triggered snoozes already are
   (same `Store`, survives a config-entry reload).
3. **`notify_switchboard.unsnooze`** — `target` (slug, required), `person`
   (optional, same default as `snooze`). Clears the matching snooze(s)
   immediately, not just letting them expire.
4. **`notify_switchboard.silence`** — `person` (required), `minutes`
   (positive integer, required, `>= 1`). A new, router-owned, temporary
   silence, independent of and never touching the person's configured
   `silence_entities`. `minutes: 0` raises `ServiceValidationError` — it has
   no defined meaning. Exposed through the existing
   `binary_sensor.<person>_silenced` (true if either this or a configured
   `silence_entities` source is active) and persisted the same way snoozes
   are. Routing to that person is dropped with reason `silenced` (the
   existing reason, no new one) unless `priority == critical` — the same
   bypass already documented for configured silence.
5. **`notify_switchboard.unsilence`** — `person` (required). Lifts a
   temporary silence immediately; a no-op (not an error) if the person was
   not temporarily silenced. Unknown `person` still raises
   `ServiceValidationError`.
6. **`services.yaml`** declaring all five services, with matching
   `en`/`fr`/`es` translations under a `services` key in `strings.json` and
   `translations/*.json` — the doctrine's i18n-from-day-one rule applies to
   services exactly as it already does to `common.*` labels and config-flow
   strings.
7. **Repairs on invalid person/target.** A row's `alert_entity` or
   `audience` naming a person/entity the router does not know about already
   raises issues elsewhere in this integration (unknown output, unknown
   target); extend the same "raise a `repairs` issue, don't just swallow it"
   posture to a service call that fails validation for a reason a user might
   plausibly hit repeatedly through a misconfigured card (e.g. a stale
   `target` a card's config still points at after a routing-table row was
   renamed) — the `ServiceValidationError` itself is enough for a single
   call; a `repairs` issue is warranted if the same invalid `target`/`person`
   recurs, mirroring `MAX_CONSECUTIVE_OUTPUT_MISSES` in spirit (exact
   threshold left to the implementation; no acceptance test pins a number).
8. **Per-row optional texts** — `message`, `done_message`, `default_title`
   (ADR-0016), all absent/`None` by default. `message`/`done_message` are
   templates rendered with the row's alert's current state exposed as
   `alert`; observer mode prefers them over the alert's own attribute (still
   checked first, for forward compatibility) and over the row `name` /
   translated `common.back_to_normal`, in that order. `default_title` is
   used as the outgoing `title` whenever no title is otherwise available —
   a caller who omitted `title` on a legacy `notify.switchboard[_<slug>]`
   call, and every observer-mode-generated message (which never had a
   caller to omit one from).
9. **`sensor.switchboard_routed_today` is unchanged** — no new drop reason,
   no new event type, no new counting rule. A message dropped for temporary
   silence counts exactly like one dropped for configured silence.

## Out of scope (must not)

Cards, voice, calls, HTTP, new external dependencies, blueprints, editing
`docs/contract.md` beyond what ADR-0016 already changed, editing workflows,
touching the dev instance, a `require_authentication` per-row override (a
separate accepted finding, not part of this sprint), a fourth resolution
path for ambiguous Companion device→person snooze (unchanged from Sprint 1).

## Acceptance (tests provided; do not modify them)

`tests/acceptance/test_s2_services.py`, `tests/acceptance/test_s2_row_texts.py`,
and the extended `tests/acceptance/test_contract.py`. Every Sprint 1
acceptance test (`test_s1_routing.py`, `test_s1_actions.py`,
`test_s1_persistence.py`, `test_s1_observer.py`) must still pass unmodified.
They cover: acknowledge allowed and refused (unknown target, row without an
alert); snooze bounded to the row's `snooze_minutes` with an invalid value
refused, both per-person and audience-wide, persisted across a config-entry
reload; unsnooze; a 60-minute silence turning `binary_sensor.<p>_silenced`
on, dropping routed messages with reason `silenced` unless `critical`,
surviving a reload, and expiring; `silence(minutes: 0)` refused; unsilence;
observer mode using a row's `message`/`done_message` templates; a caller
without a title getting the row's `default_title`; the five services
existing after setup with matching `services.yaml` and translation keys.

## Definition of done for this sprint

All acceptance tests green unmodified (Sprint 1's and Sprint 2's); your own
unit tests for the new validation and silence logic ≥ 90 % branch coverage;
ruff/mypy (core config)/hassfest green; `strings.json` + `en/fr/es` complete
for the five new services (`fr` natural, `es` labelled); `CHANGELOG`
Unreleased updated; `docs/ARCHITECTURE.md` updated where behaviour was
decided (in particular: how temporary silence combines with configured
silence in `is_person_silenced`, and the template-rendering context exposed
as `alert`); PR description lists every core API used with its file path in
the core clone. Work on branch `feat/s2-services`; commit conventionally; do
not merge.

## Order

Services and row texts (this sprint) come before `notify-switchboard-cards`
(a separate repository, separate worktree): the cards depend on these
services existing, not the other way around.
