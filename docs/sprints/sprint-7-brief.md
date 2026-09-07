# Sprint 7 brief — Notify Switchboard v0.7.0 (places, entity outputs, critical payload, labels; suite roadmap "S11")

> Spec agent first (ADR-0021, contract v0.7 addendum, failing acceptance
> tests `tests/acceptance/test_s7_*.py`, branch `spec/s7-router`, PR), then
> coding agent (branch `feat/s7-router`). English. `$HA_CORE_SRC`, `$VENV`
> from the orchestrator. No dev instance, no workflows; the coding agent
> never edits `docs/contract.md` or the acceptance tests.

## Scope (must)

1. **Places.** New options list `places`: `{id (slug), name, outputs
   (list of notify services or notify entities), schedule_entity
   (optional)}`. A row's `audience` may contain `place:<id>`. Decision for a
   place: no presence rule, no silence, no snooze, no deferral, no TTL; if
   `schedule_entity` is set and `off` the call is dropped with the **new
   reason `place_closed`**; otherwise routed to the place's outputs with the
   same merged `data` (no Companion buttons). Places never appear in
   recipients-of-episode logic for `done` filtering (they always get the
   `done` message if they got the episode's first message). `explain` and
   `sensor.switchboard_routing_table` include places. Options flow: a
   "Places" menu entry with the same discovery selector as person outputs.
2. **Entity outputs.** An output (person or place) that is an entity id of
   domain `notify` (e.g. `notify.living_room_speak` from Alexa Devices, a
   Telegram entity, a `NotifyGroup`) is delivered with
   `notify.send_message` (`message`, `title`; `data` cannot be carried —
   `$HA_CORE_SRC/homeassistant/components/notify/__init__.py`,
   `NotifyEntityFeature.TITLE`), everything else keeps the legacy call. A
   missing entity is handled exactly like a missing legacy service
   (retries, repair). Recursion guard extended to `notify.switchboard*`
   entities. Documented plainly: buttons and `data` keys are lost on entity
   outputs.
3. **Critical payload per OS.** For a `mobile_app_*` legacy output, when the
   *effective* priority is `critical`, the router adds — only where the
   caller did not set the key — the Companion keys that make the phone
   sound through silent mode: iOS `data.push.sound = {name: "default",
   critical: 1, volume: 1.0}` and `data.push["interruption-level"] =
   "critical"`; Android `data.ttl = 0`, `data.priority = "high"`,
   `data.channel = "Critical"`. The OS comes from the matching `mobile_app`
   config entry's registration data (`os_name`; verify the key in
   `$HA_CORE_SRC/homeassistant/components/mobile_app/`); unknown OS ⇒ both
   sets are added (harmless on the other platform — verify against the
   Companion documentation and cite it). Global option `critical_payload`
   (default on) disables it.
4. **Label audiences.** An `audience` entry `label:<label_id>` resolves, at
   decision time, to every `person.*` entity carrying that label in the
   entity registry (`$HA_CORE_SRC/homeassistant/helpers/entity_registry.py`,
   `labels` on `RegistryEntry`; `helpers/label_registry.py`). Unknown label
   ⇒ empty set and a repair `unknown_label` raised once. Areas and floors
   are **not** supported (persons are not in rooms); say so in the docs.
   `explain` lists the resolved persons.
5. **Options flow and docs.** Audience selector accepts persons, places and
   labels (three grouped option lists); `docs/ARCHITECTURE.md`, `README.md`
   ("Places", "Entity outputs", "Critical notifications"), `CHANGELOG.md`,
   `docs/known-issues.md`.

## Out of scope (must not)

Area/floor audiences, `data` on entity outputs (core limitation), voice,
cards.

## Acceptance (spec agent writes; coding agent must not modify)

`test_s7_places.py` (routing, `place_closed`, no buttons, `done` always
delivered to a place that got the first message), `test_s7_entity_outputs.py`
(`send_message` called with message/title; missing entity ⇒ same path as
missing service; recursion refused), `test_s7_critical_payload.py` (iOS,
Android, unknown OS, caller-set keys preserved, option off),
`test_s7_labels.py`, `test_contract.py` (new reason, new keys, `places`
in the routing-table entity).

## Definition of done

S1–S7 acceptance green unmodified; coverage ≥ 90 % on changed modules;
ruff / mypy / hassfest green; en/fr/es complete; PR lists every core API
with its path and the Companion documentation pages used. Branch
`feat/s7-router`; do not merge, do not tag.
