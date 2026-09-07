# ADR 0019: Night, catch-up and closing the loop — TTL, one wake-time summary, a full re-decision at flush, early flush, episode recipients, cleared notifications

Date: 2026-09-07

## Status

Accepted.

## Context

0.4.0 makes the first hour of use bearable. What it does not make bearable is
the night, and it never closes anything it opened.

**The night.** A person with a `wake_time` and a night silence accumulates a
queue. At the wake time the router replays that queue one message at a time,
in full, whatever it has become since:

- A message queued at 23:31 saying "the front door is open" is delivered at
  07:00 as if it were news. Nothing in the router knows that a message can
  stop being worth waking up for.
- Eleven deferred messages are eleven notifications, eleven sounds and eleven
  banners, in a burst, at the exact moment somebody opens their eyes. The
  integration that exists to protect the night is the loudest thing in it.
- The flush re-reads exactly one thing, the silence
  (`docs/known-issues.md`, 2026-09-07, "a deferral now re-checks silence, but
  only silence"). A person who left the house under a `home_only` row, who
  snoozed that row at 02:00, or who was removed from the audience still gets
  their message. The known-issues entry says as much and calls the general
  case "a design question, not a bug fix". This ADR is that design decision.
- A silence that ends at 05:00 is not observed. `_async_silence_changed`
  refreshes `binary_sensor.<p>_silenced` and returns; the queue waits for
  07:00 anyway, two hours after the person is demonstrably awake.

**The loop that never closes.** A leak alert fires at 03:00 and pushes a
notification to three phones. It is fixed at 03:20. Today:

- The `done` message ("back to normal") goes to the whole audience, including
  the two people who were silenced and never heard about the leak at all.
  Their first and only word on the subject is that something they never knew
  about is over.
- The original notification is still on every phone, for ever. Nothing tells a
  device that a notification it received is stale, and the router does not
  even know which devices received it.
- Two notifications about the same alert stack instead of replacing each
  other, because nothing sets a `tag` unless the caller thought to.

Both halves need the same missing concept: the router must remember what it
did — for how long a queued message is still worth delivering, and to whom an
episode was actually announced. Everything else in this ADR follows from
having that memory.

## Decision

### 1. Time-to-live on a deferred message

A new global option, `entry.options["ttl_minutes"]`, a mapping from priority
to a number of minutes or `null`:

```python
entry.options["ttl_minutes"] = {
    "info": 120,  # default
    "normal": 720,  # default
    "high": None,  # default: never expires
}
```

- The option is **optional and partial**. An absent mapping, or an absent
  priority inside it, means the default above. Every configuration written
  before 0.5.0 therefore behaves as if it carried the defaults, and no storage
  or options migration is needed.
- `critical` has no entry and cannot be given one: a `critical` message
  bypasses silence everywhere (contract §"Routing decision"), so it is never
  deferred, so it can never expire.
- `null` means "no expiry", and so does an absent key. `0` is not a valid
  value (it would mean "expired before it was queued"); a configuration
  carrying it is read as `null`.

A per-call override, `data.ttl_minutes`, an integer number of minutes, wins
over the mapping for that message only. `data.ttl_minutes: 0` means **this
message never expires** — the caller's way of saying "keep it whatever the
household policy is", which is the only reading that leaves the option
overridable in both directions.

**Where it is evaluated.** A deferred message is checked at every flush — the
wake-time flush, the early flush of §4, and the catch-up flush that runs at
setup after a restart — and nowhere else. If

```
deferral.queued_at + ttl <= now
```

the message is not delivered. It is removed from the store and **dropped with
the new reason `expired`**: counted in `sensor.switchboard_dropped_today`,
listed in that sensor's `reasons` attribute, and carried by one `dropped`
`event.switchboard_delivery`. The four event types are unchanged; the reason
list gains one value, which ADR-0011's "requires an ADR" clause is what this
document is for.

The effective TTL is read at **flush** time from the deferral's stored
priority and its stored `data`, not frozen at queue time. The mapping is a
household policy, not a per-message promise: a user who shortens
`info` to 30 minutes at 02:00 means it for what is already waiting.

Rejected: a wall-clock `expires_at` stamped on each deferral at queue time (it
freezes a policy the user can still change, and it needs a store migration for
nothing); a TTL on *every* message rather than on deferrals only (a message
that is delivered immediately cannot expire, and a TTL on a delivered
notification is a different feature — the auto-clear of §6); expiring a
deferral on a timer of its own (a queue that expires while nobody is watching
produces drops with no flush to attribute them to, and one timer per message
is exactly the kind of unbounded scheduling ADR-0017 §3 spent a sprint
removing).

### 2. One summary at the wake time

A new per-person option, `summary`, a boolean, **default true**. It is written
into the person row only when it is `false`, so every person row written
before 0.5.0 keeps the exact dict it had and means "on".

At a flush, once §1 has removed the expired messages and §3 has removed the
ones that no longer route, look at what is left for that person:

- **Zero survivors**: nothing is sent.
- **Exactly one survivor**, or `summary: false`: the message is delivered
  exactly as 0.4.0 delivers it — its own text, its own title, its own merged
  `data`, its own Companion buttons. Nothing about the single-message path
  changes.
- **Two or more survivors and `summary: true`**: **one** notification is sent
  per output instead of one per message.

The summary notification:

| Part | Value |
|---|---|
| `title` | the translated `common.summary_title`, with one placeholder `{count}` — "{count} messages while you were away" in English |
| `message` | one line per surviving message, `\n`-joined, in queue order, newest last |
| a line | the translated `common.summary_line` (`• {title} — {message}`), or `common.summary_line_untitled` (`• {message}`) when the message has no title at all |
| `data` | see below |

`{count}` is the number of **lines**, not the number of messages that were
queued: the count and the list a user reads must agree.

**Messages sharing a `tag` are collapsed to the last one.** The collapse key
is the effective `tag` (§6 gives every message one), across rows, and the
survivor is the one with the latest `queued_at`, which is also the position
the collapsed group takes in the list. Within one row this is already true at
queue time — the deferral store is keyed on `(person, target, tag)` — so what
this rule adds is the cross-row case: two rows that a caller deliberately
tagged the same are one line, not two.

**The summary's `data` is built, not merged.** It carries only the keys the
switchboard itself owns:

- `tag`: `switchboard-summary`, a frozen public value, so a second summary
  replaces the first instead of stacking, and §6's clear can reach it;
- `notification_id`: `switchboard-summary`, added for the
  `persistent_notification` output only, per §6;
- the union, over the collapsed survivors, of every `data` key in the
  switchboard's own `switchboard_*` namespace (today only `switchboard_done`,
  §5), later message wins on a conflict.

Nothing else survives into a summary: no caller key (`channel`, `group`,
`color`, an `image`), no row `default_data`, no `priority`, and — explicitly —
**no `actions` and no `authenticationRequired`**. This is the reading this ADR
gives to the sprint brief's "`data` = the union of `switchboard-*` keys only
(no Companion buttons on a summary)", and it is the only one that is
implementable: three rows' worth of `data` cannot be merged into one payload
without contradicting each other, and a Companion Acknowledge button on a
digest of three alerts would acknowledge an arbitrary one of them.

`critical` is never deferred, so a summary never contains a critical message
and a critical message is never delayed by one.

Rejected: a summary as a *second* notification after the individual ones (that
is more noise, not less); a digest built at queue time and updated (it would
have to be re-rendered on every new message, and it cannot know what §3 will
drop); making `summary` a per-row option (the person is the one being woken
up, not the row); collapsing on `(slug, tag)` rather than on `tag` (it makes
the cross-row case, the only one the caller can control, unreachable).

### 3. A full re-decision at the flush

`docs/known-issues.md` records that a flush re-reads the silence and nothing
else. From 0.5.0 a flush re-runs the **whole** decision, `router.decide` over
a fresh `Switchboard.build_context()`, for a request rebuilt from the stored
deferral:

- the same `message`, `title` and stored `data`;
- the same target;
- **the deferral's original priority**, written explicitly into the rebuilt
  request's `data.priority`. A row whose `default_priority` changed overnight
  must not silently re-grade a message that was queued under the old one.

The outcome:

| Re-decision says | What happens |
|---|---|
| routed | delivered (alone, or as one line of the summary of §2) |
| dropped, reason `silenced` | **kept queued**, exactly as 0.4.0 does, and the flush is re-armed. The night is not over; that is the whole point of a deferral |
| dropped, any other reason | **dropped for real**, with that reason: counted, evented, removed from the store |

So a person who left the house under a `home_only` row gets `presence`; one
who snoozed the row at 02:00 gets `snoozed`; one whose row was deleted gets
`unknown_target`; one who lost their last output gets `no_outputs`; one
removed from the audience gets `not_in_audience` (recorded, not counted, per
the contract). No new drop reason is needed for any of them, which is the
point: the flush stops being a second, weaker decision engine and becomes the
same one, run later.

Rejected: delivering anyway and logging the disagreement (that is 0.4.0, and
it is what the known-issues entry asks to stop); re-queueing a message that
now drops for a non-silence reason (a message the router would refuse to send
now will not become sendable by waiting another day); re-evaluating against
the context captured at queue time (it would make the whole exercise a no-op).

### 4. An early flush when the silence really ends

The router already subscribes to every configured `silence_entities` of every
person (`Switchboard.async_setup`, `_async_silence_changed`). From 0.5.0 that
handler does more than refresh a binary sensor. When a person's silence
entities change state, and

- none of that person's configured `silence_entities` is `on` any more, **and**
- no temporary `notify_switchboard.silence` is running for them, **and**
- they have at least one queued deferral,

their deferrals are flushed **immediately**, through the same code path as the
wake-time flush (so §1, §2 and §3 all apply, unchanged).

`wake_time` stays the **upper bound**: the timer is not cancelled by this rule,
and a queue that is still held (because the person is still silenced by
something) still comes due at the wake time as it always did. A person with no
`wake_time` has no deferrals to flush, because `_async_defer` refuses to queue
for them.

This is what makes the model honest. `wake_time` was documented as "the end of
the night silence"; a schedule that ends at 05:00 *is* the end of the night
silence, and the router was watching that entity all along without acting
on it.

Rejected: flushing when *any* silence entity goes `off` (a person with a night
schedule and a Focus sensor would be flushed the moment one of the two lifts,
which is not the end of their night); flushing on the temporary silence's
expiry timer instead (0.4.0 already re-arms the deferral timer for that
instant, and that behaviour is unchanged); making the early flush an option
(nobody configures a night silence in order to be notified two hours after it
ends).

### 5. Episodes, and who was actually told

**An episode** is one run of a row's `alert_entity`: it opens on that entity's
`idle → on` transition and closes on its `→ idle` transition. Episodes exist
for **every** row that names an `alert_entity`, not only for rows in observer
mode: a row whose alert calls `notify.switchboard_<slug>` through its own
`notifiers:` list has exactly the same episodes, and the router must widen its
`async_track_state_change_event` subscription from "every observed alert" to
"every row's alert" to see them.

While an episode is open the router records, for that row:

- **`persons`** — every person for whom at least one message of this episode
  was actually delivered, i.e. one for whom `_async_deliver` counted a
  `routed` delivery. A person whose message was dropped, or deferred and not
  yet flushed, is *not* a recipient;
- **`outputs`** — every `notify.*` output that was successfully called during
  the episode, needed by §6;
- **`tags`** — every effective `data.tag` the episode's delivered messages
  carried (§6). Normally exactly one, `switchboard-<slug>`; a caller who sets
  its own `data.tag` on some of an episode's messages produces several, and
  all of them have to be cleared, because all of them are on the phone.

The record is closed, not deleted, when the alert returns to `idle`; it is
reset when that row's **next** episode opens. A `done` message is by
definition sent after the alert is already back to `idle`, so the recipients
have to outlive the episode's end.

**Everything about an episode is persisted** with the snoozes, the deferrals
and the temporary silences, under a new `episodes` key in the same `Store`
document. `STORAGE_MINOR_VERSION` goes from 3 to 4; the migration inserts an
empty list, because an upgrade must not invent an episode. A restart in the
middle of a leak must not turn "back to normal" into a message for people who
slept through the leak.

**The `done` message goes only to the episode's recipients.** Two callers can
produce one:

1. observer mode's `on|off → idle` transition, as today;
2. any legacy `notify.switchboard[_<slug>]` call carrying
   **`data.switchboard_done: true`** — a new, documented, public `data` key,
   which is how the blueprints will mark the "back to normal" message they
   already send today. (Documenting it is in scope for this sprint; changing
   the blueprints is not.)

For such a message, every person in the row's audience who is **not** in the
episode's `persons` set is dropped with the **new reason `not_notified`** —
counted, evented, in `reasons` — before the rest of the decision runs. The
remaining persons go through the ordinary decision, so a recipient who is
silenced right now is still silenced right now.

A row with no `alert_entity` has no episodes; a `switchboard_done: true`
message on such a row is routed to the whole audience exactly as any other
message, because there is no record that could say otherwise. Same for a
`done` message on a row whose episode set is empty because nobody was reached:
there is nobody to tell, and every person is dropped with `not_notified`.

Rejected: inferring the recipients from `sensor.<person>_last_notification`
(it is a timestamp, not a per-episode ledger, and it is overwritten by every
other row); keeping the recipient set in memory only (a restart is exactly
when the household most wants the loop closed); keying the set on the alert
entity rather than on the row (two rows may watch one alert with different
audiences, and the contract says the row, not the alert, is the identity —
ADR-008).

### 6. Closing the loop on phones and in the UI

#### The default tag and notification id

Every message the router sends acquires a deterministic identity, because a
notification you cannot name is one you can never clear:

| Message | default `data.tag` | `data.notification_id` |
|---|---|---|
| any message on row `<slug>` | `switchboard-<slug>` | mirrors the effective `tag` |
| the `done` message of row `<slug>` | `switchboard-<slug>-done` | mirrors the effective `tag` |
| a wake-time summary (§2) | `switchboard-summary` | mirrors the effective `tag` |

- A caller-supplied `data.tag` always wins; the default only fills a gap. The
  test message's `switchboard-test` (contract v0.4) is such a caller value and
  is unchanged.
- `data.notification_id` defaults to the message's **effective** tag, and is
  added **only for the `persistent_notification` output** — the bare output
  service name `persistent_notification`, i.e. `notify.persistent_notification`.
  That legacy service is the one core documents as reading
  `data.notification_id` (`homeassistant/components/notify/__init__.py`, the
  `persistent_notification` service handler: `notification_id =
  data.get(pn.ATTR_NOTIFICATION_ID)`, then `pn.async_create(hass, message,
  title, notification_id)`); every other output would receive a key it has no
  use for. A caller-supplied `data.notification_id` wins there too.
- The router adds this key the same way it already strips `actions` and
  `authenticationRequired` for non-Companion outputs: per output, in
  `_async_call_output`, not on the shared payload.

**The `done` message deliberately does not share the episode's tag.** It is
the one rule here that is not obvious, and `clear_done` below is why: a done
message that carried `switchboard-<slug>` could not be kept on the phone while
the episode's own notifications are cleared, which is exactly what
`clear_done: false` — the default — promises.

#### What happens when an episode ends

When a row's `alert_entity` reaches `idle`, in this order:

1. the `done` message is routed as today, filtered by §5;
2. **every `mobile_app_*` output in the episode's `outputs`** is called with
   `message: "clear_notification"` and `data: {"tag": <t>}`, once per tag `t`
   in the episode's `tags` (normally exactly one call).
   `clear_notification` is core's own literal
   (`homeassistant/components/mobile_app/const.py`, `CLEAR_NOTIFICATION =
   "clear_notification"`); the Companion app on the device is what removes the
   notification bearing that tag when the push arrives. Core itself only reads
   the literal in one place — `mobile_app/live_activity/__init__.py`, `if
   data.get(ATTR_MESSAGE) == CLEAR_NOTIFICATION`, which ends a Live Activity
   for the same tag — and otherwise forwards the payload untouched to the push
   relay, which is precisely why the router must send it as an ordinary
   `notify.mobile_app_<device>` call rather than look for an API that does not
   exist;
3. if `persistent_notification` is in the episode's `outputs`,
   `persistent_notification.dismiss` is called once per tag of the episode,
   with that tag as the `notification_id` — `switchboard-<slug>` in the
   ordinary case, since the id mirrors the tag
   (`homeassistant/components/persistent_notification/__init__.py`,
   `ATTR_NOTIFICATION_ID`, `SCHEMA_SERVICE_NOTIFICATION`, the `dismiss`
   service and `async_dismiss`);
4. if the row's new option **`clear_done`** is true, every `mobile_app_*`
   output that received the `done` message is then called with
   `message: "clear_notification"` and the done message's own tag, so the
   "back to normal" makes its sound and its banner and does not then live in
   the notification centre for a week.

`clear_done` is a routing-table row key, boolean, **default false**, written
into the row only when true — so every row written before 0.5.0 keeps the
exact dict it had.

**A clear is not a message.** It is not counted in
`sensor.switchboard_routed_today` or `..._dropped_today`, it fires no
`event.switchboard_delivery`, it is not subject to presence, silence, snooze
or deferral, and it never creates a deferral of its own. It is housekeeping on
a channel that was already used, addressed to a device rather than to a
person; routing it would mean asking permission to tidy up. It is bounded by
the same `OUTPUT_TIMEOUT_SECONDS` as any other output call and a failure is
logged and swallowed, never raised.

Rejected: an `alert.turn_off`-style acknowledgement clearing the notification
(acknowledging is not fixing — the alert is still firing, contract §"Buttons
and callbacks"); clearing on the `on → off` acknowledgement transition (same
reason: `on → off` is an ack, and observer mode already routes nothing for
it); a TTL that auto-clears a notification after n minutes (that is a
different feature and it would clear notifications about problems that are
still there); using `notify.mobile_app_*`'s `data.tag` for the
`persistent_notification` id too, in one shared key (the two channels have
different lifetimes and core gives them different key names, so conflating
them would make one of the two undismissable).

#### Amendment 2026-09-07

Four points §6 left implicit, settled here after the acceptance suite was read
against the implementation. None of them changes a public name, a reason, an
event type or an option; all four are the reading a reviewer of §6 has to
arrive at anyway.

**(a) The closing sequence applies to observer-mode rows only.** Steps 1-4
above run when the router itself is the thing that announces the end of an
episode — that is, on a row in observer mode. A row driven by its alert's own
`notifiers:` list is different, and core is why: `end_alerting`
(`homeassistant/components/alert/entity.py:115-126`) *awaits* the done message
before it calls `async_write_ha_state()`, so the "back to normal" leaves
through `notify.switchboard_<slug>` **before** the state the router watches
becomes `idle`. That message has no `switchboard_done: true` on it and so
carries the row's ordinary default tag, `switchboard-<slug>` — the episode's
own tag. A clear fired at `→ idle` would therefore wipe the done message a
fraction of a second after it arrived, which is the exact opposite of what
`clear_done: false` promises. §5's episode *record* is unchanged: it is kept
for every row that names an `alert_entity`, in observer mode or not, and the
`not_notified` filter of §5 applies to both. It is the housekeeping of §6 that
is observer-only.

This is the whole of the narrowing §6 needs. In particular the clear does
**not** depend on what backs the `alert.*` state: any row with an
`alert_entity` in observer mode gets the closing sequence, whether that state
is written by the `alert` integration, by a template, or by a test. The router
observes and routes from such a state already; refusing to tidy up after
itself on the same evidence it was willing to notify on would be incoherent.

**(b) A summary is a delivery, so its tag is cleared with the episode.** A
wake-time summary (§2) that reaches a person is a `routed` delivery like any
other, so §5 records its person, its outputs and its **`switchboard-summary`**
tag into whatever episodes contributed a line to it. When such an episode
closes, `switchboard-summary` is among the tags of step 2 and is cleared. That
follows from §5's "actually delivered" and is spelled out because the summary
is the one message whose tag is not derived from a row slug.

**(c) One routed count per summary line.** A summary that collapses three
surviving messages into two lines counts **two** routed deliveries per output,
not one and not three: the count a household reads must match what §2 says a
line is. Recorded here; `docs/contract.md` gains the sentence at its next
addendum rather than in the middle of the v0.5 block.

**(d) Known limitation: an episode open across a real restart.** §5 persists
an open episode so that a restart mid-leak does not widen the done message.
What it cannot do is re-open the alert. Core's `AlertEntity.__init__`
(`homeassistant/components/alert/entity.py`) only subscribes to *future*
changes of its watched entity — it starts with `_firing = False` and never
reads that entity's current state — so after a real Home Assistant restart the
`alert.*` is `idle` even though the leak is still running. The router sees no
`→ idle` transition, and the persisted open episode therefore lingers until
that row's next `idle → on` resets it. The stale record is harmless (it can
only narrow a `done` message that will not be sent) and the fix belongs to
core, not here; the config-entry reload that
`test_s5_episode.py::test_the_episode_recipients_survive_a_reload` performs is
not affected, because the `alert.*` entity survives it.

## What does not change

- Every v0 / v0.2 / v0.3 / v0.4 frozen name; the **four**
  `event.switchboard_delivery` event types; the three `explain` decisions; the
  routing decision of contract §"Routing decision" for a message that is not
  deferred.
- The six `notify_switchboard.*` services: no new one, no changed field, no
  changed refusal.
- `notify.switchboard`'s targets, the `NotifyEntity` degraded path, the
  Companion callback resolution order, the fan-out guarantees, the per-row
  texts, the `managed` row key and the two v0.4 repairs.
- Deferral de-duplication on `(person, target, tag)` — §6 only means the
  `tag` half is now always populated.
- `ConfigEntry.version` / `minor_version`: the three new options keys are all
  optional with a defaulted absence, so nothing migrates.

## Consequences

- `docs/contract.md` gains a "v0.5 addendum (ADR-0019)" block: two drop
  reasons (`expired`, `not_notified`), the `ttl_minutes` option and `data`
  key, the `summary` person key, the `clear_done` row key, the
  `switchboard_done` `data` key, and the default tag / notification-id rule.
  Fourth amendment authorized by ADR-0011; released as 0.5.0, still not a
  major version, because nothing is removed or renamed.
- `STORAGE_MINOR_VERSION` 3 → 4 (`episodes`), with a migration that inserts an
  empty list. This is the first time an episode outlives a restart, so it is
  also the first store change since ADR-0016.
- `strings.json` and `translations/{en,fr,es}.json` grow: `common.summary_title`
  (`{count}`), `common.summary_line` (`{title}`, `{message}`),
  `common.summary_line_untitled` (`{message}`), the two new drop reasons
  wherever reasons are shown, the `detail` sentences for them, and the new
  options fields (`ttl_minutes`, `summary`, `clear_done`).
- `explain` gains nothing and loses nothing. It reports `deferred` under the
  same three conditions; whether that deferral will later expire is not
  something a read-only answer about *now* can promise, and adding a fourth
  `decision` value would need its own ADR (ADR-0018 §1 says so).
- `docs/ARCHITECTURE.md`'s deferral lifecycle is rewritten: queue → (expire |
  re-decide) → (hold | drop | deliver | summarise), with two entry points into
  the flush instead of one.
- `docs/known-issues.md`: the 2026-09-07 S2 entry "a deferral now re-checks
  silence, but only silence" is resolved in both its halves (§3 and §4). It is
  marked, not deleted.
- A future ADR is needed to: give `ttl_minutes` a per-row scope, make the
  summary's line format configurable, add a fifth `event.switchboard_delivery`
  type for a clear, let `explain` predict an expiry, or extend episodes to
  rows that name no `alert_entity`.
