# ADR 0018: Rules shared by every voice adapter (legacy service naming, priority values)

Date: 2026-09-07
Status: accepted

## Context

Three independent coding agents wrote the three voice adapters of the suite
(Cast Notifier 0.2.0, AirPlay Notifier 0.2.0, Assist Satellite Notifier
0.1.0) and three independent reviewers found the **same major defect** in
each: the legacy `notify.<prefix>_<slug>` service name was computed from the
*order of config entries*, so renaming an entry onto another entry's title,
or reconfiguring one (which re-indexes it in core, `config_entries.py`
`update_unique_id`), made two entries claim one name. Core's
`BaseNotificationService.async_register_services` returns early when the
name already exists (`homeassistant/components/notify/legacy.py:312`), so
the second entry silently had no service, and removing it removed the other
entry's live service.

Two of the adapters also disagreed on `data.priority`: one accepted any
string, one only `normal | critical`, while the router forwards the
contract's `info | normal | high | critical` untouched.

## Decision

1. **The legacy service name is persisted** in `entry.data["service_name"]`
   at the entry's first setup. The `_<n>` collision suffix is chosen against
   the *persisted* names of the domain's other entries, never against list
   order. It is recomputed only when the entry title changes. An entry
   created before this rule receives its name at its next setup. Disabled or
   ignored entries keep their name reserved.
2. **Registration never steals.** Before registering, the adapter checks
   `hass.services.has_service`; if the name is held by someone else it logs
   an ERROR and registers nothing. An adapter only retracts a service it
   registered itself (ownership map or flag).
3. **`data.priority`** accepts exactly the contract's four values
   `info | normal | high | critical` (lowercase, exact); anything else is
   refused as invalid call data (ADR-015). Only `critical` acts (quiet-hours
   bypass). Exception placeholders for quiet hours are `player`, `start`,
   `end` in all adapters.
4. **`data.volume` decides how loud, never whether**: inside quiet hours
   without a `quiet_volume`, the call is refused regardless of `data.volume`;
   only `critical` bypasses.

## Consequences

- `docs/review-checklist.md` gains explicit items for 1–4 (section D).
- Each adapter documents the persisted name in its ARCHITECTURE and the
  upgrade note in its CHANGELOG.
- A defect found by review in one adapter is checked in the two others
  before any of the three is released.
