# Sprint 8 brief — Notify Switchboard v0.8.0 ("a first alert without code"; proposed, awaiting the maintainer's go)

> Origin: the 0.7.1 plain-language review by a non-technical reader (4/10 "I could
> configure my first alert without help"): persons are fine (6–7/10), the target
> screen blocks — a code name to invent, a YAML block to paste, a restart, and the
> "recommended" switch shipped off. Spec agent first (ADR-0022, contract v0.8
> addendum — several frozen editor field lists change — and acceptance tests),
> then coding agent. Guard-rails unchanged (proxy, no own timers, nothing on the
> production instance).

## Scope (must)

1. **Code name derived, not typed.** The `target` step drops `slug` from its
   fields: the slug is derived from `name` (slugify, de-duplicated with `_2`…)
   when the target is created, shown read-only afterwards ("Nom en coulisses :
   `fuite_eau` — c'est lui qui apparaît dans les automatisations") and never
   renamed by the editor. `target` = `name, alert_entity, audience, observer_mode`.
   Existing rows keep their slug. Contract: the frozen `target` field list changes
   (ADR-0022); `notify.switchboard_<slug>` stays.
2. **Observer mode on by default, YAML only when off.** New targets start with
   `observer_mode: true`; `target_saved` shows the `alert:` snippet **only** when
   observer mode is off, otherwise a one-line confirmation ("Dès que « {name} »
   se déclenche, {audience} sont prévenus. Rien d'autre à faire."). A target
   without `alert_entity` and observer on gets a hint that it is a plain
   `notify.switchboard_<slug>` for automations.
3. **Menu in three blocks, one entry per thing.** Home Assistant menus are flat,
   so order and wording carry the grouping: "— Les gens de la maison —" is not
   possible as a separator; instead: `person` ("Ajouter quelqu'un"),
   `edit_person` ("Modifier quelqu'un" → one picker, then a **single** screen
   with outputs + silence + a link sentence to the night step), `remove_person`;
   `target` ("Ajouter une alerte"), `edit_target` (one picker, then the basic
   screen with link sentences to advanced/escalation), `remove_target`;
   `general` ("Réglages") which now also hosts `critical_payload` (moved out of
   the default-target step), `ttl`, `test_person`, `test_target`. The
   `edit_*_advanced` and `edit_target_escalation` entries leave the menu and
   become reachable from the edit screens (a boolean "Ouvrir les réglages
   avancés" like `target_saved.advanced`). Titles of menu entries and screens
   are identical.
4. **Confirmation before removal**: the remove pickers show what will be lost
   ("{person} ne sera plus prévenu(e) par : {targets}") and require a checkbox
   "Oui, retirer".
5. **"Créer un horaire de nuit pour {person}"**: in the person screen, a
   boolean that creates a Home Assistant `schedule` helper "Nuit de {person}"
   (22:00–07:00 every day, via the schedule storage collection — verify the
   websocket/collection API in `homeassistant/components/schedule/__init__.py`
   and `helpers/collection.py`) and adds it to `silence_entities`. The helper
   belongs to the user afterwards (doctrine: the router reads, it does not own —
   creating a helper the user owns is allowed; ADR-0022 says so).
6. **Wake time without seconds**: the time field accepts `7:30`; help text
   shows an example.
7. **Per-person summary line** in pickers: "{person} — iPhone de Bob, silence
   22 h–7 h" so a person is understood from one line.

## Out of scope

Any routing change; labels/areas; the deferred items of 0.7.0.

## Acceptance

`test_s8_slug_derived.py`, `test_s8_observer_default.py` (snippet shown only
when observer off), `test_s8_menu.py` (entries, titles = screen titles, no
advanced entries), `test_s8_remove_confirmation.py`, `test_s8_night_schedule.py`
(helper created, linked, owned by the user — deleting the router entry leaves it),
`test_s8_wake_time_format.py`, `test_contract.py` (field lists, defaults).

## Definition of done

As previous sprints, version 0.8.0; a second non-technical French review with a
target score ≥ 7/10 on "first alert without help".
