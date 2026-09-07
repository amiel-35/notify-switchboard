# Sprint 7 brief — Notify Switchboard v0.7.0 (escalation and places, reduced; suite roadmap "S11")

> Reduced by the maintainer on 2026-09-07 after the product review. Spec agent
> first (ADR-0021 — the branch `spec/s6-router` / closed PR #25 holds a fuller
> ADR-0020 draft and tests to **cut down**, not extend), then coding agent.
> Same rules as Sprint 6.

## Guard-rail (unchanged)

The router owns **no timer and no counter of its own**. Every rule below is
evaluated at decision time from entities that exist.

## Scope (must)

1. **`escalate_when_nobody_home`** (target bool, default false): when no person
   of the audience is `home` at decision time, the priority is raised **one
   step** (`info→normal`, `normal→high`, `high→critical`, `critical` unchanged)
   for this decision only. `explain` reports `escalated: nobody_home`.
2. **Scheduled priority floor**: when a person's silence entity is `on` and
   carries a `min_priority` state attribute (a `schedule` block's `data`,
   `components/schedule/__init__.py`), that silence drops only calls below the
   floor (reason `silenced`); unreadable value ⇒ silences everything. `explain`
   names the floor in `detail`. No per-person `min_priority` option.
3. **`sensor.switchboard_routing_table`** (state = number of targets; attributes
   `targets` = `{slug, name, alert_entity, snooze_minutes, allow_acknowledge,
   audience}`, `persons` = `{entity_id, wake_time, summary}`; never
   `default_data`, never outputs); attributes **excluded from the recorder**
   (`_unrecorded_attributes`). The cards drop `target_map`/`snooze_minutes`
   afterwards (cards 0.2.0).
4. **Acknowledgement authorship in the event only**: the `acknowledged` event
   payload gains `user_id` and `person` (canonical `person.user_id` link, `null`
   otherwise). No new entity, no store.
5. **Bare outputs in an audience**: an `audience` entry may be a `notify.*`
   service name (e.g. `notify.kitchen_speaker`, `notify.tablet_toast`); it has
   no presence, no silence, no snooze, no deferral, no TTL, no buttons, receives
   exactly the caller/row data, and takes part in episodes like a person output
   for the `done` message. No `places` list, no schedule, no new reason, no new
   menu — the audience selector simply offers `notify.*` services alongside
   persons. `explain` lists them under `outputs`.
6. **Entity outputs**: an output that is a `notify` **entity id** (Alexa
   Devices, Telegram, `NotifyGroup`) is delivered with `notify.send_message`
   (`message`, `title`; `data` cannot be carried — documented); missing entity
   handled like a missing service; recursion guard extended.
7. **Critical payload, translated, per OS** — for `mobile_app_*` outputs the
   router **removes its own `priority` key** from the forwarded `data`
   (it is a router input, not a Companion key; Android reads `data.priority`
   and only knows `high`) and, when the effective priority is `critical`, adds
   the keys the Companion documentation gives
   (https://companion.home-assistant.io/docs/notifications/critical-notifications/):
   iOS `push.sound: {name: default, critical: 1, volume: 1.0}` (or
   `push.interruption-level: critical`), Android `ttl: 0`, `priority: high`,
   `channel: alarm_stream`. OS from the matching `mobile_app` entry's
   registration `os_name` (`components/mobile_app/const.py`); unknown OS ⇒ both
   sets. Caller-set keys win. Global option `critical_payload` (default on).
   Contract change: `data.priority` no longer reaches `mobile_app_*` outputs
   (ADR records it).

## Out of scope (deferred, decided)

Escalation after N minutes (needs episode timestamps = state machine; a
blueprint with a template `delay_on` alert is the native answer — document it
in `docs/blueprints.md`), `max_deliveries` (a counter), per-target
`require_authentication`, per-person `min_priority`,
`sensor.switchboard_acknowledgements`, labels/areas/floors, a `places` object.

## Acceptance

`test_s7_nobody_home.py`, `test_s7_scheduled_floor.py`,
`test_s7_routing_table.py` (incl. unrecorded attributes),
`test_s7_ack_authorship.py`, `test_s7_bare_outputs.py`,
`test_s7_entity_outputs.py`, `test_s7_critical_payload.py` (iOS, Android,
unknown OS, caller keys preserved, option off, `priority` stripped),
`test_contract.py`.

## Definition of done

As Sprint 6, version 0.7.0, plus real-device evidence requested from the
maintainer for one critical push on iOS (documented in known-issues until
observed).
