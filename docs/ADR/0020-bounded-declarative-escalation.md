# ADR 0020: Bounded, declarative escalation — nobody home, a wider audience after N minutes, a delivery cap, acknowledgement authorship, the routing table as an entity, priority floors, per-row authentication

Date: 2026-09-07

## Status

Accepted.

## Context

0.5.0 closes the loop on an episode: the router knows who it told, it stops
talking at night, it tidies up after itself. What it still cannot do is
*insist*. A leak alert fires at 03:00, the one person in the audience is
asleep behind a silence, and the router does exactly what it was asked to do
— nothing — until the wake time. Nobody is escalated to, nothing gets louder,
and the household finds out at 07:00.

Every escalation feature is a trap for an integration like this one, because
the obvious implementation is a timer. "Twenty minutes after the alert
started, if nobody acknowledged, tell the second person" reads like a
`async_call_later(1200, ...)` — and that one line brings with it a timer to
cancel on unload, a timer to re-arm after a restart, a timer to reconcile with
an alert that ended while Home Assistant was down, a timer that fires for a
config entry that no longer exists, and a second clock racing the one core
already runs. ADR-0002 says this integration is a pure notify proxy. A proxy
that wakes itself up is not one.

The same trap exists in the small: "after three notifications, stop" wants a
counter that ticks on its own; "after five minutes of nobody home, escalate"
wants a debounce.

There is also a plainer gap, unrelated to escalation but on the same surface.
Two things the router knows and refuses to say:

- **Who acknowledged.** `context.user_id` is logged on every refusal and
  carried in the `acknowledged` event, and that is the end of it. There is no
  entity a card can read to answer "who turned the alert off?", and the event
  does not even carry the `person.*` the router already resolved in order to
  decide the action.
- **What the routing table is.** Every card written against this integration
  so far re-declares the slugs, the names, the snooze durations and the wake
  times in its own YAML, because nothing exposes them. That duplication
  silently goes stale on the first options-flow edit.

And two known limitations that are cheap to close on the same pass:
`require_authentication` per row (`docs/known-issues.md`, 2026-09-07 S1,
"`authenticationRequired` cannot be overridden per row"), and the absence of
any per-person priority floor — a person can be silent or not, and nothing in
between.

## Decision

### 0. The guard-rail: no clock of the router's own

**Invariant.** The router owns **no timer and no counter of its own** for
escalation. The only clock is core `alert`'s `repeat`. The only state is what
the store already keeps per episode. Every rule in this ADR is evaluated at
**decision time**, synchronously, from entities and records that already
exist.

Concretely, and this is what a reviewer should check every rule below
against:

- No `async_call_later`, no `async_track_point_in_time`, no
  `async_track_time_interval` is added for escalation.
- No counter is incremented by the passage of time. The one counter this ADR
  introduces (§3) is incremented by a delivery and lives in the episode
  record, next to the recipients ADR-0019 §5 already stores there.
- Nothing is re-armed on load, because nothing was armed.

The clock this leans on is core's, and it is worth writing down what it does.
`AlertEntity.__init__`
(`$HA_CORE_SRC/homeassistant/components/alert/entity.py`) turns the alert's
`repeat:` list into `self._delay = [timedelta(minutes=val) for val in
repeat]`. `begin_alerting` calls `_schedule_notify`, which arms
`async_track_point_in_time` for `now() + self._delay[self._next_delay]` and
then advances `self._next_delay = min(self._next_delay + 1, len(self._delay) -
1)` — so the **last** value of `repeat` is the steady-state interval.
`_notify` calls the notifier (which is `notify.switchboard_<slug>`) and
immediately re-arms `_schedule_notify`. `end_alerting` calls `self._cancel()`.

That is a repeating call into this integration, driven by core, cancelled by
core, restarted by core, with no state of ours attached to it. An escalation
rule evaluated inside the handler of that call is free.

The price is granularity, and it is paid openly rather than papered over: see
§2.

### 1. `escalate_when_nobody_home` — a routing-table row key

`escalate_when_nobody_home` is a routing-table row key, boolean, **default
false**, written into the row only when true — so every row written before
0.6.0 keeps the exact dict it had.

When it is true, the router evaluates, at decision time, whether **any**
person of the row's effective audience is `home`. If none is, the call's
priority becomes `critical` **for this decision only**: it bypasses silence
and snooze exactly as a caller-supplied `critical` does, and it will carry the
critical payload of a later sprint. The row's `default_priority` is not
changed, the caller's `data.priority` is not changed, and the next call
re-evaluates the question from scratch.

Four things this deliberately pins:

- **`home` means the literal state `home`.** `$HA_CORE_SRC/homeassistant/
  const.py`, `STATE_HOME`; a `person.*` reports its zone name, `not_home`,
  `unknown` or `unavailable` otherwise (`$HA_CORE_SRC/homeassistant/
  components/person/__init__.py`, `PersonEntity._attr_state`, and
  `IGNORE_STATES = (STATE_UNKNOWN, STATE_UNAVAILABLE)`). Anything that is not
  the string `home` — a named zone, an unknown state, a person the state
  machine has never heard of — counts as "not home". A router that treated
  `unknown` as "probably home" would decline to escalate exactly when it has
  the least information.
- **The audience it asks about is the effective one**, i.e. after §2 has
  widened it. The question "is anybody home to hear this" has to be asked of
  the people who will actually receive the message.
- **It does not touch the presence rule.** A `home_only` row with nobody home
  drops every person with reason `presence`, escalated or not: the row said
  "only tell them when they are here", and raising a priority is not
  permission to contradict that. On such a row the flag is inert, and that is
  the correct outcome rather than an oversight.
- **An empty effective audience escalates nothing**, because there is nothing
  to decide about. No delivery, no drop, no `escalated`.

`explain` reports it as `escalated: nobody_home` (§8).

### 2. Escalation audience after N minutes — two row keys, one clock

Two routing-table row keys, both optional, both **required together**; a row
carrying one without the other escalates nothing at all, and the options flow
refuses to write half a pair:

- `escalation_after_minutes` — a positive integer.
- `escalation_audience` — a list of `person.*` entity ids.

They apply to a row that names an `alert_entity`, and to no other row. When a
call arrives for such a row and **all** of the following hold:

1. the row has an episode (ADR-0019 §5) whose start is known,
2. that episode started at least `escalation_after_minutes` minutes ago,
3. the row's `alert_entity` is in state `on` right now,

then, for that decision only:

- `escalation_audience` is **added** to the row's audience. Persons already in
  the audience are unaffected; the added persons are ordinary members of the
  effective audience for the whole of the decision — presence, floors,
  silence, snooze and the delivery cap all apply to them normally — and they
  are therefore no longer reported `not_in_audience`.
- the priority is raised **one step**: `normal → high`, `high → critical`.
  `info` stays `info` and `critical` stays `critical`. A row whose alerts are
  informational does not become urgent because time passed; a row that is
  already at the top has nowhere to go.

Condition 3 is the acknowledgement check, and it is why no separate one is
needed. Core's `AlertEntity.state`
(`$HA_CORE_SRC/homeassistant/components/alert/entity.py`) returns `on` while
`_firing and not _ack`, `off` while `_firing and _ack`, and `idle` otherwise.
`alert.turn_off` — which is what this integration's own Acknowledge button
calls — sets `_ack`, so an acknowledged alert reads `off`. "Still `on`"
therefore means "firing, and nobody has acknowledged it", read from one state
string, with no acknowledgement bookkeeping of our own.

**Granularity, stated rather than hidden.** The router is called when the
alert calls it, and the alert calls it on its own `repeat` schedule. The
escalation therefore happens at the **first repeat after N minutes**, so the
effective delay is `N` rounded **up** to the alert's repeat interval: an alert
with `repeat: [15]` and `escalation_after_minutes: 20` escalates at 30
minutes, not at 20. This is a documented property of the feature, in
`docs/contract.md`, in the options-flow helper text and in the name of an
acceptance test. A household that wants the escalation to be punctual
shortens the alert's `repeat`, which is the knob core already gives it. The
alternative — our own timer — is what §0 exists to refuse.

**The episode start.** ADR-0019 §5's `Episode` record gains `started_at`, a
UTC instant stamped when the record is opened on the `alert_entity`'s `idle →
on` transition. This is a store change (`STORAGE_MINOR_VERSION` 4 → 5); the
migration adds **nothing**, so an episode restored from a 0.5.0 document has
no start time and, by condition 1, never escalates. Inventing a start time on
upgrade would mean escalating on a fiction.

`explain` reports it as `escalated: after_minutes` (§8).

### 3. `max_deliveries` — a routing-table row key

`max_deliveries` is a routing-table row key, a positive integer, optional,
absent by default. It bounds, **per episode and per person**, how many routed
deliveries that person may receive from that row. Beyond it the call is
dropped with the **new reason `max_deliveries`**.

- **A "delivery" is what the router already counts as one**: one (person,
  target) pair that reached at least one output. Not one output call, not one
  attempted call — the same unit `sensor.switchboard_routed_today` reports and
  the same moment `Switchboard._async_record_episode` already runs.
- **The count lives in the episode record**, next to the recipients, and it is
  persisted with them. No new timer, no new lifecycle: it starts at zero when
  the episode opens and it is reset — like `persons`, `outputs` and `tags` —
  when the row's *next* episode opens. That is what "reset at episode end"
  means in practice, and it is the only way to say it that ADR-0019 §5's
  "closed, not deleted" record permits.
- **A row with no `alert_entity` has no episodes, so `max_deliveries` is inert
  on it.** The key may be written, it simply never bounds anything. Bounding a
  row with no episodes would need a counter with no lifecycle — a counter of
  our own, which §0 refuses.
- **The `done` message is never counted and is always allowed**, whatever the
  cap says. A cap exists to stop the router repeating itself about a problem;
  telling somebody the problem is over is the opposite of repeating. ADR-0019
  §5's `not_notified` filter still applies to it unchanged.
- **`critical` does not bypass it.** `critical` bypasses a *person's* quiet —
  silence and snooze — because that is a promise about their attention.
  `max_deliveries` is a bound the household put on a *row*, and an escalation
  that raises priority is not permission to lift it. This matters most in the
  case it is designed for: when §2 widens the audience, the newly added people
  have their own counters at zero and hear about it, while the person already
  told three times is not told a fourth. That is escalation working, not
  escalation being blocked.

The cap is evaluated **after** presence, the priority floor, silence and
snooze, and **before** outputs are resolved: a delivery that was going to be
dropped for another reason keeps that reason and does not consume the budget.

### 4. Acknowledgement authorship

On every acknowledgement that actually happens — the Companion Acknowledge
button and `notify_switchboard.acknowledge`, after the ADR-0009 allow-list has
said yes and `alert.turn_off` has run — the router records:

```python
{
    "target": "leak",
    "person": "person.alice",  # or None
    "user_id": "01J...",  # or None
    "at": "2026-09-07T03:12:44+00:00",
}
```

- `user_id` is `call.context.user_id` for a service call
  (`$HA_CORE_SRC/homeassistant/core.py`, `ServiceCall.context` and
  `Context.user_id`) and `event.context.user_id` for a Companion callback —
  which `mobile_app` sets to the registration's own user. Both paths already
  carry it; nothing new is read.
- `person` is that `user_id` resolved through the **canonical** link only:
  the `user_id` state attribute of a `person.*`
  (`$HA_CORE_SRC/homeassistant/components/person/const.py`,
  `PersonEntityStateAttribute.USER_ID`), which is contract v0.3 §"Callback
  resolution order" step 1. It is `null` when that does not resolve. The
  `device_id` fallback of step 2 is deliberately **not** used here: guessing
  who acknowledged from a device name is worse than saying "unknown", and step
  3 ("apply to the whole audience") has no meaning for an author.
- `at` is an ISO 8601 UTC instant.

**The new global entity `sensor.switchboard_acknowledgements`.** Its state is
the number of acknowledgements since local midnight. Its attributes are `last`
(the most recent record above, or `null`) and `by_target` (a mapping from row
slug to that row's most recent record).

The name has no `_today` suffix on purpose: only the **state** is a daily
count, reset at local midnight like the other three counters. `last` and
`by_target` are memory, not statistics — "who acknowledged the leak?" is a
question whose answer must not evaporate at midnight — so they survive the
reset, the reload and the restart. The whole record set is persisted in the
same store document as the episodes and the snoozes.

**The `acknowledged` event payload** gains `user_id` and `person`, alongside
the `target` and `alert_entity` it already carries. `user_id` is in the
payload today but has never been part of the contract; both are frozen by this
ADR. No new event type: the four `event.switchboard_delivery` types are
unchanged.

### 5. `sensor.switchboard_routing_table` — the table, for user interfaces

A second new global entity. Its state is the number of routing-table rows. Its
attributes are two lists:

```yaml
targets:
  - slug: leak
    name: Fuite d'eau
    alert_entity: alert.leak
    snooze_minutes: [15, 60]
    allow_acknowledge: true
    audience: [person.alice, person.bob]
persons:
  - entity_id: person.alice
    wake_time: "07:00:00"
    summary: true
```

`targets` follows the order of `entry.options["targets"]`, `persons` that of
`entry.options["persons"]`. `alert_entity` and `wake_time` are `null` when the
row has none; `wake_time` is the `"HH:MM:SS"` string the options carry, so a
card can print it without parsing anything.

**What is not in it, and why the list is closed.** No `default_data` — it is
the one row key that carries whatever the user put in it, which is where an
API key, a webhook path or a phone number ends up. No `default_priority`,
`presence_rule`, `observer_mode`, `message`, `done_message`, `default_title`,
`managed`, `clear_done`, or any key this ADR adds: not because they are
secret, but because this entity exists to stop cards duplicating the six
fields they actually re-declare today, and every field added to it is a field
frozen for ever. A card that needs to know what *would* happen already has
`notify_switchboard.explain` (ADR-0018 §1). No `outputs` per person either: a
person's `notify.*` services are the one part of the table that maps to their
physical devices, and `explain` already discloses them to a caller who asks
about that person specifically.

Places (Router S7) are absent, because they do not exist yet.

Both attributes are declared unrecorded
(`$HA_CORE_SRC/homeassistant/helpers/entity.py`,
`Entity._unrecorded_attributes`, the mechanism `schedule` itself uses for its
custom block data). They are configuration, they change only on an options
edit, and writing the whole routing table into the recorder on every state
write would be a database cost for nothing.

### 6. Priority floors

Two floors, one static and one scheduled, both expressed as a minimum
priority. The rank is `info < normal < high < critical`, which is the order
`VALID_PRIORITIES` already declares.

**(a) A per-person floor.** `min_priority` is a person-row key, defaulting to
`info` and therefore written into the row only when it is something else. A
call whose effective priority is **below** the floor is dropped for that
person with the **new reason `below_min_priority`**. Because `critical` is the
top of the rank, it can never be below any floor; no bypass rule is needed and
none is added.

The floor is evaluated **after** the presence rule and **before** silence and
snooze. A floor is a standing statement about what a person wants to hear
about at all; a silence and a snooze are temporary states. Telling somebody
"you were snoozed" about a message their floor would have dropped anyway sends
them to the wrong switch — the same reasoning ADR-0018 §1 applies to
`explain`'s `detail`.

**(b) A scheduled floor, carried by a silence entity.** When one of a person's
silence entities is `on` **and** its state attributes carry `min_priority`,
that entity silences only the calls **below** that value, with the existing
reason `silenced`; calls at or above it pass. A silence entity that is `on`
and carries no such attribute silences everything, exactly as today.

The mechanism this is designed for is core's `schedule`. A `schedule`'s
per-block `data:` is validated by `CUSTOM_DATA_SCHEMA = vol.Schema({str:
vol.Any(bool, str, int, float)})` and, while that block is the active one,
`Schedule._update` does
`self._attr_extra_state_attributes.update(current_data)`
(`$HA_CORE_SRC/homeassistant/components/schedule/__init__.py`; the key name is
`CONF_DATA` in `.../schedule/const.py`). So a household writes:

```yaml
schedule:
  night:
    monday:
      - from: "22:30:00"
        to: "07:00:00"
        data:
          min_priority: high
```

and the entity is `on` all night with `min_priority: high` among its
attributes — a night that lets a leak through and holds the shopping list,
with no automation and nothing of ours running.

**The rule reads the attribute, not the domain.** Any silence entity that is
`on` and exposes a `min_priority` attribute is read this way, whether it is a
`schedule`, a template `binary_sensor` or something else. This is a
deliberate generalisation of the brief's "a `schedule` silence entity":
nowhere else does the router care what kind of entity a silence is — it asks
`state == "on"` and nothing more (`router.state_is_on`) — and a domain check
here would be the only exception in the module. `schedule` is the documented
way to produce the attribute, not the only accepted source.

**An unreadable floor silences everything.** A `min_priority` attribute whose
value is not one of the four priorities is ignored and the entity behaves as
an ordinary silence. A typo must fail towards quiet, never towards noise.

`explain` names the floor in `detail`, in both cases (§8).

### 7. `require_authentication` — a routing-table row key

`require_authentication` is a routing-table row key, `true`, `false` or
`null`, defaulting to `null` and written into the row only when it is not
`null`.

- `null` (or absent) — today's rule, unchanged: the Companion buttons carry
  `authenticationRequired: true` when the message's effective priority is
  `high` or `critical`.
- `true` — the buttons always carry it, whatever the priority.
- `false` — the buttons never carry it, whatever the priority.

It governs the row's Companion buttons and nothing else: it is not an
authorisation decision, and it does not touch the ADR-0009 allow-list, which
remains the only thing that decides whether a row can be acknowledged at all.
This closes the `docs/known-issues.md` entry of 2026-09-07 ("
`authenticationRequired` cannot be overridden per row"), which named exactly
this tri-state as its planned resolution.

The effective priority a `null` row reads is the **escalated** one: a `normal`
call escalated to `critical` by §1 gets an authenticated button, because the
button it gets is the one that matches the message that was actually sent.

### 8. What `explain` says

`notify_switchboard.explain`'s response gains **one** top-level key,
`escalated`, alongside `target`, `priority` and `persons`:

| Value | Meaning |
|---|---|
| `null` | nothing escalated this decision |
| `"nobody_home"` | §1 fired |
| `"after_minutes"` | §2 fired |

`priority` reports the **escalated** priority, and `persons` covers the
**effective** audience, escalation audience included — `explain` answers "what
would happen to a message sent right now", and right now the escalation is
part of that.

Two edges, pinned rather than left to a reader:

- **`escalated` is populated only when a rule actually changed the
  decision** — the priority was raised, the audience was widened, or both. A
  §1 row with nobody home and a call that is already `critical` changes
  nothing, so `escalated` is `null`. Reporting a rule that did nothing would
  make the key useless for the question a card asks it ("why is this
  louder than I configured?").
- **When both rules fire, `escalated` is `"nobody_home"`.** §2 is evaluated
  first, because it widens the audience §1 then asks its question about; §1 is
  reported, because it is the one that produced the final priority.

The three `decision` values are unchanged, and the two new drop reasons
(`max_deliveries`, `below_min_priority`) travel in the existing `reason` key.
`explain` remains a pure evaluation: it reads the episode's start time and the
alert's state, and writes nothing — in particular it does not consume a
`max_deliveries` budget.

## Rejected alternatives

- **A timer of our own** (`async_call_later` at the row's
  `escalation_after_minutes`, cancelled on acknowledgement). This is the
  obvious design and it is what §0 exists to refuse. It would need cancelling
  on unload, re-arming on load, reconciling with an alert that ended while
  Home Assistant was down, and defending against firing for a config entry
  that no longer exists — four failure modes, none of which can happen to a
  rule evaluated at decision time. It would also be a second clock racing
  core's, with no way to say which of the two is authoritative when they
  disagree.
- **A repeat counter of our own** ("escalate on the third notification"). Same
  objection in miniature: a counter that only time advances is a clock. The
  episode's delivery count of §3 is incremented by a delivery, in the same
  method that already records the episode's recipients, and it is read — never
  advanced — at decision time.
- **Changing `alert.repeat`** so the escalation is punctual (rewriting the
  user's `repeat:` list, or calling into the alert to re-arm it). The alert is
  the user's configuration and core's entity; a notify proxy that edits its
  own trigger is not a proxy (ADR-0002). Rounding up to the repeat interval,
  documented, is the honest version of the same thing.
- **An `escalation_outputs` row key** (a louder output rather than a wider
  audience). It duplicates the person's `outputs`, it has no place in the
  routing decision — which is per person, not per output — and the critical
  payload of a later sprint is the right way to make one message louder.
- **A fourth `explain` decision value** for "would be escalated". ADR-0018 §1
  fixed three values and said a fourth needs its own ADR; `escalated` as a
  separate key says the same thing without touching them.
- **Putting `outputs` and `default_data` in
  `sensor.switchboard_routing_table`** to make it a complete dump of the
  options. See §5: `default_data` is where secrets live, and a state attribute
  is world-readable to anybody who can read the state machine.
- **A `min_priority` on the row as well as on the person.** A floor is a
  statement about a person's attention; a row already has
  `default_priority` to say how loud it is. Two floors that can contradict
  each other, for one use case nobody has had.

## What does not change

- Every v0 / v0.2 / v0.3 / v0.4 / v0.5 frozen name; the **four**
  `event.switchboard_delivery` event types; the three `explain` `decision`
  values; the six `notify_switchboard.*` services, with no new one, no changed
  field and no changed refusal.
- The routing rules of contract §"Routing decision" for a row that carries
  none of this ADR's keys and a person whose `min_priority` is `info`: the
  decision is byte-for-byte the one 0.5.0 makes.
- `critical` remains the only priority that bypasses silence and snooze. §1
  escalates *to* `critical`; it does not add a second bypass.
- The ADR-0009 allow-list, the callback resolution order, the fan-out
  guarantees, the per-row texts, `managed`, `clear_done`, `summary`,
  `ttl_minutes`, the default tag / notification-id rule, and the episode
  lifecycle of ADR-0019 §5 and §6.
- `ConfigEntry.version` / `minor_version`: every new options key is optional
  with a defaulted absence, so nothing migrates.

## Consequences

- `docs/contract.md` gains a "v0.6 addendum (ADR-0020)" block: two frozen
  entity names (`sensor.switchboard_acknowledgements`,
  `sensor.switchboard_routing_table`), two drop reasons (`max_deliveries`,
  `below_min_priority`), five routing-table row keys
  (`escalate_when_nobody_home`, `escalation_after_minutes`,
  `escalation_audience`, `max_deliveries`, `require_authentication`), one
  person key (`min_priority`), the `min_priority` state attribute a silence
  entity may carry, `explain`'s `escalated` key, and the `acknowledged` event
  payload. Fifth amendment authorized by ADR-0011; released as 0.6.0, still
  not a major version, because nothing is removed or renamed.
- `STORAGE_MINOR_VERSION` 4 → 5: `Episode` gains `started_at` and a per-person
  delivery count, and the document gains the acknowledgement records. The
  migration adds nothing to an existing episode — no start time, no counts —
  so an episode restored from 0.5.0 never escalates and is never capped, which
  is the conservative reading in both cases.
- `strings.json` and `translations/{en,fr,es}.json` grow: the two new drop
  reasons wherever reasons are shown, their `explain` `detail` sentences (both
  of which name a floor or a cap), the names of the two new entities, and the
  new options fields with their helper texts — including the sentence that
  says an escalation is rounded up to the alert's repeat interval.
- `docs/ARCHITECTURE.md` gains the "no own clock" rule in words, next to the
  deferral lifecycle, and its Router S6 roadmap row moves to done.
- `docs/known-issues.md`: the 2026-09-07 S1 entry "`authenticationRequired`
  cannot be overridden per row" is resolved by §7. It is marked, not deleted.
- The options flow grows a second page on the row editor — five row keys is
  more than one screen — and a `min_priority` selector on the person editor.
- A future ADR is needed to: give a row more than one escalation step, make
  the escalation punctual by any means, expose `outputs` or `default_data` in
  the routing-table entity, add a `min_priority` to a row, let `max_deliveries`
  bound a row that has no `alert_entity`, or use the `device_id` fallback for
  acknowledgement authorship.
