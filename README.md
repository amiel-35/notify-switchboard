# Notify Switchboard

[![MIT License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=amiel-35&repository=notify-switchboard&category=integration)
[![Open your Home Assistant instance and start setting up a new integration.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=notify_switchboard)

A [Home Assistant](https://www.home-assistant.io/) custom integration that
acts as a pure `notify` **proxy**. It never delivers a notification itself:
it only forwards to `notify.*` services you already have configured
(Companion app, persistent notification, a speaker via core's own `notify:
platform: tts`, and so on — see "Adding a speaker as an output" below).

## Why

Home Assistant already has the pieces a notification system needs: `alert`
for state that persists, `event` for one-off facts, `person` for presence,
`schedule`/`input_boolean` for do-not-disturb, and `notify` as the universal
send contract. What's missing is a per-person distribution layer that sits
in front of `notify.*` and decides who should be told, and when. Notify
Switchboard is that layer, kept as close to native Home Assistant as
possible — see [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the full
contract and rationale.

## The proxy model

Notify Switchboard exposes:

- `notify.switchboard`, and one `notify.switchboard_<slug>` per **target** of
  the routing table, so the core `alert` integration can name a target under
  `notifiers:`;
- a `NotifyEntity`, documented as degraded: `notify.send_message` carries only
  `message` and `title`, so it routes to the default target with priority
  `normal`.

The vocabulary this page uses — target, person, output, audience, silence,
snooze, wake time, deferral, summary, episode, observer mode — is defined once,
in the [Glossary](#glossary) at the bottom.

A call carries `message`, `title` and `data` (`priority`, `source_entity`,
`tag`, and anything else, merged over the target's default data). For every
person in the target's audience the router checks, in order: the presence rule
against `person.*`, the person's silence entities, an active snooze — with
`priority: critical` overriding the last two — and then calls each of that
person's `notify.*` outputs.

On a Companion output it adds an **Acknowledge** button (when the target is
tied to an `alert.*` and allows it) and one **Snooze** button per configured
duration. Acknowledging turns that alert off, and only an alert listed in the
routing table. A message silenced during someone's night is not lost: it is
queued and delivered when that night ends — as **one** summary rather than a
burst, and only if it is still worth delivering (see "The night" below).

Every outgoing message also carries a name of its own: `data.tag` defaults to
`switchboard-<slug>`, so a repeat updates the notification instead of stacking
a second one, and on the `persistent_notification` output the matching
`data.notification_id` is added too. Your own `tag` always wins. Those defaults
are the router's own keys and only reach the outputs that read them —
Companion and `persistent_notification`; any other output receives your `data`
merged with the target's default data and nothing else.

## Install

The **My Home Assistant** button at the top of this page opens this repository
in [HACS](https://hacs.xyz/) on your own instance. By hand: HACS →
Integrations → menu → Custom repositories → add
`https://github.com/amiel-35/notify-switchboard`, category "Integration", then
install "Notify Switchboard" and restart Home Assistant.

## Configuration

The second button at the top of this page starts the config flow. Or:
Settings → Devices & services → Add integration → "Notify Switchboard".
Setup takes no input, and two short forms — **two fields, then five** — are
enough to get a working `notify.switchboard`:

1. **Add a person** — pick a `person.*`, then answer two things: which notify
   services reach them, and which entities mean they are silent. The notify
   services of the phones registered to that person's Home Assistant user are
   listed first, marked as theirs and already selected, and their iPhone Focus
   sensors are proposed as silence entities. Nothing is guessed from a name:
   the link is the `user_id` a Companion registration stores and the one a
   `person.*` publishes. You can still type a service that does not exist yet.
2. That is it, on a fresh install: the first person added to an empty routing
   table also gets a **target** called `default`, which becomes the one
   `notify.switchboard` uses when no target is named — so it reaches a real
   phone straight away. While that target is managed, a second person joins
   its audience automatically; editing it hands it to you for good.
3. **Add a target** — one per alert, when you want more than "everybody". Five
   fields: a slug (it becomes `notify.switchboard_<slug>`), a name, the
   `alert.*` it is about, the audience, and whether the router watches that
   alert itself. The audience offers the instance's `notify.*` services
   alongside the persons, so a kitchen speaker can be in it without being
   modelled as somebody who lives in the house (see below). Saving it shows
   the `alert:` block to paste.
4. **Test a person / Test a target** — sends one real message through the
   ordinary routing path, tagged `switchboard-test`, and shows what the router
   decided for each person.

Priority, presence rule, buttons, snooze durations, templates and default data
all have a default that suits almost everybody, and live behind **Advanced
settings of a target** — offered straight after saving, and in the options menu
for ever after. The same split applies to a person: **Advanced settings of a
person** holds their wake time and their night summary. **Escalation of a
target** is a third, one-question step, described next.

### When the house is empty

A target can carry **`escalate_when_nobody_home`** (options menu → *Escalation
of a target*, off by default). When it is on and **no** person of the target's
audience is in the literal state `home` at the moment a message arrives, that
message is routed **one step louder**, for that message only:

| From | To |
|---|---|
| `info` | `normal` |
| `normal` | `high` |
| `high` | `critical` |
| `critical` | `critical` (unchanged) |

One step, not straight to `critical`: an empty house says nobody is here to
notice it, not that the message became a life-safety alert. A target whose
alerts matter sets its default priority to `high` and gets a **critical** push
out of an empty house — which, with the critical payload below, is a phone
that rings through Do Not Disturb. A target of shopping lists gets a `normal`
message and nothing else.

Anything that is not the literal `home` — a named zone, `not_home`, `unknown`,
a person the state machine has never heard of — counts as "not home". A target
with no person in its audience escalates nothing, and the presence rule is
never overridden: a `home_only` target with nobody home still drops everybody
with the reason `presence`. That last point is the thing to check before
turning escalation on: it only changes anything on a target whose presence
rule lets an absent person be notified — `always` or `away_only`. Under
`home_only` an empty house means nobody is notified at all, so there is no
priority left to raise. `notify_switchboard.explain` reports the rule under
its `escalated` key, and reports the raised priority.

### Observer mode, or `notifiers:`

Two ways to wire a target to an alert, and the first is the one to start with.

**Observer mode** — tick it on the target, and the router watches the alert
itself: it routes on `idle → on`, sends the back-to-normal message when the
alert returns to `idle`, and stops on `on → off`. The `alert:` block then
needs no `notifiers:` at all, and the target's own message template and
default title decide what is said:

```yaml
alert:
  water_leak:
    name: Water leak
    entity_id: binary_sensor.leak_kitchen
    state: "on"
    repeat: [5, 15, 60]
    can_acknowledge: true
```

**Or drive the router from the alert** — leave observer mode off and name the
target under `notifiers:`, so the alert decides when to send and repeats on
its own schedule:

```yaml
alert:
  water_leak:
    name: Water leak
    entity_id: binary_sensor.leak_kitchen
    state: "on"
    repeat: [5, 15, 60]
    can_acknowledge: true
    notifiers:
      - switchboard_leak
```

## Adding a speaker as an output

A speaker is just another `notify.*` service — core already ships one that
speaks, the legacy `platform: tts` notify platform
(`homeassistant/components/tts/notify.py`). Five lines make it a target,
whether it is one person's output or a bare target's:

```yaml
notify:
  - platform: tts
    name: kitchen_speaker      # -> notify.kitchen_speaker
    entity_id: tts.home_assistant_cloud
    media_player: media_player.kitchen
```

Aim it at a Music Assistant player to get pause/announce/resume; a raw Cast
player is interrupted. Pick `notify.kitchen_speaker` in a person's **Notify
services** the same way you would a phone — or put it **straight in a target's
audience**, which is what it is for. Assist Satellite Notifier (a sibling of
this suite) is the one adapter still worth a separate integration —
`assist_satellite` has no `notify` platform of its own.

An audience entry that is a `notify.*` service name is a **bare output**: a
thing that can be told something, with no presence, no phone and no bedtime.
It has no presence rule, no silence, no snooze, no wake time, no summary and
no time to live — it is delivered now or it is not delivered — and it gets no
Acknowledge or Snooze button and no key the router invented, only what you
sent merged with the target's default data. It counts as one delivery like
anybody else, it takes part in the target's episodes (so "back to normal"
reaches the speaker that heard the alarm and no other), and one that does not
exist fails exactly the way a missing phone does. Until 0.7.0 it had to be
modelled as a fake `person.*` that never moved.

An episode can tell a bare output that it is over; it cannot **tidy** it. The
clear at the end of an episode works on the identifiers the router adds — the
`tag` a Companion app matches, the `notification_id`
`persistent_notification` is created with — and a bare output receives none of
them. A bare `notify.persistent_notification` therefore stays on the dashboard
until somebody dismisses it, next to the back-to-normal message saying the
leak is fixed. Put `persistent_notification` in a **person's** outputs instead
whenever you want it cleared.

### Outputs that are `notify` entities

Some integrations — Alexa Devices, Telegram, core's own notify groups — ship
`notify.*` **entities** rather than legacy services. From 0.7.0 an output that
names one is delivered through `notify.send_message`. A registered legacy
service of the same name always wins, so nothing that works today changes.

The pickers do not offer them: **Notify services** and a target's **Audience**
both list the registered `notify.*` services, so to use an entity you type its
entity id into the field — both fields accept a typed value — and the router
resolves it when the message goes out.

Home Assistant's entity action carries **`message` and `title` and nothing
else**, so a target's default data, your own `data`, the default tag, the
buttons and the critical payload never reach an entity output. That is core's
shape, not a shortcut — it is the same limitation this integration documents
for its own `notify.switchboard` entity. An entity that is missing or
`unavailable` is treated as a missing output, with the same repair.

## The night

A person with a silence entity has a queue, and that queue behaves like
something a human wakes up to.

A **wake time** is optional. With one, the queue is flushed then. Without one,
the queue is flushed when the silence itself says it ends — a `schedule.*`
publishes that instant, an `input_boolean` does not — and a message silenced by
something that never says when it stops is dropped with the reason `silenced`,
as it always was.

- **A silence can be selective.** A silence entity that is `on` and publishes a
  `min_priority` state attribute holds only the calls **below** that priority;
  anything at or above it goes through. `binary_sensor.<person>_silenced`
  still reads `on` throughout: it answers "is a silence running?", not "would
  this particular message get through?", and a floor changes only the second —
  which is `notify_switchboard.explain`'s question, message by message. A core
  `schedule` is the documented way to publish one, with no automation of your
  own:

  ```yaml
  schedule:
    night:
      monday:
        - from: "22:30:00"
          to: "07:00:00"
          data:
            min_priority: high
  ```

  List `schedule.night` as that person's silence entity and the night holds the
  shopping list and lets the leak through. The router reads the attribute, not
  the domain, so a template `binary_sensor` that publishes it works the same
  way. A value that is not one of the four priorities is ignored and the entity
  holds everything: a floor fails towards quiet. When several silences are on,
  the strictest decides, and one without a floor holds everything.
- **Nothing waits for ever.** Each priority has a time to live, counted from
  the moment the message was queued: 2 h for `info`, 12 h for `normal`, none
  for `high`. A message whose time has run out is dropped with the reason
  `expired` instead of announcing at 07:00 that the front door was open at
  23:31. Those three numbers are today's defaults, not a promise: a minor
  version may pick others. The **Time to live** step in the options changes
  the policy for good and always shows the values in force;
  `data: {ttl_minutes: 30}` changes it for one call, and `ttl_minutes: 0`
  means "keep this one whatever the policy says". A `critical` message is
  never held back, so it never expires.
- **One notification, not eleven.** More than one message surviving for the
  same person becomes a single notification per output: a title carrying the
  count, one line per message, and messages sharing a `tag` collapsed to the
  most recent one. A digest carries no Acknowledge or Snooze button, because
  it could only act on an arbitrary one of the messages it lists. Turn
  **Summarise the night** off on a person to get them one by one instead.
- **The decision is taken again, not remembered.** At the flush the router
  re-runs the whole decision — audience, presence, snooze, silence — with the
  message's original priority. Somebody who left the house under a `home_only`
  target gets `presence`, somebody who snoozed it at 02:00 gets `snoozed`,
  and nothing is delivered blindly on the strength of a decision taken hours
  earlier. Still silenced is the one outcome that keeps the message queued.
- **The night ends when it ends.** When the last of a person's silence
  entities turns `off` and no `notify_switchboard.silence` is running, their
  queue goes out there and then. A wake time, when there is one, stays the
  upper bound: nothing waits longer than it used to.

## Closing the loop

A leak that was fixed at 03:20 used to leave its 03:00 notification on every
phone for ever, and to tell "back to normal" to the two people who slept
through the whole thing.

For every target tied to an `alert.*`, the router remembers one **episode**:
from the alert's `idle → on` to its return to `idle`, who was actually told,
which notify services answered, and under which tag. It survives a restart.

- The **back-to-normal message reaches only those people**; everybody else in
  the audience is dropped with the reason `not_notified`. That applies to
  observer mode's own message and to any call you mark yourself with
  `data: {switchboard_done: true}` — the documented key for an `alert:` block
  or a blueprint that sends its own.
- When an observer target's episode ends, the notifications it sent are
  **cleared**: a `clear_notification` push to each Companion service the
  episode reached, and a `persistent_notification.dismiss` for the matching
  id. The back-to-normal message keeps a tag of its own
  (`switchboard-<slug>-done`) so it survives that clear; turn **Clear the
  back-to-normal message** on for the target if you would rather it tidied
  itself away too.
- A clear is not a message: it is not counted, it fires no event, and no
  routing rule applies to it.
- A **summary counts as having told you**: if a night's digest carried a line
  about the leak, you get the back-to-normal message and the digest is cleared
  with the episode. One digest carries one tag for all its lines, so the first
  of those alerts to end clears the whole digest — the price of one
  notification instead of eleven.

## Services

Everything the notification buttons do is also a service, so a card, a script
or an automation can do it too. Each one refuses an invalid call with an
explicit error rather than doing nothing quietly.

| Service | Fields | What it does |
|---|---|---|
| `notify_switchboard.acknowledge` | `target` | Turns off the target's alert, if it has one and allows it. |
| `notify_switchboard.snooze` | `target`, `minutes`, `person` (optional) | Stops that target for a while. `minutes` has to be one of the durations the target offers; without `person`, the whole audience is snoozed. |
| `notify_switchboard.unsnooze` | `target`, `person` (optional) | Lifts a snooze immediately. |
| `notify_switchboard.silence` | `person`, `minutes` | Silences somebody for a while, for every target, without touching their own silence entities. Only `critical` still gets through. |
| `notify_switchboard.unsilence` | `person` | Lifts that silence immediately. |
| `notify_switchboard.explain` | `target`, `priority` (optional), `person` (optional) | Answers what would happen to a message sent right now, per person, and changes nothing at all. Call it with **Return response**. |

A silence set this way shows up in `binary_sensor.<person>_silenced` (with an
`until` attribute), survives a restart, and lifts on its own.

## Why didn't I get it?

`notify_switchboard.explain` is the answer to the first argument this router
will ever lose. It runs the real decision over the real world and reports it,
per person, without sending anything, moving a counter or firing an event:

```yaml
target: leak
priority: critical             # the priority a message would actually go out at
escalated: nobody_home         # or null: what raised it, when anything did
outputs: [notify.kitchen_speaker]   # the target's bare outputs, in audience order
persons:
  person.alice:
    decision: dropped          # routed | deferred | dropped
    until: null                # ISO instant, deferred only
    reason: silenced           # a drop reason, dropped only
    detail: "person.alice is silenced by input_boolean.quiet_hours. Only a critical message would get through."
    outputs: []                # the notify.* services it would reach
    missing_outputs: []        # configured outputs that are not services
```

`detail` is translated, and it names the deciding object — *which* switch is
on, *when* the snooze lifts, the presence rule against the person's current
state, and the **floor** a silence carries when it has one — rather than
restating the reason. `priority` is what a message sent right now would carry,
escalation included; `escalated` is `null` when nothing raised it, including
when the rule's condition held but the message was already `critical`.

Alongside it, three repairs turn silent, permanent failures into something the
Repairs page can show: a person in an audience with no notify service at all, a
target tied to an `alert.*` that does not exist (checked a minute after
startup, never during it), and an output that keeps failing.

## Message text

Three optional fields per target, all empty by default and all in **Advanced
settings of a target**:

- **Message template** and **Back-to-normal template** — used in observer mode
  instead of the target's bare name. The watched alert's state is available to
  the template as `alert`, so a target can write
  `Water on the floor, {{ alert.attributes.level }}`.
- **Default title** — the title used when the caller gives none, and for every
  message observer mode sends.

## `data` keys a caller can set

| Key | Meaning |
|---|---|
| `priority` | `info` / `normal` / `high` / `critical`; overrides the target's default. Only `critical` bypasses silence and snoozes. **From 0.7.0 it is not forwarded to `mobile_app_*` outputs**: it is the router's own input key, and Android's Companion app reads `data.priority` and understands only `high`. Every other output still receives it. |
| `source_entity` | The entity the message is about. Diagnostics and voice deny-lists read it. |
| `tag` | De-duplicates a deferral and names the notification. Defaults to `switchboard-<slug>`, and that default is only sent to Companion and `persistent_notification` outputs; a `tag` **you** set is passed to every output like any other key. |
| `ttl_minutes` | How long this message is still worth delivering once it has been held back. `0` means never expires. |
| `switchboard_done` | Marks this call as the "back to normal" of the target's current episode, so it only reaches the people that episode reached. |
| anything else | Merged over the target's default data, caller wins, and passed to the outputs untouched. |

The router never adds a key an output cannot read: apart from the defaults
above, an output receives exactly what you sent merged with the target's
default data. That matters for adapters that validate their `data` and refuse anything
unknown — the AirPlay and Assist Satellite notifiers of this suite do.

### Critical notifications

`critical` has meant one thing to a phone since 0.1.0: nothing. It bypassed a
silence *inside the router* and then arrived as an ordinary push, which a phone
in Do Not Disturb does not play.

From 0.7.0, a message whose **effective** priority is `critical` — after the
escalation above — carries, on `mobile_app_*` outputs only, the keys the
[Companion documentation](https://companion.home-assistant.io/docs/notifications/critical-notifications/)
gives for a critical notification:

| Registration OS | Keys added under `data` |
|---|---|
| iOS / iPadOS / watchOS | `push: {sound: {name: default, critical: 1, volume: 1.0}}` |
| Android | `ttl: 0`, `priority: high`, `channel: alarm_stream` |
| anything else, or no matching registration | both sets |

The OS is read from the Companion registration behind that service, so nothing
has to be configured per phone. Both sets are sent when the router cannot tell:
the keys of one OS are inert on the other, and a phone that rings beats a phone
that is quiet because a registration predates the field. A key **you** set is
never overwritten, and `push` counts as a single key — write
`push: {interruption-level: critical}` and the router adds nothing under it.

Turn it off in one place, under **Default target** in the options menu
("Make critical notifications critical"). On iOS the phone must also have
granted the Companion app the critical-alerts permission, which no integration
can do for you.

## The routing table, for cards

`sensor.switchboard_routing_table` publishes what the table *is*, so a card
stops re-declaring it in its own YAML and going stale on the first options
edit. Its state is the number of targets, and it carries exactly two
attributes:

| Attribute | One entry per | Keys |
|---|---|---|
| `targets` | target, in table order | `slug`, `name`, `alert_entity`, `snooze_minutes`, `allow_acknowledge`, `audience` |
| `persons` | configured person, in options order | `entity_id`, `wake_time`, `summary` |

`alert_entity` and `wake_time` are `null` rather than absent when there is
none, so every row has the same shape, and `audience` is reported verbatim,
bare outputs included. Both lists are **closed**: a target's `default_data` is
never exposed — it is where an API key or a webhook path ends up, and a state
attribute is readable by anybody who can read the state machine — and neither
is a person's list of notify services. If you need to know what *would*
happen, that is `notify_switchboard.explain`.

Neither attribute is written to the database: they are configuration, and they
change only when you edit the options.

## Translations

The interface ships in English, French and Spanish — including the entity
names: `sensor.switchboard_routed_today` reads as "Routed today", "Acheminées
aujourd'hui" or "Encaminadas hoy" depending on the instance language, while
the **entity id itself never changes**, so an `alert:`, an automation or a card
written against the documented names keeps working in any language.

English and French are
written by the maintainer; **the Spanish translation
(`custom_components/notify_switchboard/translations/es.json`) is machine
translated and has not been reviewed by a native speaker** — corrections and
new languages are very welcome, one pull request per language.

## Removal

Settings → Devices & services → Notify Switchboard → delete. This removes
the `notify.switchboard` service and the entity; it does not touch the
`notify.*` services it forwarded to.

## Roadmap

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the sprint table and the
router's own roadmap.

**0.7.0 adds again**, from a list the maintainer shortened after the product
review: one step louder when nobody is home, a priority floor a `schedule` can
carry, `sensor.switchboard_routing_table`, who acknowledged in the
`acknowledged` event, audience entries and outputs that are not people, and a
critical push that a phone actually plays. It has one **breaking** change:
`data.priority` no longer reaches a `mobile_app_*` output — see the `data` keys
table above. The router still owns no timer and no counter of its own: every
rule is evaluated when a message arrives, from entities that already exist.
Deferred, each with the native answer that stands in for it today: escalation
after N minutes (a template `binary_sensor`'s `delay_on`, written up in
[`docs/blueprints.md`](docs/blueprints.md)), a delivery cap, a per-target
authentication override, a per-person priority floor, an acknowledgement
history sensor, labels on a target and a `places` object.

0.6.0 before it was a consolidation release: it added no routing rule, no
entity, no service and no drop reason. It shortened the first form somebody
meets from fifteen fields to five, removed a field nothing ever read
(`class`), gave an absent wake time a documented meaning, settled one word per
concept, and made these documents agree with the code. What went before is
still all here:
the routing table, the per-person decision, acknowledge and snooze, night
deferral, observer mode, the diagnostic entities, the six services above, a
temporary per-person silence, the per-target message texts, translated entity
names, a parallel fan-out bounded by a per-output timeout, `person.user_id` as
the canonical link for Companion callbacks, actions that exist whether or not
the config entry is loaded, discovered Companion outputs and Focus sensors, a
managed `default` target, `notify_switchboard.explain`, two consistency
repairs, a test message from the options menu, a time to live on a deferral,
one wake-time summary, a full re-decision at the flush, an early flush when
the silence really ends, episodes and cleared notifications.

Later, and unscheduled, each needing an ADR of its own: the deferred list
above, plus intents.

## Glossary

One word per concept. The other documents link here rather than redefining
anything.

| Word | What it means here |
|---|---|
| **Target** | One entry of the routing table: an identity, an alert it is about, an audience, and how it is driven. It becomes `notify.switchboard_<slug>`. Not to be confused with the notify `target` list — the `target:` field of a `notify.switchboard` call, which names one or more of these. |
| **Person** | A `person.*` this router knows, with the notify services that reach them and the entities that mean they are silent. |
| **Output** | A `notify.*` service — or, from 0.7.0, a `notify.*` entity — a person's messages are handed to. The router never delivers anything itself. |
| **Bare output** | An audience entry that is a `notify.*` service name rather than a person: a speaker, a wall tablet. It has no presence, no silence, no snooze, no deferral and no buttons — it is told now or not at all — and it takes part in the target's episodes like anybody else. |
| **Audience** | The people a target is for, and its bare outputs. Anybody else is not considered at all — not notified, and not counted as dropped. |
| **Presence rule** | Whether a person's `person.*` state has to be `home`, has to be away, or does not matter. The only thing here still called a rule. |
| **Silence** | A person is silent while one of their own silence entities is `on` (a `schedule`, an `input_boolean`, an iPhone Focus sensor) or while a temporary `notify_switchboard.silence` is running. Only `priority: critical` gets through. |
| **Priority floor** | A `min_priority` state attribute on a silence entity that is `on`: the silence then holds only the calls **below** that priority. A `schedule`'s per-block `data:` is the documented way to publish one — a night that holds the shopping list and lets the leak through. An unreadable value is ignored, and the silence holds everything. |
| **Escalation** | `escalate_when_nobody_home` on a target: one step louder for one message, when no person of the audience is `home`. It never overrides the presence rule. |
| **Snooze** | One target stopped for a chosen number of minutes, from a notification button or from `notify_switchboard.snooze`. The button snoozes it for the person who pressed it; the service called without a `person` snoozes it for the target's whole audience. |
| **Wake time** | The hour a person's night silence is treated as over. Optional: without one, a queue is flushed when the silence itself says it ends. |
| **Quiet hours** | *Not a concept of this integration.* It is what a silence entity and a wake time add up to, and it is the phrase most people arrive with. |
| **Deferral** | A message held back rather than dropped, because the person is silent by one of their own silence entities *and* their night has a known end — their wake time, or the end that silence publishes. A temporary `notify_switchboard.silence` alone is not a night: such a message is dropped, not deferred. It is re-decided in full when it is flushed, and it expires. |
| **Summary** | The single notification a person receives when more than one deferral survives the flush, instead of one per message. On by default. |
| **Episode** | What the router remembers between an alert's `idle → on` and its return to `idle`: who was actually told, on which outputs, under which tags. It is what makes a back-to-normal message reach only the people who heard the alarm. |
| **Observer mode** | The router watching a target's alert itself rather than waiting to be called as one of its `notifiers:`. The recommended way to wire a target. |

### Words used in the interface

From 0.7.1 the screens are written for somebody who does not read code, so the
words on them are not always the contract's. This is the mapping; the right
column is what the rest of this documentation, the contract and the stored
options call the same thing.

| On screen | In this documentation |
|---|---|
| Where to tell them / their devices | `outputs` |
| When not to disturb them | `silence_entities` |
| Who to tell | `audience` |
| Short identifier | `slug` |
| Alert watched | `alert_entity` |
| Watch the alert directly | `observer_mode` |
| Importance (not very important / normal / important / critical) | `priority` (`info` / `normal` / `high` / `critical`) |
| Tell people depending on presence | `presence_rule` |
| Put on hold / "later" buttons | snooze |
| Set aside | deferred |
| How long a message set aside stays useful | `ttl_minutes` |
| Raise the importance when the house is empty | `escalate_when_nobody_home` |
| Who gets what (the sensor) | `sensor.switchboard_routing_table` |

Entity ids, service names and option keys are unchanged: only what is written
on the screens is.

## Documentation

- [Contract](docs/contract.md) — the frozen public names and behaviour
  (`notify.switchboard`, `notify.switchboard_<target>`, `data.priority`,
  `data.source_entity`, observer mode) that this project commits to across
  minor versions.
- [Architecture](docs/ARCHITECTURE.md) — the proxy model, input/output
  contracts, the decisions Sprints 1 and 2 took where the contract left room
  (how the two silence sources combine, what a target's template can read),
  and the sprint roadmap.
- [Known issues](docs/known-issues.md) — what was consciously left out, and
  why.
- [Accepted deviations](docs/accepted-deviations.md) — the three places where
  this integration knowingly bends one of its own principles, and what each one
  bought.
- [Quickstart](docs/quickstart.md) — route your first alert in about ten
  minutes.
- [Migrating an existing installation](docs/migration-guide.md) — where to
  start when you already have inline `notify.mobile_app_*` calls and a handful
  of `alert:` blocks.
- [Blueprints](docs/blueprints.md) — the three importable automation
  blueprints shipped in `blueprints/automation/notify_switchboard/`.

## License

[MIT](LICENSE) © 2026 the maintainer

## How this project is built

This integration is written almost entirely by AI models, under the direction
and the responsibility of a single human maintainer, who owns every product
decision and tests each release on real hardware.
[`docs/how-this-is-built.md`](docs/how-this-is-built.md) sets out who does
what, what the specification-before-code discipline is meant to catch, and
what it does not catch — read it before deciding how much to trust this code.
