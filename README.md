# Notify Switchboard

[![MIT License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=amiel-35&repository=notify-switchboard&category=integration)
[![Open your Home Assistant instance and start setting up a new integration.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=notify_switchboard)

A [Home Assistant](https://www.home-assistant.io/) custom integration that
acts as a pure `notify` **proxy**: it never delivers a notification itself, it
only forwards to `notify.*` services you already have configured (Companion
app, persistent notification, a speaker via core's own
`notify: platform: tts` — see [Adding a speaker](#adding-a-speaker-as-an-output)).
It sits in front of `notify.*` and decides who should be told, and when, based
on Home Assistant's own `alert`, `person` and `schedule` — see
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the full contract and
rationale.

## The proxy model

Notify Switchboard exposes `notify.switchboard`, and one
`notify.switchboard_<slug>` per **target** of the routing table (so `alert`
can name a target under `notifiers:`), plus a degraded `NotifyEntity` — only
`message` and `title`, routed to the default target at priority `normal`.

The vocabulary this page uses is defined once, in the [Glossary](#glossary) at
the bottom.

A call carries `message`, `title` and `data` (`priority`, `source_entity`,
`tag`, and anything else, merged over the target's default data). For every
person in the target's audience the router checks, in order: presence,
silence, an active snooze — `priority: critical` overrides the last two —
then calls each of that person's `notify.*` outputs. On a Companion output it
also adds an **Acknowledge** button (when the target allows it) and one
**Snooze** button per configured duration. A message silenced during
someone's night is queued and delivered when that night ends, as one summary
rather than a burst (see [The night](#the-night)).

## Install and configure

The **My Home Assistant** button at the top opens this repository in
[HACS](https://hacs.xyz/); by hand, add
`https://github.com/amiel-35/notify-switchboard` as a custom repository. The
second button starts the config flow; then click **Configure**. Two short
forms are enough for a working `notify.switchboard`: a person's screen asks
**two things** — where to tell them and when not to disturb them — plus two
optional boxes (create a night schedule, set up their night now); an alert's
screen asks **four** — its name, what sets it off (optional), who to tell, and
whether to tell them as soon as it goes off. Adding the first person also
creates a `default` target with everybody in it, and a speaker can join a
target's audience directly (see [Bare outputs](#bare-outputs)). On screen, a
target is called an **alert**; its **automation name**
(`notify.switchboard_<slug>`) is made from its name once and never changes.
"Tell people as soon as it goes off" (observer mode) is on by default, so a
new alert tied to a Home Assistant alert needs no YAML and no restart — but
it sends one message when that alert goes off and one when it ends, **not
its reminders** (see [Wiring a target to an alert](#wiring-a-target-to-an-alert)).
One tied to nothing is set off by an automation: the last screen links to a
blueprint shipped with the integration, already in your blueprints, so the
automation is one click and two fields away (see
[`docs/blueprints.md`](docs/blueprints.md)). Priority, presence rule,
buttons, snooze durations, templates and default data all have a sane default
and are opened by a checkbox on the **Change an alert** screen. The menu has three entries for people, three for
alerts, and **Settings**. Full walkthrough, including the two test messages
under **Settings**, in [`docs/quickstart.md`](docs/quickstart.md).

## When the house is empty

A target can carry **`escalate_when_nobody_home`** (**Change an alert** → tick
*What happens when the house is empty*, off by default). When on, and no person of the target's audience
is `home`, that message routes **one step louder** — `info→normal`,
`normal→high`, `high→critical`, `critical` unchanged — for that message only.
The presence rule is never overridden, so escalation only matters on a target
whose presence rule lets an absent person be notified (`always` or
`away_only`); `notify_switchboard.explain` reports it under `escalated`.

## Wiring a target to an alert

**Observer mode** — tick it on the target, and the router watches the alert
itself: routes `idle → on`, sends back-to-normal on `→ idle`, stops on
`on → off`. No `notifiers:` needed — and **no reminders**: an alert's
`repeat` changes no state, so there is nothing for the router to observe;
only the alert's own `notifiers:` calls carry them:

```yaml
alert:
  water_leak:
    name: Water leak
    entity_id: binary_sensor.leak_kitchen
    state: "on"
    repeat: [5, 15, 60]
    can_acknowledge: true
```

**Or drive the router from the alert** — leave observer mode off and add
`notifiers: [switchboard_leak]` to the same block, so the alert decides when
to send and repeats on its own schedule. This is the way to choose when people
should be reminded until somebody acknowledges.

Either way, the **back-to-normal** message never rings louder than the
target's **Importance of the back-to-normal message** (`done_priority`,
*normal* by default) nor louder than the alert itself: the end of a critical
leak does not sound through Do Not Disturb, and waits for the morning when
somebody is asleep. Set it to *critical* to have the old behaviour back.

## Adding a speaker as an output

A speaker is just another `notify.*` service — core already ships one that
speaks, the legacy `platform: tts` notify platform:

```yaml
notify:
  - platform: tts
    name: kitchen_speaker      # -> notify.kitchen_speaker
    entity_id: tts.home_assistant_cloud
    media_player: media_player.kitchen
```

Aim it at a Music Assistant player to get pause/announce/resume (a raw Cast
player is interrupted instead), then pick `notify.kitchen_speaker` in a
person's **Notify services** or straight in a target's audience as a bare
output. Two sibling voice adapters, **Cast Notifier** and **AirPlay
Notifier**, are **archived** — this platform does what they did, natively.
**Assist Satellite Notifier** stays, in maintenance mode, for
`assist_satellite`, which has no `notify` platform of its own.

## Bare outputs

An audience entry that is a `notify.*` service name (not a person) is a **bare
output**: a speaker, a wall tablet. It has no presence, silence, snooze, wake
time or summary — delivered now or not at all, with only what you sent merged
with the target's default data, no buttons — but still takes part in the
target's episodes. A bare `notify.persistent_notification` cannot be cleared
this way (no `tag` of its own) and stays on the dashboard until dismissed —
use a **person's** outputs instead if you want it cleared.

Some integrations (Alexa Devices, Telegram, core's notify groups) ship
`notify.*` **entities** rather than legacy services. From 0.7.0 such an output
is delivered through `notify.send_message` — `message` and `title` only, no
buttons or critical payload — and a legacy service of the same name always
wins. The pickers don't offer entities: type the entity id in directly.

## The night

A person with a silence entity has a queue that behaves like something a human
wakes up to.

- **A night in one tick**: *Create a night schedule* on a person's screen
  makes an ordinary `schedule` helper named after them, 22:00–07:00 every day,
  and lists it as their silence. It is yours from then on — edit its hours in
  **Settings → Helpers**; the router never changes or deletes it.
- **Wake time** (optional, the person's night settings, typed as `7:30`)
  flushes the queue at a fixed hour. Without one, it flushes when the silence itself ends (a
  `schedule.*` publishes that instant; an `input_boolean` does not, so a
  message it silenced is dropped, not deferred).
- **A floor**: a silence entity publishing a `min_priority` state attribute
  (e.g. a `schedule` block with `data: {min_priority: high}`) holds only
  calls below that priority — the rest still goes through.
- **A time to live**, counted from queuing: 2 h for `info`, 12 h for
  `normal`, none for `high`. `data: {ttl_minutes: 30}` overrides it per call,
  `0` never expires, and `critical` is never held back.
- **One notification, not eleven**: survivors become one digest per output —
  turn **Summarise the night** off on a person for one by one instead.
- **A fresh decision at flush time**: presence, snooze and silence are all
  re-checked against the message's original priority, not remembered.

## Closing the loop

For every target tied to an `alert.*`, the router remembers one **episode**
(from `idle → on` to the return to `idle`, who was told and on which outputs,
surviving a restart), so the **back-to-normal message reaches only those
people** — everybody else is dropped with `not_notified`. Mark your own call
the same way with `data: {switchboard_done: true}`. When an observer target's
episode ends, its notifications are **cleared** (Companion
`clear_notification`, `persistent_notification.dismiss`, and a night's digest
that mentioned it); turn **Clear the back-to-normal message** on to tidy that
one away too.

## Services

Everything the notification buttons do is also a service, refusing an invalid
call with an explicit error.

| Service | Fields | What it does |
|---|---|---|
| `notify_switchboard.acknowledge` | `target` | Turns off the target's alert, if it has one and allows it. |
| `notify_switchboard.snooze` | `target`, `minutes`, `person` (optional) | Stops that target for a while. Without `person`, the whole audience is snoozed. |
| `notify_switchboard.unsnooze` | `target`, `person` (optional) | Lifts a snooze immediately. |
| `notify_switchboard.silence` | `person`, `minutes` | Silences somebody for a while, for every target. Only `critical` still gets through. |
| `notify_switchboard.unsilence` | `person` | Lifts that silence immediately. |
| `notify_switchboard.explain` | `target`, `priority` (optional), `person` (optional) | Answers what would happen to a message sent right now, without sending anything. Call with **Return response**. |

`explain` (why didn't I get it?) reports the real decision per person —
decision, reason, and a translated `detail` naming the deciding object —
without sending anything; full example in
[`docs/quickstart.md`](docs/quickstart.md). Three repairs also turn silent
failures into a Repairs entry: a person with no notify service, a target tied
to a missing `alert.*`, and an output that keeps failing.

## `data` keys a caller can set

| Key | Meaning |
|---|---|
| `priority` | `info` / `normal` / `high` / `critical`; overrides the target's default. Only `critical` bypasses silence and snoozes. Not forwarded to `mobile_app_*` outputs since 0.7.0 (see [`docs/contract.md`](docs/contract.md), "Breaking"). |
| `source_entity` | The entity the message is about. |
| `tag` | Names the notification and de-duplicates a deferral. Defaults to `switchboard-<slug>`. |
| `ttl_minutes` | How long a held-back message is still worth delivering. `0` never expires. |
| `switchboard_done` | Marks this call as the target's "back to normal" message, routed at no more than its `done_priority`. |
| anything else | Merged over the target's default data, caller wins, passed to outputs untouched. |

A `critical` message also carries, on `mobile_app_*` outputs only, the keys
the [Companion docs](https://companion.home-assistant.io/docs/notifications/critical-notifications/)
give for a critical notification — full detail and an off switch
(**Settings** → "Make phones ring for critical alerts") in
[`docs/contract.md`](docs/contract.md).

The two [dashboard cards](docs/cards.md) come with the integration: an
alerts list with Acknowledge and Snooze, and one person's silence tile.
They are added to your dashboards' resources on startup; search for "Notify
Switchboard" in the card picker. If you installed them earlier as the separate
**Notify Switchboard Cards** HACS download, remove that one.

For cards, `sensor.switchboard_routing_table` publishes the table itself —
state is the number of targets, `targets` and `persons` attributes carry the
rest (exact keys in `docs/contract.md`) — without a target's `default_data`
or a person's notify services.

## Translations

The interface ships in English, French and Spanish, entity names included —
the **entity id itself never changes** across languages. Spanish is machine
translated and not yet reviewed by a native speaker — corrections welcome.
From 0.7.1 the screens use plain language rather than the contract's own
words; entity ids, service names and option keys are unchanged underneath
(mapping in [`docs/contract.md`](docs/contract.md)). From 0.8.0 the screens
call a target an **alert** (« alerte », « alerta ») and its slug its
**automation name** (« nom pour les automatisations »); a Home Assistant
`alert.*` entity is always spelled "a Home Assistant alert" to tell the two
apart.

En français : les principes du projet sont résumés dans
[`docs/fr/doctrine.md`](docs/fr/doctrine.md).

## Removal and roadmap

Settings → Devices & services → Notify Switchboard → delete removes the
`notify.switchboard` service and entity; it does not touch the `notify.*`
services it forwarded to. A night schedule created from a person's screen is
an ordinary Home Assistant helper and stays, and so does the blueprint copied
into your blueprints, and so does any card you put on a dashboard (its
resource is removed). Current release: **0.10.0** (the dashboard cards ship
with the integration; before it, one-click automation from a
shipped blueprint, a back-to-normal message that wakes nobody, observer mode's missing
reminders said on screen; before that, a first alert without code — names
instead of identifiers, observer mode by default, a shorter menu, a night
schedule in one tick — two-step editors, escalation, a scheduled priority floor, the routing-table sensor,
bare and entity outputs, a critical push per OS, plain-language interface) — see
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the full roadmap.

## Glossary

One word per concept. The other documents link here rather than redefining
anything.

| Word | What it means here |
|---|---|
| **Target** | One routing-table entry: an identity, an alert, an audience, how it is driven. Called an **alert** on screen from 0.8.0. Becomes `notify.switchboard_<slug>` — not the notify `target:` field, which names one or more of these. |
| **Automation name** | A target's slug, the `<slug>` of `notify.switchboard_<slug>`. Made from the target's name when it is created, never typed, never changed afterwards. |
| **Person** | A `person.*` this router knows, with the notify services that reach them and the entities that mean they are silent. |
| **Output** | A `notify.*` service — or, from 0.7.0, entity — a person's messages are handed to. |
| **Bare output** | An audience entry that is a `notify.*` service name rather than a person. See [Bare outputs](#bare-outputs). |
| **Audience** | The people a target is for, and its bare outputs. Anybody else is not considered at all. |
| **Presence rule** | Whether a person's `person.*` state has to be `home`, has to be away, or does not matter. |
| **Silence** | A person is silent while a silence entity is `on`, or a temporary `notify_switchboard.silence` runs — only `critical` gets through. *Quiet hours* is not a concept here: it is a silence entity plus a wake time. |
| **Priority floor** | A `min_priority` attribute on a silence entity that is `on`: holds only calls below that priority. |
| **Escalation** | `escalate_when_nobody_home`: one step louder for one message, when nobody in the audience is `home`. Never overrides the presence rule. |
| **Snooze** | One target stopped for a chosen number of minutes. |
| **Wake time** | The hour a person's night silence is treated as over. Optional. |
| **Deferral** | A message held back, not dropped, because the person is silent and their night has a known end. Re-decided in full when flushed. |
| **Summary** | The one notification a person gets when more than one deferral survives the flush. On by default. |
| **Episode** | What the router remembers between an alert's `idle → on` and its return to `idle`: who was told, on which outputs. |
| **Observer mode** | The router watching a target's alert itself instead of waiting to be called as one of its `notifiers:`. The recommended way to wire a target — one message when the alert goes off, one when it ends, no reminders. |
| **Done message** | A target's "back to normal" message: observer mode's, a call with `switchboard_done: true`, or the `done_message` of an alert that lists the router under `notifiers:`. Never louder than the target's `done_priority`. |

## Documentation

- [Contract](docs/contract.md) — the frozen public names and behaviour.
- [Architecture](docs/ARCHITECTURE.md) — the proxy model, decision engine and roadmap.
- [Known issues](docs/known-issues.md) — what was consciously left out, and why.
- [Accepted deviations](docs/accepted-deviations.md) — where this integration knowingly bends its own principles.
- [Quickstart](docs/quickstart.md) — route your first alert in about ten minutes.
- [Migration guide](docs/migration-guide.md) — moving from inline `notify.mobile_app_*` calls.
- [Blueprints](docs/blueprints.md) — importable automation blueprints.
- [Dashboard cards](docs/cards.md) — the alerts card and the silence tile, and their options.

## License

[MIT](LICENSE) © 2026 the maintainer. This integration is written almost
entirely by AI models, under the direction and responsibility of a single
human maintainer, who owns every product decision and tests each release on
real hardware — see [`docs/how-this-is-built.md`](docs/how-this-is-built.md)
before deciding how much to trust this code.
