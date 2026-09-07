# Notify Switchboard

[![MIT License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=amiel-35&repository=notify-switchboard&category=integration)
[![Open your Home Assistant instance and start setting up a new integration.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=notify_switchboard)

A [Home Assistant](https://www.home-assistant.io/) custom integration that
acts as a pure `notify` **proxy**. It never delivers a notification itself:
it only forwards to `notify.*` services you already have configured
(Companion app, persistent notification, voice adapters, and so on).

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

- `notify.switchboard`, and one `notify.switchboard_<slug>` per row of the
  routing table, so the core `alert` integration can name a row under
  `notifiers:`;
- a `NotifyEntity`, documented as degraded: `notify.send_message` carries only
  `message` and `title`, so it routes to the default row with priority
  `normal`.

A call carries `message`, `title` and `data` (`priority`, `source_entity`,
`tag`, and anything else, merged over the row's default data). For every
person in the row's audience the router checks, in order: the presence rule
against `person.*`, the person's silence entities, an active snooze — with
`priority: critical` overriding the last two — and then calls each of that
person's `notify.*` outputs.

On a Companion output it adds an **Acknowledge** button (when the row is tied
to an `alert.*` and allows it) and one **Snooze** button per configured
duration. Acknowledging turns that alert off, and only an alert listed in the
routing table. A message silenced during someone's night is not lost: it is
queued and delivered at their wake time — as **one** summary rather than a
burst, and only if it is still worth delivering (see "The night" below).

Every outgoing message also carries a name of its own: `data.tag` defaults to
`switchboard-<slug>`, so a repeat updates the notification instead of stacking
a second one, and on the `persistent_notification` output the matching
`data.notification_id` is added too. Your own `tag` always wins.

## Install

The **My Home Assistant** button at the top of this page opens this repository
in [HACS](https://hacs.xyz/) on your own instance. By hand: HACS →
Integrations → menu → Custom repositories → add
`https://github.com/amiel-35/notify-switchboard`, category "Integration", then
install "Notify Switchboard" and restart Home Assistant.

## Configuration

The second button at the top of this page starts the config flow. Or:
Settings → Devices & services → Add integration → "Notify Switchboard".
Setup takes no input, and since 0.4.0 **one form is enough** to get a working
`notify.switchboard`:

1. **Add a person** — pick a `person.*`. The notify services of the phones
   registered to that person's Home Assistant user are listed first, marked as
   theirs and already selected, and their iPhone Focus sensors are proposed as
   silence entities. Nothing is guessed from a name: the link is the `user_id`
   a Companion registration stores and the one a `person.*` publishes. You can
   still type a service that does not exist yet.
2. That is it, on a fresh install: the first person added to an empty routing
   table also creates a `default` row and points the default target at it, so
   `notify.switchboard` reaches a real phone straight away. While that row is
   managed, a second person joins its audience automatically; editing it hands
   it to you for good.
3. **Add a target** — one row per alert, when you want more than "everybody":
   a slug (it becomes `notify.switchboard_<slug>`), a name, a default
   priority, the `alert.*` it is tied to, the audience, a presence rule, and
   the snooze durations to offer. Saving it shows the `alert:` block to paste,
   `notifiers:` included.
4. **Test a person / Test a target** — sends one real message through the
   ordinary routing path, tagged `switchboard-test`, and shows what the router
   decided for each person.

Then point an alert at it:

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

## The night

A person with a **wake time** and a silence entity has a queue. Since 0.5.0
that queue behaves like something a human wakes up to.

- **Nothing waits for ever.** Each priority has a time to live, counted from
  the moment the message was queued: 2 h for `info`, 12 h for `normal`, none
  for `high`. A message whose time has run out is dropped with the reason
  `expired` instead of announcing at 07:00 that the front door was open at
  23:31. The **Time to live** step in the options changes the policy;
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
  row gets `presence`, somebody who snoozed the row at 02:00 gets `snoozed`,
  and nothing is delivered blindly on the strength of a decision taken hours
  earlier. Still silenced is the one outcome that keeps the message queued.
- **The night ends when it ends.** When the last of a person's silence
  entities turns `off` and no `notify_switchboard.silence` is running, their
  queue goes out there and then. The wake time stays the upper bound: nothing
  waits longer than it used to.

## Closing the loop

A leak that was fixed at 03:20 used to leave its 03:00 notification on every
phone for ever, and to tell "back to normal" to the two people who slept
through the whole thing.

For every row tied to an `alert.*`, the router now remembers one **episode**:
from the alert's `idle → on` to its return to `idle`, who was actually told,
which notify services answered, and under which tag. It survives a restart.

- The **back-to-normal message reaches only those people**; everybody else in
  the audience is dropped with the reason `not_notified`. That applies to
  observer mode's own message and to any call you mark yourself with
  `data: {switchboard_done: true}` — the documented key for an `alert:` block
  or a blueprint that sends its own.
- When an observer row's episode ends, the notifications it sent are
  **cleared**: a `clear_notification` push to each Companion service the
  episode reached, and a `persistent_notification.dismiss` for the matching
  id. The back-to-normal message keeps a tag of its own
  (`switchboard-<slug>-done`) so it survives that clear; turn **Clear the
  back-to-normal message** on for the row if you would rather it tidied itself
  away too.
- A clear is not a message: it is not counted, it fires no event, and no
  routing rule applies to it.

## Services

Everything the notification buttons do is also a service, so a card, a script
or an automation can do it too. Each one refuses an invalid call with an
explicit error rather than doing nothing quietly.

| Service | Fields | What it does |
|---|---|---|
| `notify_switchboard.acknowledge` | `target` | Turns off the row's alert, if the row has one and allows it. |
| `notify_switchboard.snooze` | `target`, `minutes`, `person` (optional) | Stops that target for a while. `minutes` has to be one of the durations the row offers; without `person`, the whole audience is snoozed. |
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
row tied to an `alert.*` that does not exist (checked a minute after startup,
never during it), and an output that keeps failing.

## Message text

Three optional fields per row, all empty by default:

- **Message template** and **Back-to-normal template** — used in observer mode
  instead of the row's bare name. The watched alert's state is available to
  the template as `alert`, so a row can write
  `Water on the floor, {{ alert.attributes.level }}`.
- **Default title** — the title used when the caller gives none, and for every
  message observer mode sends.

## `data` keys a caller can set

| Key | Meaning |
|---|---|
| `priority` | `info` / `normal` / `high` / `critical`; overrides the row's default. Only `critical` bypasses silence and snoozes. |
| `source_entity` | The entity the message is about. Diagnostics and voice deny-lists read it. |
| `tag` | De-duplicates a deferral and names the notification. Defaults to `switchboard-<slug>`. |
| `ttl_minutes` | How long this message is still worth delivering once it has been held back. `0` means never expires. |
| `switchboard_done` | Marks this call as the "back to normal" of the row's current episode, so it only reaches the people that episode reached. |
| anything else | Merged over the row's default data, caller wins, and passed to the outputs untouched. |

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

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the sprint table and
the router's own roadmap. This release covers everything up to router S4: the
routing table, the per-person decision, acknowledge and snooze, night
deferral, observer mode, the diagnostic entities, the six services above, a
temporary per-person silence, the per-row message texts, translated entity
names, a parallel fan-out bounded by a per-output timeout, `person.user_id` as
the canonical link for Companion callbacks, actions that exist whether or not
the config entry is loaded, discovered Companion outputs and Focus sensors, a
managed `default` row, `notify_switchboard.explain`, two consistency repairs, a
test message from the options menu, and — since 0.5.0 — a time to live on a
deferral, one wake-time summary, a full re-decision at the flush, an early
flush when the silence really ends, episodes and cleared notifications.

Next: escalation (S6) and places (S7).

## Documentation

- [Contract](docs/contract.md) — the frozen public names and behaviour
  (`notify.switchboard`, `notify.switchboard_<target>`, `data.priority`,
  `data.source_entity`, observer mode) that this project commits to across
  minor versions.
- [Architecture](docs/ARCHITECTURE.md) — the proxy model, input/output
  contracts, the decisions Sprints 1 and 2 took where the contract left room
  (how the two silence sources combine, what a row template can read), and the
  sprint roadmap.
- [Known issues](docs/known-issues.md) — what was consciously left out, and
  why.
- [Quickstart](docs/quickstart.md) — route your first alert in ten minutes.
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
