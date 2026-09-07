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

Every word in bold on this page is defined once, in the [Glossary](#glossary)
at the bottom.

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
Setup takes no input, and **two forms of two and five fields** are enough to
get a working `notify.switchboard`:

1. **Add a person** — pick a `person.*`, then answer two things: which notify
   services reach them, and which entities mean they are silent. The notify
   services of the phones registered to that person's Home Assistant user are
   listed first, marked as theirs and already selected, and their iPhone Focus
   sensors are proposed as silence entities. Nothing is guessed from a name:
   the link is the `user_id` a Companion registration stores and the one a
   `person.*` publishes. You can still type a service that does not exist yet.
2. That is it, on a fresh install: the first person added to an empty routing
   table also creates a `default` **target** and points the default target at
   it, so `notify.switchboard` reaches a real phone straight away. While that
   target is managed, a second person joins its audience automatically;
   editing it hands it to you for good.
3. **Add a target** — one per alert, when you want more than "everybody". Five
   fields: a slug (it becomes `notify.switchboard_<slug>`), a name, the
   `alert.*` it is about, the audience, and whether the router watches that
   alert itself. Saving it shows the `alert:` block to paste.
4. **Test a person / Test a target** — sends one real message through the
   ordinary routing path, tagged `switchboard-test`, and shows what the router
   decided for each person.

Priority, presence rule, buttons, snooze durations, templates and default data
all have a default that suits almost everybody, and live behind **Advanced
settings of a target** — offered straight after saving, and in the options menu
for ever after. The same split applies to a person: **Advanced settings of a
person** holds their wake time and their night summary.

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
services** the same way you would a phone, or give it to a person whose whole
job is that speaker. Assist Satellite Notifier (a sibling of this suite) is the one
adapter still worth a separate integration — `assist_satellite` has no
`notify` platform of its own.

## The night

A person with a silence entity has a queue, and that queue behaves like
something a human wakes up to.

A **wake time** is optional. With one, the queue is flushed then. Without one,
the queue is flushed when the silence itself says it ends — a `schedule.*`
publishes that instant, an `input_boolean` does not — and a message silenced by
something that never says when it stops is dropped with the reason `silenced`,
as it always was.

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
state — rather than restating the reason.

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
| `priority` | `info` / `normal` / `high` / `critical`; overrides the target's default. Only `critical` bypasses silence and snoozes. |
| `source_entity` | The entity the message is about. Diagnostics and voice deny-lists read it. |
| `tag` | De-duplicates a deferral and names the notification. Defaults to `switchboard-<slug>`, and that default is only sent to Companion and `persistent_notification` outputs; a `tag` **you** set is passed to every output like any other key. |
| `ttl_minutes` | How long this message is still worth delivering once it has been held back. `0` means never expires. |
| `switchboard_done` | Marks this call as the "back to normal" of the target's current episode, so it only reaches the people that episode reached. |
| anything else | Merged over the target's default data, caller wins, and passed to the outputs untouched. |

The router never adds a key an output cannot read: apart from the defaults
above, an output receives exactly what you sent merged with the target's
default data. That matters for adapters that validate their `data` and refuse anything
unknown — the AirPlay and Assist Satellite notifiers of this suite do.

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

**0.6.0 is a consolidation release**: it adds no routing rule, no entity, no
service and no drop reason. It shortens the first form somebody meets from
fifteen fields to five, removes a field nothing ever read (`class`), gives an
absent wake time a documented meaning, settles one word per concept, and makes
these documents agree with the code. What went before it is still all here:
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

Next, in 0.7.0: escalation and places, reduced in scope. Later, and
unscheduled: labels on a target, a per-target authentication override, and
intents.

## Glossary

One word per concept. The other documents link here rather than redefining
anything.

| Word | What it means here |
|---|---|
| **Target** | One entry of the routing table: an identity, an alert it is about, an audience, and how it is driven. It becomes `notify.switchboard_<slug>`. Not to be confused with the notify `target` list — the `target:` field of a `notify.switchboard` call, which names one or more of these. |
| **Person** | A `person.*` this router knows, with the notify services that reach them and the entities that mean they are silent. |
| **Output** | A `notify.*` service a person's messages are handed to. The router never delivers anything itself. |
| **Audience** | The people a target is for. Anybody else is not considered at all — not notified, and not counted as dropped. |
| **Presence rule** | Whether a person's `person.*` state has to be `home`, has to be away, or does not matter. The only thing here still called a rule. |
| **Silence** | A person is silent while one of their own silence entities is `on` (a `schedule`, an `input_boolean`, an iPhone Focus sensor) or while a temporary `notify_switchboard.silence` is running. Only `priority: critical` gets through. |
| **Snooze** | One person stopping one target for a chosen number of minutes, from a notification button or from `notify_switchboard.snooze`. |
| **Wake time** | The hour a person's night silence is treated as over. Optional: without one, a queue is flushed when the silence itself says it ends. |
| **Quiet hours** | *Not a concept of this integration.* It is what a silence entity and a wake time add up to, and it is the phrase most people arrive with. |
| **Deferral** | A message held back rather than dropped, because the person is silent and their night has a known end. It is re-decided in full when it is flushed, and it expires. |
| **Summary** | The single notification a person receives when more than one deferral survives the flush, instead of one per message. On by default. |
| **Episode** | What the router remembers between an alert's `idle → on` and its return to `idle`: who was actually told, on which outputs, under which tags. It is what makes a back-to-normal message reach only the people who heard the alarm. |
| **Observer mode** | The router watching a target's alert itself rather than waiting to be called as one of its `notifiers:`. The recommended way to wire a target. |

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
- [Quickstart](docs/quickstart.md) — route your first alert in ten minutes.
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
