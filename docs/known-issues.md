# Known issues

Findings accepted instead of being fixed. Design the maintainer chose on
purpose — which bends a stated principle for a stated reason — lives in
[`accepted-deviations.md`](accepted-deviations.md) instead.

## `alert.turn_off` does not cancel its own repeat timer

**What.** Core's `AlertEntity.async_turn_off` only sets an internal
acknowledged flag; it never cancels the alert's own repeat timer. Only the
watched entity leaving the alert state does that.

**Impact.** An alert acknowledged through this integration keeps its repeat
timer armed until the watched entity changes state. In tests, this trips
`pytest-homeassistant-custom-component`'s lingering-timer check.

**Workaround.** `tests/conftest.py` tolerates the lingering timer for the
affected tests, with the reasoning recorded there. A ready-to-file upstream
issue is drafted in
[`docs/upstream/cancel-on-shutdown-async-call-later.md`](upstream/cancel-on-shutdown-async-call-later.md);
not yet filed.

## The options editor writes one target or person at a time

**What.** Adding or updating a target or person always replaces the whole
row, keyed by slug or `entity_id`. There is no field-level edit.

**Impact.** Renaming a slug means adding the new target and removing the old
one; there is no in-place rename.

**Workaround.** Each editor is split into a short form and an advanced step,
so at least changing one field cannot silently reset the others. A richer
editor is a cards-repository concern, not this integration's.

## The Companion `device_id` fallback is unverified on a real phone

**What.** `context.user_id` is the primary way an acknowledge/snooze callback
resolves who pressed the button; a lookup by the event's `device_id` is the
documented fallback when that fails. No event from a real Companion device
has been observed by this project, so the fallback's shape is inferred from
core's source, not measured.

**Impact.** If the fallback path is ever exercised in practice and mismatched,
it snoozes the whole audience rather than the wrong person alone — never a
silent wrong-person action, by design.

**Workaround.** None needed today: `user_id` resolution is exact and covers
every case seen so far. Capturing one real callback and pinning its shape in
a test would close this out.

## `authenticationRequired` has no per-target override

**What.** The contract sets `authenticationRequired: true` by default when a
message's effective priority is `high` or `critical`. No target-level field
overrides this in either direction.

**Impact.** A target cannot ask for an unauthenticated Acknowledge on a
`critical` alert, or an authenticated one on an `info` alert.

**Workaround.** None; deferred on purpose. A tri-state field was drafted and
cut in review as a fourth state on a form that exists to stay short, for a
case nobody has hit yet.

## The UI services are callable by any user, not just admins

**What.** `notify_switchboard.acknowledge`, `snooze`, `unsnooze`, `silence`
and `unsilence` are callable by any Home Assistant user, admin or not.

**Impact.** A non-admin account (e.g. a wall tablet) can call any of these
services for any target or person it can name.

**Workaround.** Deliberate, not overlooked: the allow-list in
[ADR-0009](ADR/0009-secure-notification-actions.md) (only an `alert.*` in the
routing table, on a target with `allow_acknowledge`), `context.user_id`
logged on every refusal, and `authenticationRequired` on `high`/`critical`
Companion buttons bound what these services can do. An optional per-target
restriction may be added later; never a blanket admin-only domain, which
would break the tablet's own cards.

## Two repairs never clear themselves automatically

**What.** `unknown_target_<slug>` stays open until the routing table is
reloaded, even if the caller that raised it is fixed instead; `missing_output_<x>`
clears only on the next successful call to that output, so an output that is
still configured but never called again keeps its warning.

**Impact.** Cosmetic: a stale Repairs entry that no longer reflects the
current cause.

**Workaround.** Safe to dismiss manually in **Settings → Repairs** — neither
case is observable by the router well enough to auto-clear.

## An episode can stay open across a Home Assistant restart

**What.** Core's `AlertEntity` never reads the current state of the entity it
watches at startup, only future changes. If Home Assistant restarts while an
alert is firing, the router never sees the `on → idle` transition and the
open episode from before the restart lingers.

**Impact.** Harmless: the only effect is that a future back-to-normal message
stays narrowed to the stale episode's recipients until the target's next
`idle → on` opens a fresh one.

**Workaround.** None needed; a config-entry reload does not trigger this (the
`alert.*` entity survives it). A ready-to-file upstream issue is drafted in
[`docs/upstream/alert-entity-startup-state.md`](upstream/alert-entity-startup-state.md);
not yet filed.

## Notify entities aren't offered in the option pickers

**What.** From 0.7.0 an output that names a `notify.*` **entity** (not a
legacy service) is delivered through `notify.send_message`, but the **Notify
services** and **Audience** pickers only list registered legacy services.

**Impact.** An entity output must be typed in by hand; it is not discoverable
from the dropdown.

**Workaround.** Type the entity id directly — both fields accept a typed
value. Offering entities in the picker needs a few product decisions
(labelling, ordering, what happens when a legacy service and an entity share
a name) that have not been made yet.

## The night schedule reaches core's schedule store through its websocket registry

**What.** From 0.8.0 the person screen can create a `schedule` helper (ADR-0022
§5). Home Assistant 2026.9.1 has no Python API for creating one: the
`schedule` integration keeps its storage collection only behind its
`schedule/*` websocket commands. The flow finds that collection through the
registered `schedule/list` handler and calls the collection's own
`async_create_item`, the method the `schedule/create` command uses.

**Impact.** If a future core moves or wraps that handler, the checkbox stops
working: the person screen shows "The night schedule could not be created",
nothing is saved half-done, and everything else keeps working.

**Workaround.** Create a schedule in **Settings → Devices & services →
Helpers** and pick it in **When not to disturb them**, as before 0.8.0.

## The read-only identifier and the menu are unverified in a real frontend

**What.** The **Change an alert** screen shows the identifier automations use
in a text field marked `read_only`, a selector option every selector accepts
in 2026.9.1 (`make_selector_config_schema`). The tests assert the option is
sent; that the frontend greys the field out, and how the seven-entry menu and
the **Settings** sub-menu read, has to be seen on a real instance.

**Impact.** If the frontend ignores `read_only`, the field looks editable;
whatever is typed in it is ignored, so nothing breaks.

**Workaround.** None needed; one look on a real instance closes this out.

## The critical push is unverified on a real device

**What.** A `critical`-priority message carries the Companion-documented keys
for a critical notification on `mobile_app_*` outputs. Nothing in this
repository can prove that a phone actually rings: the tests assert the router
**emits** the right keys, not what Apple, Firebase or the Companion app do
with them afterwards.

**Impact.** iOS also requires the user to have granted the Companion app the
critical-alerts permission, which no automated test can stand in for.

**Workaround.** None; shipping without proof was preferred to not shipping.
One observed critical push on a real iOS device would close this out.

## The quiet back-to-normal of a `notifiers:` alert leans on core's `end_alerting`

**What.** From 0.9.0 the `done_message` a Home Assistant alert sends through
its `notifiers:` list is recognised and routed at no more than the target's
`done_priority` (ADR-0023 §2.2). Nothing in the call says it is the last one;
the router suspects the instant core's `end_alerting` creates — the live
`AlertEntity` already reads `idle` while the state machine still holds `on` or
`off`, because core clears `_firing`, awaits the done message, and only then
writes the state — and confirms it by yielding once and finding the stored
state `idle`. An alert stuck after a `done_message` template that failed to
render never writes `idle`, so its next calls keep their priority: a real
alarm is never downgraded.

**Impact.** If a future core reorders `end_alerting` — the `alert` integration
is marked "development frozen" — the recognition stops and the back-to-normal
message rings at the target's own priority again, as in 0.8. Observer mode's
done message and a `switchboard_done: true` call are not affected.

**Workaround.** Wire the alert in observer mode, or send the back-to-normal
yourself with `switchboard_done: true`.

## A back-to-normal sent through a `notify.group` is not recognised

**What.** One alert listing two targets under `notifiers:`
(`switchboard_a`, `switchboard_b`) ends quietly on both: core calls them one
after the other and writes `idle` after the last. But an alert whose
`notifiers:` names a `notify.group` that contains `switchboard_<slug>` is not
recognised: the group calls the router from a task of its own, once the alert
is already `idle`, so nothing distinguishes that call from an ordinary one.

**Impact.** The back-to-normal rings at the target's own priority, as in 0.8.

**Workaround.** List `switchboard_<slug>` directly under the alert's
`notifiers:`, or wire the alert in observer mode.

## The one-click blueprint is unverified in a real frontend

**What.** From 0.9.0 an alert tied to no Home Assistant alert ends on a link to
the blueprint list, where one click on the shipped blueprint opens the
automation editor (frontend 20260826.6, `ha-blueprint-overview.ts`). The tests
prove the file is copied, valid and working once used; that the link opens the
list in the same window and the row opens the editor is frontend behaviour.

**Impact.** If the frontend behaves differently, the user reaches the
blueprint through **Settings → Automations & scenes → Blueprints** instead.

**Workaround.** None needed; one look on a real instance closes this out.

## Observer mode does not follow an alert's reminders

**What.** Observer mode routes a Home Assistant alert's start and end. Its
`repeat` reminders change no state, so the router never sees them. 0.9.0 says
so on screen; it does not change it (ADR-0023 §3 records a possible way).

**Impact.** A target in observer mode — the default — sends one message when
the alert goes off and one when it ends.

**Workaround.** For reminders, untick **Tell people as soon as it goes off**
and list `switchboard_<target>` under the alert's `notifiers:`.

