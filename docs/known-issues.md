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
