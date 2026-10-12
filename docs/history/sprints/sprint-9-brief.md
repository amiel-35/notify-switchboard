# Sprint 9 brief — Notify Switchboard v0.9.0 ("one-click automation, quiet all-clear"; maintainer's go on 2026-10-12)

> Origin: the second non-technical French review of 0.8.0 (7/10 on "I could
> configure my first alert without help") and a real-world test at the
> maintainer's home on 2026-10-12. Three findings: an alert tied to no Home
> Assistant alert still ends on "build an automation by hand"; the "back to
> normal" message of a `critical` target rings like the alarm itself; and
> observer mode, recommended by default since 0.8.0, silently drops the
> `repeat` reminders of the Home Assistant alert. Spec agent first (ADR-0023,
> contract v0.9 addendum, acceptance tests), then coding agent. Guard-rails
> unchanged: pure proxy, no timer of the router's own, nothing on any
> production instance.

## Scope (must)

1. **One-click automation for an alert without an `alert.*`.** Ship an
   automation blueprint inside the integration package,
   `custom_components/notify_switchboard/blueprints/<lang>/alert_from_a_sensor.yaml`
   (`en`, `fr`, `es`, identical logic, translated texts). Inputs:
   `trigger_entity`, `trigger_to` (default `on`), `alert_name` (the automation
   name), `message`, `done_message`, `priority` (default: the alert's own).
   When the options flow shows `target_ready_manual`, it copies the blueprint
   in the instance language to
   `<config>/blueprints/automation/notify_switchboard/alert_from_a_sensor.yaml`
   if — and only if — no file is there, the way core's own
   `DomainBlueprints.async_populate` copies its examples
   (`homeassistant/components/blueprint/models.py`). The screen then links to
   the blueprint list (`/config/blueprint/dashboard`), where one click on the
   row opens the automation editor on it (`ha-blueprint-overview.ts`,
   `_handleRowClicked` → `showAutomationEditor({use_blueprint})`, frontend
   20260826.6), and tells the user which automation name to type. If the copy
   fails, the link is a My Home Assistant `blueprint_import` link to the same
   file on GitHub. The manual explanation (`{service}`) and the `alert:` block
   (`{snippet}`) stay as the fallback. The file belongs to the user: never
   overwritten, never deleted.
2. **The all-clear does not ring like the alarm.** A new optional target key
   `done_priority` (absent = `normal`), shown on `target_advanced` next to the
   done text. Every *done* message is routed at no more than that priority,
   and never louder than it would otherwise have been: observer mode's
   `→ idle` message, a call carrying `data.switchboard_done: true`, and — new —
   the call a Home Assistant `alert:` makes through its `notifiers:` while it
   is ending (recognised at call time: the live `AlertEntity` already reports
   `idle` while the state machine still holds `on`/`off`, because core's
   `end_alerting` clears `_firing` before awaiting the done message and writes
   the state after). That last one changes priority only: same tag as before
   (it still replaces the alert's notification on the phone), no episode
   filter. A deferred done message keeps its cap at its flush.
3. **Observer mode and reminders, said plainly.** Observer mode routes
   `idle → on` and `→ idle`, never a `repeat` (there is no state change to
   observe). Say so on `observer_mode`'s help (`target`, `target_edit`), on
   `target_ready`, on `target_saved` (that path does carry reminders), in the
   README, the quickstart and the doctrine. ADR-0023 records a
   doctrine-compatible way for observer mode to follow repeats (the alert's
   own `notifiers:` calls, filtered) as a proposal, not implemented.

## Out of scope

Escalation after N minutes, `max_deliveries`, labels/areas, voice adapters.
Any change to the `not_notified` filter, the default tags or the tidy-up of a
`notifiers:` target.

## Acceptance

`test_s9_done_priority.py` (a real core `alert:` with `notifiers:` on a
`critical` target: the first message and a `repeat` are critical, the
`done_message` is `normal` and carries no critical payload; observer done and
`switchboard_done` capped; `done_priority` raises or lowers the ceiling; an
`info` target's done stays `info`; a capped done message is silenced like any
`normal` one and stays capped when deferred and flushed),
`test_s9_blueprint.py` (the three packaged files are valid automation
blueprints with the same inputs and the same logic; `target_ready_manual`
installs the instance-language file once, never overwrites it, links to it and
names the automation name; a failed copy falls back to the import link; an
automation built from the installed blueprint routes the sensor's change, and
its done message is a capped done message),
`test_s9_observer_repeats.py` (observer mode routes no `repeat`; the
`notifiers:` path does; the help texts say so in `en`/`fr`/`es`),
`test_contract.py` (`done_priority` key and default, the ten fields of
`target_advanced`, the frozen blueprint path and input names).

## Definition of done

As previous sprints: ruff, ruff format, mypy, full pytest green; `en`/`fr`/`es`
complete with menu titles = screen titles; CHANGELOG 0.9.0 in house style;
manifest 0.9.0. A third non-technical French review targets ≥ 8/10 on "first
alert without help". End-to-end check on the maintainer's **dev** instance
only.
