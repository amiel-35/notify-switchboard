# ADR 0016: UI services (acknowledge/snooze/silence) and per-row message texts

Date: 2026-09-07

## Status

Accepted.

## Context

Sprint 2 opens the door to `notify-switchboard-cards`, a Lovelace UI in a
sibling repository. A card cannot originate a
`mobile_app_notification_action` event the way a real Companion push
notification does: it has no device registration, no webhook, and no
`context.user_id` tied to a Home Assistant user the way a person's own phone
has. The only thing a card (or a script, or a voice command wired up later)
can do is call a Home Assistant service and read entity state. Everything the
Companion buttons can trigger — acknowledge, snooze, and now a temporary
per-person silence that has no Companion equivalent at all — must therefore
also exist as first-class domain services, refusing invalid calls the way any
well-behaved service does: by raising, not by logging a warning nobody reads.

Separately, `docs/known-issues.md` (2026-09-06 and 2026-09-07 entries) records
that a real `alert.*` entity in Home Assistant core 2026.9.1 exposes no
`message` or `done_message` state attribute at all — `AlertEntity` renders
both internally only to build the payload it sends to its own `notifiers`.
Observer mode was implemented exactly as the Sprint 1 brief specified, but on
a real alert it always takes the fallback branch (row name / translated
"back to normal"), which is not expressive enough for a card that wants to
show a real per-alert message. The two known-issues entries both point to the
same open question: should the row own its own text, independently of what
`alert.*` can or cannot surface? This ADR answers yes, and specifies both
changes together because the cards work (Sprint 2 Part B) depends on both.

## Decision

### 1. Five new services, domain `notify_switchboard`

| Service | Fields | Behaviour |
|---|---|---|
| `notify_switchboard.acknowledge` | `target` (slug, required) | Same effect as the Companion Acknowledge button: `alert.turn_off` on the row's `alert.*`, but only when that row is in the routing table, has an `alert_entity` configured, and `allow_acknowledge` is true — the same allow-list as ADR-0009. Unlike the Companion callback (an event handler with nobody to answer to), a service call that fails this check raises `ServiceValidationError` instead of only logging: an unknown `target` and a known target the row does not allow to be acknowledged are both refused this way. `context.user_id` from the call is logged exactly as the Companion path logs it, and fires the existing `acknowledged` `event.switchboard_delivery` event — no new event type is introduced (see "What does not change" below). |
| `notify_switchboard.snooze` | `target` (slug, required), `minutes` (int, required), `person` (optional `person.*`, default: every person in the row's audience) | Same effect as the Companion snooze buttons, with one tightening: `minutes` must be one of the row's configured `snooze_minutes`; a value the row does not offer raises `ServiceValidationError` rather than being stored regardless (the Companion path never has to validate this because the button labels it fires are generated from `snooze_minutes` in the first place — a service call has no such guarantee). When `person` is given it must resolve to a person in the row's audience (unknown or out-of-audience person → `ServiceValidationError`); when omitted, every person in the audience is snoozed, matching the documented Companion fallback (`tests/acceptance/README.md` "Assumptions" §3) without needing an unresolvable `device_id` to get there. |
| `notify_switchboard.unsnooze` | `target` (slug, required), `person` (optional, default: every person in the row's audience) | Clears the snooze(s) stored by `snooze` for the same (person, target) pairs, immediately (not just letting them expire); same `target`/`person` validation as `snooze`. |
| `notify_switchboard.silence` | `person` (required), `minutes` (positive integer, required) | A **new** kind of silence: temporary and person-wide (not per-target), independent of the person's configured `silence_entities`. `minutes` must be `>= 1`; `silence(minutes: 0)` raises `ServiceValidationError` — zero has no defined meaning (draft note from the cards review: the maintainer explicitly flagged this as needing a rule). An unknown `person` (not `person.*` known to the router) also raises `ServiceValidationError`. |
| `notify_switchboard.unsilence` | `person` (required) | Lifts a temporary silence set by `silence` immediately. Idempotent: calling it on a person who is not currently temporarily silenced is not an error (there is nothing to undo). Unknown `person` still raises `ServiceValidationError`, for the same reason as above. |

Declared in a new `services.yaml` with matching `en`/`fr`/`es` translations
under a `services` key in `strings.json`/`translations/*.json`, the way core
integrations document their services (this repository's per-row
`common.*` translations are unaffected).

### 2. Temporary silence is a new, router-owned mechanism

`docs/ARCHITECTURE.md` is explicit that a person's configured
`silence_entities` (`schedule.*`, `input_boolean.*`, …) are "read, never
owned" by the router. `notify_switchboard.silence` does not touch any of
those entities — it adds a second, independent source of silence that the
router *does* own: an expiring `(person -> until)` entry next to the
existing snooze store.

- `binary_sensor.<p>_silenced` (already part of the frozen contract, §3.5)
  becomes true if **either** source is active: any configured
  `silence_entities` is `on`, **or** a temporary silence from
  `notify_switchboard.silence` has not yet expired. The entity's
  `sources`/attributes gain no new frozen key; a `until` attribute may be
  added when a temporary silence is active — attributes are not covered by
  the contract freeze (only the entity id is).
- The routing decision (contract §"Routing decision", step 3) is unchanged
  in shape: a person under either kind of silence is dropped with reason
  `silenced` (the existing constant, no new drop reason), unless the
  message's priority is `critical` — the same bypass rule that already
  applies to configured silence.
- Temporary silences are persisted in the same `Store` as snoozes and night
  deferrals (doctrine: nothing lives in RAM only) and expire lazily, the same
  way snoozes already do.
- `notify_switchboard.silence`/`unsilence` do not raise a new event type.
  `event.switchboard_delivery`'s `event_types` (`routed`, `dropped`,
  `acknowledged`, `snoozed`) are frozen by ADR-0011; a silence/unsilence call
  is observable through `binary_sensor.<p>_silenced` changing state, which is
  enough for a card, and does not need a fifth event type to be useful.

### 3. Per-row optional texts: `message`, `done_message`, `default_title`

Three new optional fields on a routing-table row (`entry.options["targets"][n]`),
all `None`/absent by default so every Sprint 1 row and test keeps working
unchanged:

- `message` — a template. When set, observer mode uses its rendered value on
  `idle -> on` instead of falling back straight to the row's `name`. The
  template is rendered with the row's alert's current state exposed as
  `alert` (a Home Assistant `State` object, or `None` if the row has no
  `alert_entity` or the entity does not currently exist) — so a row can write
  `{{ alert.name }}` or inspect whatever attributes a *synthetic*
  `alert.*`-shaped entity happens to expose, without depending on a real
  `AlertEntity` ever gaining `extra_state_attributes` upstream. If the alert
  itself already carries a `message` attribute (still checked first, for
  forward compatibility — see known-issues 2026-09-06), that attribute wins;
  the row's `message` template is the fallback when it does not, and the row
  `name` remains the last resort when neither is present.
- `done_message` — the same idea for the `on|off -> idle` transition,
  ahead of the alert's own `done_message` attribute and the translated
  `common.back_to_normal`, in that order.
- `default_title` — used as the outgoing `title` whenever no title is
  otherwise available: a legacy `notify.switchboard_<slug>` (or
  `notify.switchboard`) call whose caller omitted `title`, and every message
  observer mode generates on its own (which never had a caller to supply one
  in the first place). This is the same "row supplies a default, caller
  wins" shape the contract already documents for `default_data` — it does
  not change how a caller-supplied `title` is treated when one is given.

This directly resolves the known-issues entry "a real `alert.*` never
exposes `message` or `done_message`": the row, not a real `alert.*` entity,
is now the documented source of observer-mode text, matching option (a) that
entry raised. The two upstream `alert` limitations recorded in
`docs/known-issues.md` (2026-09-07, "two `alert` limitations to raise
upstream") remain worth filing against core independently — this ADR does
not depend on either being fixed upstream.

## What does not change

- The four `event.switchboard_delivery` `event_types` are unchanged (ADR-0011).
- `sensor.switchboard_routed_today` / `sensor.switchboard_dropped_today` keep
  their existing semantics; a message dropped for temporary silence counts
  exactly like one dropped for configured silence (same reason, same
  counter).
- Nothing about the Companion callback path (`mobile_app_notification_action`)
  changes: it keeps logging and returning on a refused action rather than
  raising, because there is still nobody on that path who could receive a
  `ServiceValidationError`.
- `docs/contract.md`'s v0 names, input/output shape and routing decision are
  untouched; this ADR only adds to the contract (services, and two new
  per-row optional fields), which is why it is released as router 0.2.0
  rather than a major version.

## Consequences

- The routing table gains three optional per-row keys and the router gains a
  second, owned silence mechanism next to the existing snooze store — one
  more thing `Store` persists, one more thing `is_person_silenced` combines.
- Cards (Sprint 2 Part B) can be built against real services instead of
  needing to fake a Companion callback event, and can show real per-alert
  text instead of always falling back to the row name.
- `docs/contract.md` needs one addendum edit (this is the one change this
  ADR authorizes to the otherwise-frozen document, per ADR-0011's own
  "requires an ADR" clause) and a version bump to "v0.2 addendum".
- A future ADR would be needed to let a row override the `snooze` bound
  (e.g. an arbitrary custom duration) or to add a sixth event type; neither
  is needed yet and both are explicitly out of scope here.

### Addendum (2026-09-07, post-review): the five services are not admin-only

The review of the Sprint 2 implementation asked whether the five services
should be restricted to administrators, the way core restricts a handful of
system services. **They are not, and that is the decision, not an oversight.**

The whole point of ADR-0016 is the wall tablet. That tablet runs Home
Assistant under a **non-admin** account, and the cards on it are the primary
caller of `acknowledge`, `snooze`, `unsnooze`, `silence` and `unsilence`.
Marking the services admin-only would make the cards fail for the one user
they were written for, and would leave the Companion buttons — which are not
admin-gated either, because a `mobile_app_notification_action` event is not a
service call — as the only way to acknowledge anything. That is the opposite
of what this ADR set out to do.

What actually bounds the blast radius is unchanged and is deliberately not
the caller's role:

- **The allow-list (ADR-0009).** `acknowledge` can only turn off an
  `alert.*` that is *in the routing table*, on a row whose
  `allow_acknowledge` is true. A caller cannot name an arbitrary entity; the
  set of things any of these services can touch is exactly what the
  administrator put in the options flow.
- **`alert.turn_off` is called with a child of the caller's context, not
  with the caller's own.** Forwarding the caller's context verbatim would
  hand the authorisation decision to core's entity-permission layer
  (`homeassistant/helpers/service.py`,
  `_resolve_entity_service_call_entities`) and quietly make the row's
  allow-list secondary to whatever entity policy the account happens to
  have. The allow-list stays the single gate; the logbook still attributes
  the acknowledgement through the parent context.
- **`context.user_id` is logged and carried.** Every refusal logs it, and the
  `acknowledged` and `snoozed` `event.switchboard_delivery` events carry it
  as an attribute, so who acknowledged what is auditable after the fact —
  which is what ADR-0009 asked for, rather than prevention by role.
- **Companion buttons keep `authenticationRequired`** on `high` and
  `critical` rows, so acting from a phone still means unlocking it. The
  tablet, a shared wall device that nobody unlocks, is precisely why the
  service path exists alongside the button path.
- **Nothing here is a security control.** ADR-0010 already says security is a
  configuration rule, not a code guarantee, and the alarm and the locks are
  deliberately outside this integration.

Revisit if a household actually needs it — a child who keeps silencing the
smoke alert, a guest account. The shape it would take is a per-row flag
(`admin_only`, alongside `allow_acknowledge`), not a blanket restriction on
the domain, because the blanket version breaks the tablet. Recorded in
`docs/known-issues.md` so it is not silently re-litigated.
