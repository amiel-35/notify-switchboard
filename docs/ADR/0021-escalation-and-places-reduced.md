# ADR 0021: Escalation and places, reduced — one step when nobody is home, a scheduled floor, the routing table as an entity, acknowledgement authorship, outputs that are not people, and a critical push that is actually critical

Date: 2026-09-07

## Status

Accepted.

## Context

0.6.0 stopped adding and consolidated. 0.7.0 adds again, and the list it adds
from is deliberately shorter than the one the first draft of this sprint
carried: an earlier version of this ADR — written for a sprint that was then
reduced by the maintainer after the product review — proposed seven decisions
of which four are here and three are not. What survived, and what did not, is
recorded in §9 rather than quietly dropped.

What the router still cannot do, and what 0.7.0 answers:

- **Insist when the house is empty.** An alert fires, nobody is in, and the
  message is routed at exactly the priority the target was configured with —
  which is the priority chosen for a household that is at home to hear it.
- **Be quiet about small things without being quiet about everything.** A
  person is silent or not. There is nothing in between, so a night that lets a
  leak through has to let the shopping list through too.
- **Say what the routing table is.** Every card written against this
  integration re-declares the slugs, the names, the snooze durations and the
  wake times in its own YAML, because nothing exposes them. That copy goes
  stale on the first options edit, silently.
- **Say who acknowledged.** `context.user_id` reaches both entry points and is
  already in the `acknowledged` event payload; the `person.*` the router
  resolved in order to decide the action is thrown away.
- **Talk to a thing that is not a person.** A kitchen speaker, a wall tablet's
  toast overlay: an output with no presence, no phone and no bedtime. Today it
  has to be modelled as a fake `person.*`, with a `person.*` entity that never
  moves and a silence that never fires.
- **Talk to a `notify` entity.** Alexa Devices, Telegram, a core `NotifyGroup`
  ship `notify.*` **entities**, not legacy services. The router only knows how
  to call a service, so those integrations are unreachable from it.
- **Make a `critical` message actually critical.** The router has had four
  priorities since 0.1.0 and `critical` has meant exactly one thing to a phone:
  nothing. It bypasses a silence *inside the router* and then arrives as an
  ordinary push, which a phone in Do Not Disturb does not play.

That last one has a companion defect that has been in the contract since v0:
the router forwards `data.priority` — its **own** input key — to Companion
outputs, where `mobile_app` on Android reads `data.priority` and knows exactly
one value, `high`. A message routed as `info` therefore hands Android a
`priority` it does not understand, and a message routed as `critical` hands it
`critical`, which is also not `high`. Nobody noticed because nothing on the
Android side errors: the key is ignored and the notification is delivered at
the default priority.

## Decision

### 0. The guard-rail: no clock and no counter of the router's own

**Invariant.** The router owns **no timer and no counter of its own** for
anything in this ADR. Every rule below is evaluated at **decision time**,
synchronously, from entities and records that already exist.

Concretely, and this is what a reviewer should check every rule against:

- No `async_call_later`, no `async_call_at`, no `async_track_point_in_time`,
  no `async_track_time_interval` is added.
- No counter is incremented by the passage of time, and no counter is added at
  all.
- Nothing is re-armed on load, because nothing was armed.
- `STORAGE_VERSION` / `STORAGE_MINOR_VERSION` do not move: nothing new is
  persisted.

The invariant is what decided §9 more than any single feature did. "Twenty
minutes after the alert started, if nobody acknowledged, tell the second
person" reads like one line of `async_call_later` and is in fact a timer to
cancel on unload, a timer to re-arm after a restart, a timer to reconcile with
an alert that ended while Home Assistant was down, a timer that fires for a
config entry that no longer exists, and a second clock racing the one core
already runs. ADR-0002 says this integration is a pure notify proxy. A proxy
that wakes itself up is not one.

### 1. `escalate_when_nobody_home` — one step, for one decision

`escalate_when_nobody_home` is a **target** key, boolean, **default false**,
written into the target only when true — so every target written before 0.7.0
keeps the exact dict it had.

When it is true, the router evaluates, at decision time, whether **any**
person of the target's audience is `home`. If none is, the call's priority is
raised **one step** for this decision only:

| From | To |
|---|---|
| `info` | `normal` |
| `normal` | `high` |
| `high` | `critical` |
| `critical` | `critical` (unchanged) |

The rank is `info < normal < high < critical`, which is the order
`VALID_PRIORITIES` already declares.

The target's `default_priority` is not changed, the caller's `data.priority` is
not changed, and the next call re-evaluates the question from scratch.

**One step, not straight to `critical`.** The first draft of this sprint
escalated to `critical` in one jump, which made every `info` message in an
empty house bypass every silence and — with §7 — ring a phone in Do Not
Disturb. Escalation is a statement that *nobody is here to notice*, not a
statement that the message became a life-safety alert. One step is the
smallest thing that says it, and it composes: a target whose alerts matter
sets `default_priority: high` and gets a critical push out of an empty house,
which is exactly the case the feature exists for. A target of shopping lists
gets a `normal` message and nothing else.

Five things this deliberately pins:

- **`home` means the literal state `home`** (`$HA_CORE_SRC/homeassistant/
  const.py` line 301, `STATE_HOME`). A `person.*` reports its zone name,
  `not_home`, `unknown` or `unavailable` otherwise
  (`$HA_CORE_SRC/homeassistant/components/person/__init__.py`,
  `PersonEntity._attr_state`, and `IGNORE_STATES = (STATE_UNKNOWN,
  STATE_UNAVAILABLE)` line 72). Anything that is not the string `home` — a
  named zone, an unknown state, a person the state machine has never heard of
  — counts as "not home". A router that treated `unknown` as "probably home"
  would decline to escalate exactly when it has the least information.
- **Only persons are asked.** A bare output (§5) has no presence, so it never
  makes a house occupied and never keeps one empty either: a target whose
  audience is *only* bare outputs has no person to ask about and escalates
  nothing.
- **It does not touch the presence rule.** A `home_only` target with nobody
  home drops every person with reason `presence`, escalated or not: the target
  said "only tell them when they are here", and raising a priority is not
  permission to contradict that. On such a target the flag is inert, and that
  is the correct outcome rather than an oversight.
- **An empty audience escalates nothing**, because there is nothing to decide
  about. No delivery, no drop, no `escalated`.
- **The escalated priority is the effective one everywhere downstream**: the
  silence and snooze bypass (`critical` only), the `authenticationRequired`
  flag on Companion buttons (`AUTHENTICATED_PRIORITIES`), the `priority` key
  of the `routed` event, and the critical payload of §7. A message escalated
  to `critical` is a critical message in every respect, because it is the
  message that was actually sent.

`explain` reports it as `escalated: nobody_home` (§8).

### 2. A scheduled priority floor, carried by a silence entity

When one of a person's configured silence entities is `on` **and** its state
attributes carry `min_priority`, that entity silences only the calls **below**
that value; calls at or above it pass. The reason a floored silence produces is
the existing `silenced` — no new drop reason is introduced.

A silence entity that is `on` and carries no such attribute silences
everything, exactly as it does today.

The mechanism this is designed for is core's `schedule`. A `schedule`'s
per-block `data:` is validated by `CUSTOM_DATA_SCHEMA = vol.Schema({str:
vol.Any(bool, str, int, float)})`
(`$HA_CORE_SRC/homeassistant/components/schedule/__init__.py` line 122; the key
name is `CONF_DATA` in `.../schedule/const.py` line 23) and, while that block is
the active one, `Schedule._update` (line 332) reads it at line 346 and does
`self._attr_extra_state_attributes.update(current_data)` at line 395. So a
household writes:

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
attributes — a night that lets a leak through and holds the shopping list, with
no automation and nothing of ours running.

Five rules, pinned:

- **The router reads the attribute, not the domain.** Any silence entity that
  is `on` and exposes a `min_priority` attribute is read this way, whether it
  is a `schedule`, a template `binary_sensor` or something else. Nowhere else
  does the router care what kind of entity a silence is — it asks
  `state == "on"` and nothing more (`router.state_is_on`) — and a domain check
  here would be the only exception in the module. `schedule` is the documented
  way to produce the attribute, not the only accepted source.
- **An unreadable floor silences everything.** A `min_priority` whose value is
  not one of the four priority strings — a typo, a number, a bool, a `None` —
  is ignored and the entity behaves as an ordinary silence. `CUSTOM_DATA_SCHEMA`
  accepts any string, so `min_priority: loud` reaches the state attributes
  intact and must fail towards quiet, never towards noise.
- **The strictest `on` silence decides.** A person with several silence
  entities on at once is silenced when **any** of them would silence this call:
  one with a `high` floor and one with no floor together silence everything,
  because the floor-less one does. Silence has always been an OR across
  sources (ADR-0016) and a floor narrows one source, not the union.
- **A temporary `notify_switchboard.silence` has no floor and never will.** It
  is a gesture ("quiet for the next hour"), not a policy, and it carries no
  state attributes to read. It silences everything, as it does today.
- **A floor changes which calls a silence catches, not what happens to a
  caught call.** A call the floor catches is dropped with `silenced` — or
  deferred to a wake time, or to the silence's own published end
  (ADR-0020 §3), or re-decided at a flush, or summarised — exactly as an
  unfloored silence's call is. `critical` still bypasses everything, floor or
  no floor.

`explain` names the floor and the entity that carries it in `detail` (§8).

**No per-person `min_priority`.** See §9: a person who wants a standing floor
writes a `schedule` that is `on` all day and carries one, which is the same
mechanism with no second concept.

### 3. `sensor.switchboard_routing_table` — the table, for user interfaces

One new global entity, a frozen public name. Its **state** is the number of
targets. Its attributes are two lists:

```yaml
targets:
  - slug: leak
    name: Leak
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
row has none, never absent, so a card reads the same shape for every row;
`wake_time` is the `"HH:MM:SS"` string the options carry, so a card can print
it without parsing anything. `audience` is reported verbatim, bare outputs
(§5) included, because that is what the audience is.

**What is not in it, and why the list is closed.** No `default_data` — it is
the one target key that carries whatever the user put in it, which is where an
API key, a webhook path or a phone number ends up, and a state attribute is
readable by anybody who can read the state machine. No `default_priority`,
`presence_rule`, `observer_mode`, `message`, `done_message`, `default_title`,
`managed`, `clear_done`, `escalate_when_nobody_home`: not because they are
secret, but because this entity exists to stop cards duplicating the six fields
they actually re-declare today, and every field added to it is a field frozen
for ever. A card that needs to know what *would* happen already has
`notify_switchboard.explain` (ADR-0018 §1). No `outputs` per person either: a
person's `notify.*` services are the one part of the table that maps to their
physical devices, and `explain` already discloses them to a caller who asks
about that person specifically.

Both attributes are declared **unrecorded**
(`$HA_CORE_SRC/homeassistant/helpers/entity.py` line 554,
`Entity._unrecorded_attributes`; unioned into
`__combined_unrecorded_attributes` by `__init_subclass__` at line 600 and
published to the recorder at line 1539 — the mechanism `schedule` itself uses
for its custom block data, `.../schedule/__init__.py` line 286). They are
configuration, they change only on an options edit, and writing the whole
routing table into the recorder on every state write would be a database cost
for nothing.

### 4. Acknowledgement authorship, in the event and nowhere else

The `acknowledged` `event.switchboard_delivery` payload gains **two** keys
alongside the `target` and `alert_entity` it already carries:

| Key | Meaning |
|---|---|
| `user_id` | `call.context.user_id` for a service call, `event.context.user_id` for a Companion callback. Already in the payload today; frozen by this ADR |
| `person` | that `user_id` resolved through the **canonical** link only, or `null` |

`person` is the `user_id` state attribute of a `person.*`
(`$HA_CORE_SRC/homeassistant/components/person/const.py`,
`PersonEntityStateAttribute.USER_ID`), which is contract v0.3 §"Callback
resolution order" step 1 and which the router already computes in
`_person_for_user_id`. It is `null` when that does not resolve. The `device_id`
fallback of step 2 is deliberately **not** used here: guessing who acknowledged
from a device name is worse than saying "unknown", and step 3 ("apply to the
whole audience") has no meaning for an author.

**No entity and no store.** The first draft added
`sensor.switchboard_acknowledgements`, with a daily count, a `last` record and
a `by_target` mapping, persisted in the same store document as the episodes.
It is dropped (§9): the event carries the fact, and a household that wants the
history writes four lines of trigger-based template sensor on
`event.switchboard_delivery` — which is a recorder-backed history, in the
user's own entity, rather than a second history this integration would have to
migrate for ever.

No new event type: the four `event.switchboard_delivery` types are unchanged.

### 5. Bare outputs — an audience entry that is not a person

An entry of a target's `audience` may be a `notify.*` **service name** —
`notify.kitchen_speaker`, `notify.tablet_toast` — instead of a `person.*`
entity id. The two are told apart by domain, and by nothing else: an audience
entry in the `notify` domain is a bare output, an entry in the `person` domain
is a person, and anything else is the `unknown_person` drop it already is.

A bare output is exactly what its name says and nothing more:

- **No presence**, so no presence rule and no part in §1's question.
- **No silence, no snooze, no deferral, no TTL, no wake time, no summary.** It
  is delivered now or it is not delivered.
- **No Companion buttons**, no `actions`, no `authenticationRequired`, no
  `notification_id`, no router-added `tag`. It receives exactly the caller's
  `data` merged with the target's `default_data`, and nothing the router
  invented — the ADR-0019 §6 rule, applied to an output that is nobody's
  phone. If it happens to be a `mobile_app_*` service, §7 applies to it like
  any other Companion output; that is a property of the service, not of the
  audience entry.
- **It takes part in episodes.** The episode of a target's `alert_entity`
  records a delivered bare output the way it records a person, so a `done`
  message reaches only the bare outputs that heard the episode's messages and
  every other bare output of the audience is dropped with `not_notified`
  (ADR-0019 §5, unchanged).
- **It is a delivery, and it is counted.** One bare output that answers is one
  `sensor.switchboard_routed_today` increment and one `routed`
  `event.switchboard_delivery` whose `person` key is `null` and whose `target`
  is the slug. One that does not exist, times out or raises is one
  `delivery_failed` drop, the same output-failure counter and the same
  `missing_output_*` repair as a person's output. No new drop reason.
- **The recursion guard applies.** A bare output resolving to
  `notify.switchboard*` is refused at config time and at runtime, with the
  existing `recursion` reason.
- **No `places` object, no schedule, no new menu.** The audience selector of
  the `target` step simply offers the registered `notify.*` services alongside
  the persons, and `validate_target` accepts either.

`explain` lists them under a new top-level `outputs` key (§8).

This is the reduced form of "places", and it is the whole of it. A speaker in
the kitchen is not a place, it is a thing that can be told something; the
household that wants "tell the kitchen when somebody is in the kitchen" writes
a target whose audience is the kitchen speaker and drives it from an
automation that already knows about the kitchen. What is deferred is the object
that would have modelled the room itself (§9).

### 6. Entity outputs — `notify.send_message`

An output — a person's, or a bare one — that is a `notify` **entity id** is
delivered with `notify.send_message` (`$HA_CORE_SRC/homeassistant/components/
notify/__init__.py` lines 84-91, registered on the entity component;
`SERVICE_SEND_MESSAGE` in `.../notify/const.py` line 29), carrying `message`
and `title` and nothing else.

**Resolution order, pinned: service first, then entity.** A legacy notify
service and a notify entity share one namespace — `notify.living_room` can be
either — so the order has to be stated rather than discovered. A registered
legacy service wins, which is exactly today's behaviour for every output that
exists today; an output that is not a registered service and *is* a `notify.*`
entity in the state machine is called through `notify.send_message`.

**`data` is not carried, and that is core's shape, not a shortcut.**
`NotifyEntity.async_send_message` takes `message` and an optional `title`
(`.../notify/__init__.py` line 185) and the entity service schema accepts only
those two (`ATTR_MESSAGE` required, `ATTR_TITLE` optional). `title` itself only
reaches the platform when the entity declares `NotifyEntityFeature.TITLE`
(line 63; the base implementation drops it otherwise, and `NotifyGroup` does
the same for a member that does not declare it —
`.../components/group/notify.py` lines 176-190). The router passes `title`
regardless and lets core decide, because whether a given entity uses it is the
entity's business. This is the same limitation the contract already documents
for the router's own degraded `notify.switchboard` entity, now stated in the
other direction: a target whose output is an entity cannot carry `default_data`
to it, cannot carry a caller's `data`, and gets no tag, no buttons and no
critical payload.

**A missing entity is handled like a missing service, and the router has to
check for itself.** `notify.send_message` is an entity service: an
`entity_id` that resolves to nothing is **logged and skipped**, not raised
(`$HA_CORE_SRC/homeassistant/helpers/service.py`,
`_resolve_entity_service_call_entities` line 675, `referenced.log_missing(...)`),
and an entity that exists but is `unavailable` is filtered out of the
candidates in the same function. Calling and hoping would therefore count a
delivery that never happened. So the router resolves the entity **before**
calling: absent from the state machine, or `unavailable`, is a missing output —
the same `failing_outputs` counter, the same `missing_output_*` repair after
`MAX_CONSECUTIVE_OUTPUT_MISSES`, the same `delivery_failed` drop when it was a
person's only output, and the same `missing_outputs` list in `explain`.

**The recursion guard is extended, and it already had to be.** The router's own
degraded path *is* a notify entity, `notify.switchboard` (contract §Names), so
without §6 an output naming it was a service that did not exist and did nothing;
with §6 it would be a real entity and a real loop. `is_recursive_output` already
matches `switchboard` and `switchboard_*` after stripping the `notify.` prefix,
which covers the entity id as written; what this ADR adds is that the check runs
on the **entity** path too, before the state lookup, and that a target
configured with it is refused at config time exactly as a recursive service is.

### 7. The critical payload, translated per OS

Two changes to what a `mobile_app_*` output receives, and to nothing else.

**(a) The router's own `priority` key is stripped. Unconditionally.**
`data.priority` is a *router input* (contract §Input: it selects the effective
priority) and has never been a Companion key. `mobile_app` on Android reads
`data.priority` and knows one value, `high`; on iOS it means nothing at all.
From 0.7.0 the router removes it from the `data` it forwards to a
`mobile_app_*` output, whatever the priority is and whatever the option below
says.

This is a **contract change**, and it is written as one in `docs/contract.md`:
until 0.6.x, a caller who wrote `data: {priority: high}` had that key delivered
to their phone, where by coincidence it was the one value Android understands.
From 0.7.0 the router puts `priority: high` there itself, and only when the
message really is critical (b). Every other output — a bare `notify.*`, a
speaker, a webhook — keeps receiving `priority` exactly as before: it is the
caller's key and the router is a proxy.

**(b) When the effective priority is `critical`, the Companion keys are
added.** "Effective" means after §1: a `high` message escalated by an empty
house is critical here too. The keys are the ones the Companion documentation
gives (<https://companion.home-assistant.io/docs/notifications/critical-notifications/>,
fetched 2026-09-07):

| OS | Keys added under `data` |
|---|---|
| iOS / iPadOS / watchOS | `push: {sound: {name: "default", critical: 1, volume: 1.0}}` |
| Android | `ttl: 0`, `priority: "high"`, `channel: "alarm_stream"` |

The page's words for what those buy: a critical alert "always appear[s] at the
top of your lock screen above all other notifications, and play[s] a sound even
if Do Not Disturb is enabled or the iPhone is muted"; on Android the alarm
stream options "make the device ring even if on vibrate/silent ringer mode",
while a default notification respects Do Not Disturb. `ttl: 0` and
`priority: high` are what push the message through Firebase immediately rather
than letting it be batched.

**The OS is read from the registration.** The output service name is
`slugify(f"mobile_app_{device_name}")` (`.../notify/legacy.py`), which is what
`companion_service_name` already computes, so the router matches the output
against the `mobile_app` config entries and reads the matching entry's
`os_name` (`$HA_CORE_SRC/homeassistant/components/mobile_app/const.py` line 36,
`ATTR_OS_NAME`; the same entry data the router already reads `user_id` from,
line 17, and `device_name` from, line 34). The match is case-insensitive:
`ios`, `ipados` and `watchos` take the Apple set, `android` takes the Android
set, and **anything else — an unknown string, an entry with no `os_name`, no
matching registration at all — takes both sets**. Both is right rather than
neither: the keys of one OS are inert on the other, and a household whose
registration predates an `os_name` should get a phone that rings, not a phone
that is quiet because the router could not identify it.

**Caller-set keys win, and `push` counts as one key.** A key the caller (or the
target's `default_data`) already wrote is never overwritten: a caller who set
`channel: my_alerts` keeps it. `push` is treated as a **single** caller key
rather than merged sub-key by sub-key — if the caller supplied any `push`
mapping, the router adds nothing under it. Merging into a nested mapping the
caller wrote is where a rule like this stops being predictable, and the escape
hatch the Companion page itself documents is one key: a household that prefers
`push: {interruption-level: critical}` to the sound form writes it and the
router leaves it alone.

`priority` is the one exception to "caller wins", and (a) is why: it is
stripped before (b) runs, so the router's `priority: high` is not contending
with a caller's value. A caller's routing priority is not a Companion priority.

**The global option `critical_payload`.** `entry.options["critical_payload"]`
is a boolean, **default true**, absent meaning true — so no migration and no
options rewrite. When it is false, (b) adds nothing; (a) still strips. A
household that hands its own Companion `data` from an automation, or that has
a phone where a critical alert is unwelcome, turns it off in one place rather
than target by target.

**Where it does not apply.** A wake-time summary's `data` is *built*, not
merged (ADR-0019 §2), and a critical message is never deferred, so a summary
never carries a critical payload. A `clear_notification` housekeeping call is
not a message and carries no payload. A `NotifyEntity` output (§6) carries no
`data` at all.

### 8. What `explain` says

`notify_switchboard.explain`'s response gains **two** top-level keys, alongside
`target`, `priority` and `persons`:

| Key | Type | Meaning |
|---|---|---|
| `escalated` | `"nobody_home"` or `null` | which rule raised this decision's priority |
| `outputs` | list of `notify.*` service names | the target's bare outputs (§5), in audience order; `[]` when it has none |

and `priority` reports the **escalated** priority, because `explain` answers
"what would happen to a message sent right now" and right now the escalation is
part of that.

Two edges, pinned rather than left to a reader:

- **`escalated` is populated only when the rule actually changed the
  decision.** A target with the flag on, nobody home, and a call that is
  already `critical` changes nothing, so `escalated` is `null`. Reporting a
  rule that did nothing would make the key useless for the question a card asks
  it ("why is this louder than I configured?").
- **`outputs` is the target's, not a person's.** A person's outputs stay where
  they are, in that person's entry of `persons`. The top-level key exists
  because a bare output has no person to hang off.

The three `decision` values are unchanged and no fourth one is added. No new
drop reason travels in `reason`: a floored silence (§2) reports `silenced`, and
`detail` for that case names both the entity that is on and the floor it
carries, because naming only the entity leaves the user unable to tell why the
`high` message got through and the `normal` one did not.

`explain` remains a pure evaluation: it reads person states and silence
attributes and writes nothing.

### 9. Deferred, with the reason and the alternative

Each of these was in the first draft of this sprint and was cut by the
maintainer after the product review. None is rejected for ever; each needs an
ADR of its own to come back.

| Deferred | Why it was cut | The native answer today |
|---|---|---|
| **Escalation after N minutes** (`escalation_after_minutes` + `escalation_audience`) | It needs the episode to know **when** it started, which is a store migration and a persisted timestamp — a state machine the router does not have. And because the router is only called when the alert calls it, the delay would round up to the alert's `repeat` interval, a documented imprecision on the one feature whose whole value is being on time | A template `binary_sensor` with `delay_on`, a second `alert:` on it and a second target with the wider audience. Written up in `docs/blueprints.md` §"Escalation after N minutes": core's own `delay_on` is the timer, cancelled by core when the condition clears, restored by core after a restart |
| **`max_deliveries`** | A counter, which §0 refuses. It would also have to live in the episode record and be reset by an episode lifecycle the router does not own | The alert's own `repeat:` list is the household's bound on how often it is told; `notify_switchboard.snooze` is the per-person one |
| **Per-target `require_authentication`** | A tri-state on a form this project spent 0.6.0 shortening, for a case nobody has hit. The `docs/known-issues.md` entry of 2026-09-07 that names it stays open, unchanged | None. The rule remains "authenticated when the effective priority is `high` or `critical`" |
| **Per-person `min_priority`** | §2 covers the use case with a mechanism the household can also schedule, and two floors that can disagree is a worse form than one | A `schedule` that is `on` all day and carries `min_priority`, listed as that person's silence entity |
| **`sensor.switchboard_acknowledgements`** | A second history, persisted in this integration's store, for a fact the `acknowledged` event already carries — and a `last` / `by_target` memory that would have had to survive the daily reset, the reload and the restart | §4's event, plus a trigger-based template sensor on `event.switchboard_delivery` if the household wants it recorded |
| **Labels, areas, floors on a target** | The successor of the `class` key 0.6.0 removed, and still with no consumer. A grouping nothing reads is what ADR-0020 §4 deleted | None needed yet |
| **A `places` object** | §5 gives the useful half — an output that is not a person — without a second addressing model beside the audience | §5 |

## Rejected alternatives

- **Escalate straight to `critical` (§1).** The first draft's rule. It turns
  every `info` message in an empty house into one that bypasses silence and,
  with §7, rings a phone through Do Not Disturb. "Nobody is here" is not
  "this is a life-safety alert".
- **A per-person `min_priority` alongside the scheduled floor.** Two floors
  that can contradict each other, for one use case, when a `schedule` that is
  always `on` expresses the standing version of the same thing.
- **A new drop reason for a floored silence** (`below_min_priority`). It is a
  silence: the entity is on, the user's remedy is the same switch, and
  `explain`'s `detail` is where the floor belongs. A reason exists to send
  somebody to the right place, and this one would send them to the same place
  under a second name.
- **Putting `outputs` and `default_data` in
  `sensor.switchboard_routing_table`** to make it a complete dump of the
  options. See §3: `default_data` is where secrets live, and a state attribute
  is world-readable to anybody who can read the state machine.
- **Modelling a bare output as an implicit person.** It would make the audience
  uniform at the cost of a `PersonConfig` with no `person.*`, which every
  presence, silence, snooze, deferral, summary and repair path would then have
  to special-case anyway — and it would put a fake person in
  `sensor.switchboard_routing_table`'s `persons` list and in every card that
  reads it.
- **Resolving an entity output before a service output.** The reverse of §6's
  order. It would change the behaviour of an installation where both exist
  under one name, which is the one case the order is for.
- **Carrying `data` to a `NotifyEntity` output** by calling the platform
  directly rather than through `notify.send_message`. It would mean reaching
  past a public service into another integration's entity object; the
  limitation is core's and is documented rather than worked around.
- **Adding the critical payload for every output, or for the
  `persistent_notification` output.** The keys are Companion's. ADR-0019 §6's
  amendment says a key the router adds goes only to the outputs that read it,
  and a sibling adapter that validates its `data` raises on a key it does not
  know.
- **Making `critical_payload` a per-target key.** It is a property of the
  household's phones, not of what the message is about. One global option, one
  place to turn it off.
- **Keeping `data.priority` on Companion outputs "for compatibility".** It is
  the key that makes an Android device see a `priority` it does not understand
  on every single message, and it is the exact key §7(b) needs to set itself.
  Leaving it would mean the router's own critical payload could be silently
  overridden by the routing priority of the message it belongs to.

## What does not change

- Every v0 / v0.2 / v0.3 / v0.4 / v0.5 / v0.6 frozen name; the **four**
  `event.switchboard_delivery` event types; the three `explain` `decision`
  values; the six `notify_switchboard.*` services, with no new one, no changed
  field and no changed refusal; the eleven drop reasons — §5 and §6 add none.
- The routing rules of contract §"Routing decision" for a target that carries
  no `escalate_when_nobody_home`, an audience of persons only, outputs that are
  registered services, and silence entities that carry no `min_priority`: the
  decision is byte-for-byte the one 0.6.0 makes.
- `critical` remains the only priority that bypasses silence and snooze. §1
  escalates *to* it; it does not add a second bypass.
- The ADR-0009 allow-list, the callback resolution order, the fan-out
  guarantees and the 30-second per-output timeout, the per-target texts,
  `managed`, `clear_done`, `summary`, `ttl_minutes`, the default tag /
  notification-id rule, ADR-0020 §3's absent-`wake_time` deferral, and the
  episode lifecycle of ADR-0019 §5 and §6.
- `ConfigEntry.version` / `minor_version`, `STORAGE_VERSION` and
  `STORAGE_MINOR_VERSION`: every new options key is optional with a defaulted
  absence, and nothing new is persisted, so nothing migrates.

## Consequences

- **Version 0.7.0**, and a **v0.7 addendum to `docs/contract.md`** — the sixth
  amendment authorized under ADR-0011. It adds one frozen entity name
  (`sensor.switchboard_routing_table`), one target key
  (`escalate_when_nobody_home`), one global option (`critical_payload`), the
  `min_priority` state attribute a silence entity may carry, two `explain`
  top-level keys (`escalated`, `outputs`), two `acknowledged` payload keys
  (`user_id`, `person`), audience entries that are `notify.*` service names,
  outputs that are `notify.*` entity ids — and **removes one thing**:
  `data.priority` no longer reaches a `mobile_app_*` output. That removal is
  the only breaking change of 0.7.0 and is why the addendum states it plainly
  rather than folding it into the critical-payload paragraph.
- **`const.py`** gains `CONF_ESCALATE_WHEN_NOBODY_HOME`, `CONF_CRITICAL_PAYLOAD`,
  `ATTR_MIN_PRIORITY`, `ATTR_ESCALATED` and `ESCALATED_NOBODY_HOME`, the
  Companion payload keys and their two frozen dicts, `ATTR_OS_NAME`, and the
  `notify.send_message` service name. `PRIORITY_RANK` (or a
  `escalate_one_step` helper) belongs next to `VALID_PRIORITIES`, whose order
  already *is* the rank.
- **`router.py`** carries the pure half: one step up the rank, the floor
  comparison, telling a bare-output audience entry from a person. `decide` is
  where a bare output becomes its own `RoutedDelivery` with `person=None`, and
  `RoutingContext.silenced` stops being `dict[str, bool]` — it has to carry the
  floor each `on` entity publishes, not only whether it is on.
- **`dispatcher.py`** carries the impure half: reading the `min_priority`
  attribute into the context, resolving a `notify` entity output, the
  `mobile_app` `os_name` lookup, and the payload surgery of §7 inside
  `_async_call_output`, next to the scoping rule that is already there.
- **`sensor.py`** gains one entity, `strings.json` and
  `translations/{en,fr,es}.json` gain its name, the `escalate_when_nobody_home`
  field with its helper text, the `critical_payload` option, and the
  `detail_silenced` sentence's floor variant.
- **The options flow** gains one boolean on `target_advanced` — not on
  `target`, whose five fields ADR-0020 §1 froze — one boolean on the `general`
  step, and an audience selector that offers `notify.*` services alongside the
  persons. `validate_target` accepts an audience entry in either domain.
- **`docs/known-issues.md`** keeps its `require_authentication` entry open and
  marks it as deferred again by this ADR; it gains one entry for the real-device
  evidence a critical iOS push still needs.
- **`docs/blueprints.md`** gains the "Escalation after N minutes" recipe, which
  is the native answer §9 promises rather than a note saying the feature was
  cut.
- **The cards repository** (separate PR, recorded here so the decision is not
  lost between two repositories): with `sensor.switchboard_routing_table`
  shipping, cards 0.2.0 drop their `target_map` and `snooze_minutes`
  configuration and read the entity instead.
- **Real-device evidence is outstanding.** Nothing in this repository can prove
  that an iOS phone rings through Do Not Disturb; the acceptance tests prove
  the router emits the documented keys. One observed critical push on a real
  iOS device is the sprint's definition of done and is recorded in
  `docs/known-issues.md` until it happens.
- **A future ADR is needed to**: bring back anything in §9, add a second
  escalation step, escalate on anything other than presence, put `outputs` or
  `default_data` in the routing-table entity, give a bare output any of the
  properties §5 denies it, carry `data` to a `NotifyEntity` output, or change
  the resolution order of §6.
