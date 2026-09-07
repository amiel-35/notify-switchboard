# Sprint 4 brief — Notify Switchboard v0.4.0 (zero-config and explainability; suite roadmap "S8")

> Spec agent first (ADR-0018, contract v0.4 addendum, failing acceptance
> tests `tests/acceptance/test_s4_*.py`, branch `spec/s4-router`, PR), then
> coding agent (branch `feat/s4-router`). English. Paths from the
> orchestrator: `$HA_CORE_SRC` (core 2026.9.1), `$VENV`. Nobody touches the
> dev instance or `.github/workflows`; the coding agent never edits
> `docs/contract.md` or the acceptance tests.

## Goal

A newcomer who installs the router from HACS must get a working
`notify.switchboard` within minutes without typing a single service name,
and must be able to ask the router *why* a message would or would not
reach someone. Every feature here is discovery, defaults and diagnosis —
no new routing semantics.

## Scope (must)

1. **`notify_switchboard.explain`** — `SupportsResponse.ONLY`. Fields:
   `target` (slug, required), `priority` (optional, else the row's default),
   `person` (optional `person.*`, else the whole audience). Response, per
   person: `decision` ∈ `routed` | `deferred` | `dropped`; for `deferred`
   the ISO `until`; for `dropped` the `reason` (existing reasons only) and a
   human-readable `detail` string (translated: which silence entity is on,
   snooze until when, presence rule vs current state); the list of `outputs`
   that would be called and `missing_outputs`. Pure evaluation: no service
   call, no counter, no event, no store change. Unknown target/person raise
   `ServiceValidationError` like the other services.
2. **Companion outputs discovered, not typed.** In the person step of the
   options flow, `outputs` becomes a multi-select (`SelectSelector`,
   `multiple`, `custom_value: true` so a not-yet-existing service can still
   be typed) whose options are every existing `notify.*` legacy service
   except `switchboard*`. Services belonging to *this* person's phones are
   listed first and labelled (translated) "this person's device": the link is
   `person.user_id` ↔ the `user_id` stored in each `mobile_app` config
   entry's data (verify in `$HA_CORE_SRC/homeassistant/components/mobile_app/`
   how the registration keeps `user_id` and `device_name`, and how
   `notify/legacy.py` + `mobile_app/notify.py` derive the service name from
   the device name via `slugify`). When a new person is added and has
   phones, those services are pre-selected.
3. **Silence entities proposed.** Same step: `silence_entities` becomes an
   `EntitySelector` (`multiple`, domains `binary_sensor`, `schedule`,
   `input_boolean`) with, pre-selected for a new person, the `binary_sensor`
   entities that belong to that person's `mobile_app` devices and whose
   entity id or translation key contains `focus` (iOS Focus). Android's
   "Do Not Disturb" is a `sensor` with several states and is *not*
   auto-proposed; the quickstart shows the one-line template
   `binary_sensor` for it.
4. **Default target created and kept in sync.** When the first person is
   added and the routing table is empty, the router creates a row
   `default` (translated name, `class` general, priority `normal`,
   presence `always`, no alert, `managed: true`) with that person as
   audience and sets it as `default_target`. While `managed` is true, the
   row's audience is every configured person; editing the row in the UI
   (any field) clears `managed`. `notify.switchboard` therefore works as
   soon as one person with one output exists.
5. **Consistency repairs** (all translated, non-fixable, raised once,
   deleted when the condition disappears on reload): `person_without_outputs`
   (a person in any audience has no outputs), `alert_entity_missing` (a row's
   `alert_entity` is not in the state machine 60 s after start), and the
   existing unknown-output issue kept as is.
6. **"Test this person / this target"** — options-flow steps (menu entries)
   that send one translated test message through the *real* routing path
   (counted and evented like any message, `data.tag: switchboard-test`) and
   then show the `explain` result for that call in the step description
   (`description_placeholders`).
7. **`alert:` snippet shown after saving a row** — the confirmation step of
   the row editor shows, via `description_placeholders`, a ready-to-paste
   YAML block (`alert:` with `notifiers: [switchboard_<slug>]`, the row's
   `alert_entity` if any, a `repeat` example). Braces in the *value* of a
   placeholder are fine; never put a braced placeholder in single quotes in
   `strings.json` (hassfest rule).
8. **Docs rewritten around the zero-config path.** `docs/quickstart.md`:
   1) add the integration, 2) add a person (phones and Focus pre-selected),
   3) either pick an existing `alert.*` in observer mode (no YAML, no
   restart) or paste the generated snippet, 4) test from the options menu,
   5) `explain` in Developer tools. `README.md`: My Home Assistant buttons
   (`https://my.home-assistant.io/redirect/hacs_repository/?owner=amiel-35&repository=notify-switchboard&category=integration`
   and the config-flow start redirect), same structure as before otherwise.
   `docs/ARCHITECTURE.md`, `CHANGELOG.md`, `docs/known-issues.md`.

## Out of scope (must not)

TTL, summaries, early flush, escalation, places, labels/areas (later
sprints); cards; any change to the frozen event types or drop reasons; an
in-app import wizard from other projects.

## Acceptance (spec agent writes; coding agent must not modify)

`test_s4_explain.py` — every decision kind with its `detail`, no side
effects (counters, events, store unchanged), unknown target/person raise.
`test_s4_discovery.py` — with two `mobile_app` entries (one linked to the
person's user id) and one unrelated `notify.*` service, the person step's
schema lists the person's service first and pre-selects it; Focus
binary_sensor of that device pre-selected; custom value accepted.
`test_s4_default_target.py` — first person ⇒ `default` row + default target;
second person joins its audience; editing the row stops the sync.
`test_s4_repairs.py` — the two new issues raised and cleared.
`test_s4_test_message.py` — the test step routes a message with the test
tag and its result is visible in the step description.
`test_contract.py` — `explain` added to the frozen service names with its
response keys.

## Definition of done

S1–S4 acceptance green unmodified; unit coverage ≥ 90 % on changed
modules; ruff / mypy / hassfest green; en/fr/es complete (service,
response labels, repairs, options-flow steps, test message); docs of
item 8; PR lists every core API with its path. Branch `feat/s4-router`; do
not merge, do not tag.
