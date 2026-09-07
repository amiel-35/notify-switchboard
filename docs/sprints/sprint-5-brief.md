# Sprint 5 brief — Notify Switchboard v0.5.0 (night, catch-up and closing the loop; suite roadmap "S9")

> Spec agent first (ADR-0019, contract v0.5 addendum, failing acceptance
> tests `tests/acceptance/test_s5_*.py`, branch `spec/s5-router`, PR), then
> coding agent (branch `feat/s5-router`). English. Paths from the
> orchestrator: `$HA_CORE_SRC`, `$VENV`. Nobody touches the dev instance or
> `.github/workflows`; the coding agent never edits `docs/contract.md` or
> the acceptance tests.

## Goal

Make the night bearable for the people who are silenced, and close every
episode cleanly on every channel. Today a silenced person gets every
deferred message replayed one by one at wake time, including messages that
no longer mean anything; the phone keeps stale notifications after an
alert is over; and "back to normal" goes to people who never heard about
the problem.

## Scope (must)

1. **Time-to-live.** Global options `ttl_minutes` per priority: `info` 120,
   `normal` 720, `high` none, `critical` not applicable (never deferred);
   per-call `data.ttl_minutes` overrides. A deferred message whose queue
   time + TTL has passed at flush time is dropped with the **new reason
   `expired`** (ADR-0019 extends the reason list; the four event types stay),
   counted in `dropped_today` and `event.switchboard_delivery`.
2. **One summary at wake time.** Per-person option `summary` (default on).
   At flush, if more than one deferred message survives TTL for a person,
   they are delivered as **one** notification per output: translated title
   "{count} messages while you were away", message = one line per message
   (`• title — message`, newest last), messages sharing a `tag` collapsed to
   the last one, `data` = the union of `switchboard-*` keys only (no
   Companion buttons on a summary). With `summary` off, or exactly one
   surviving message, the old one-by-one behaviour applies. `critical` is
   never deferred, so never summarised.
3. **Full re-decision at flush.** A deferred message is re-evaluated with
   the complete decision (audience, presence rule, snooze, silence) using
   its original priority; if it no longer routes it is dropped with the
   real reason, never delivered blindly.
4. **Early flush.** The router subscribes to every person's configured
   silence entities; when the last active one turns `off` (and no temporary
   silence is active), that person's deferrals are flushed immediately
   instead of waiting for `wake_time`. `wake_time` remains the upper bound.
5. **Episode recipients.** For rows with an `alert_entity`, the router
   remembers, per episode (from the alert's `idle → on` until `→ idle`),
   which persons actually received at least one message. The `done`
   message (observer mode, and any legacy call carrying
   `data.switchboard_done: true`, a new documented key the blueprints will
   use) goes only to those persons; the others are dropped with the new
   reason `not_notified`. Persisted with the other store data.
6. **Closing the loop on phones and in the UI.** When an episode ends:
   for every `mobile_app_*` output that received the episode, send
   `message: clear_notification` with the episode's `tag`
   (`$HA_CORE_SRC/homeassistant/components/mobile_app/const.py`
   `CLEAR_NOTIFICATION`); for the `persistent_notification` output, dismiss
   the notification. To make this deterministic the router sets a default
   `data.tag` = `switchboard-<slug>` when the caller provides none, and a
   `data.notification_id` = `switchboard-<slug>` for the
   `persistent_notification` output (`components/notify/__init__.py`,
   `ATTR_NOTIFICATION_ID`), so repeats update instead of stacking. The
   `done` message itself is still sent as today (then cleared for
   `mobile_app_*` outputs only if the row option `clear_done` is on;
   default off).

## Out of scope (must not)

Escalation, `max_deliveries`, places, labels, critical payload per OS
(later sprints); cards; blueprints changes beyond documenting
`switchboard_done` (a docs note is enough; the blueprint change is a
separate small PR after this sprint).

## Acceptance (spec agent writes; coding agent must not modify)

`test_s5_ttl.py` — expired vs surviving deferrals, per-priority defaults,
per-call override, reason `expired`.
`test_s5_summary.py` — three deferred messages, two sharing a tag ⇒ one
notification with two lines, title count, no buttons; `summary` off ⇒
three notifications; single survivor ⇒ plain delivery.
`test_s5_redecision.py` — a deferral whose person left home under a
`home_only` row is dropped with `presence` at flush.
`test_s5_early_flush.py` — silence entity `on → off` at 05:00 flushes
before the 07:00 wake time; temporary silence still active ⇒ no flush.
`test_s5_episode.py` — two persons, one silenced during the episode:
`done` reaches only the other; reason `not_notified`; survives a reload.
`test_s5_clear.py` — `clear_notification` with the right tag to the
`mobile_app_*` output, `persistent_notification.dismiss` with the right
id; default tag and notification id set when absent.
`test_contract.py` — reasons `expired` and `not_notified` added; keys
`ttl_minutes`, `switchboard_done`, default tag/notification id documented.

## Definition of done

S1–S5 acceptance green unmodified; coverage ≥ 90 % on changed modules;
ruff / mypy / hassfest green; en/fr/es complete (summary title/lines,
options, reasons); `docs/ARCHITECTURE.md` (deferral lifecycle diagram
updated), `CHANGELOG.md`, `docs/known-issues.md`; PR lists every core API
with its path. Branch `feat/s5-router`; do not merge, do not tag.
