# ADR 0023: One-click automation, a quiet all-clear, and observer mode's reminders said plainly

Date: 2026-10-12

## Status

Accepted (maintainer's go on 2026-10-12, sprint 9).

## Context

0.8.0 brought "could I configure my first alert without help?" from 4/10 to
7/10 for a non-technical French reader. Three things stop it there, two found
by that review and one by a real-world test the same day:

- **An alert tied to nothing ends on homework.** `target_ready_manual` says,
  correctly, that the alert will not go off on its own, and explains how to
  build the automation by hand: Settings > Automations & scenes > Create
  automation, When: the sensor, Then: the action `notify.switchboard_<slug>`
  with a message. Every word is right and the reader still has to assemble a
  trigger and an action they have never seen.
- **The all-clear rings like the alarm.** An `alert:` with
  `notifiers: [switchboard_<slug>]` calls that one service for its first
  message, for every `repeat`, and for its `done_message`
  (`homeassistant/components/alert/entity.py`: `_notify`,
  `_notify_done_message`, both through `_send_notification_message`, with the
  same `title` and the same static `data`). The router saw three identical
  calls and routed all three at the target's `default_priority`. On a
  `critical` target, "the leak is over" arrived as a critical push — sound at
  full volume through Do Not Disturb — at the maintainer's home. Observer
  mode's own `→ idle` message had the same flaw, at the same priority.
- **Observer mode loses the reminders.** Observer mode routes on the alert's
  `idle → on` and `→ idle` transitions (`dispatcher.py`,
  `_async_alert_changed`). A core alert's `repeat` changes no state: its
  timer calls `_notify`, which calls the `notifiers:` and nothing else. So a
  target in observer mode — the default since 0.8.0 — sends one message when
  the leak starts and one when it ends, and never a reminder. Nothing on
  screen says so.

## Decision

### 0. Guard-rails, unchanged

- The router stays a pure notify proxy (ADR-0002). The blueprint (§1) is an
  ordinary automation the user owns; the automation calls the router, never
  the other way round.
- No timer and no counter of the router's own (ADR-0021 §0). §3 explicitly
  does not add one.
- No service, entity, `data` key, drop reason or `event.switchboard_delivery`
  type is added or removed. The config entry `VERSION` / `MINOR_VERSION` and
  the store's `STORAGE_VERSION` / `STORAGE_MINOR_VERSION` do not move (§2.5
  explains the one optional key a stored deferral gains).

### 1. A blueprint shipped with the integration, one click away

**What ships.** The integration package carries one automation blueprint in
three languages, identical but for its texts:

```
custom_components/notify_switchboard/blueprints/en/alert_from_a_sensor.yaml
custom_components/notify_switchboard/blueprints/fr/alert_from_a_sensor.yaml
custom_components/notify_switchboard/blueprints/es/alert_from_a_sensor.yaml
```

Blueprints are not translatable in Home Assistant (a blueprint's `name`,
`description` and input labels are plain text), so the only way for a French
household to meet a French form is a French file. Its inputs:

| Input | Selector | Default | Meaning |
|---|---|---|---|
| `trigger_entity` | entity | — | the sensor that signals the problem |
| `trigger_to` | text | `on` | the state that sets the alert off |
| `alert_name` | text | — | the alert's automation name, the `<slug>` of `notify.switchboard_<slug>` |
| `message` | text | `""` | the text; empty means the sensor's name |
| `done_message` | text | `""` | sent when the sensor leaves that state, with `data.switchboard_done: true`; empty means nothing is sent |
| `priority` | select | `default` | `default` (the alert's own), `info`, `normal`, `high`, `critical` |

Its done trigger ignores a change to `unavailable` or `unknown`, so a
sensor that drops off the network does not announce the end of anything; its
start trigger fires from any state, so a leak that starts during a restart or
a sensor that comes back already wet sets the alert off (amended, see below). Every call carries `data.source_entity` (contract §"Input").

**How it reaches the user — verified in 2026.9.1.** Core has no mechanism for
an integration other than `automation`/`script` to ship blueprints:
`DomainBlueprints.async_populate` (`homeassistant/components/blueprint/models.py`)
copies `homeassistant/components/automation/blueprints/` into
`<config>/blueprints/automation/homeassistant/`, once, when the folder does not
exist, and nothing else. `DomainBlueprints._load_blueprints` globs
`<config>/blueprints/automation/**/*.yaml` on every listing and loads any path
it has not cached, so a file that appears there is listed the next time the
blueprint page is opened, with no reload.

The options flow therefore does what core does for its own examples: when it
shows `target_ready_manual` — the one screen that ends on "this alert needs an
automation" — it copies the file for the instance language (`fr`, `es`, else
`en`) to

```
<config>/blueprints/automation/notify_switchboard/alert_from_a_sensor.yaml
```

in an executor job, **only if no file is there**. It never overwrites one and
never deletes one, including when the alert, the person or the config entry
is removed: from the moment it exists, it is the user's, exactly like the
night schedule of ADR-0022 §5. A user who edited it keeps their edit; a user
who deleted it gets it back only by reaching that screen again, which is the
moment they need it. The copy happens long after `automation`'s own
`async_populate` ran at start-up, so creating
`blueprints/automation/notify_switchboard/` can never stop core from
populating `blueprints/automation/homeassistant/`.

**The one click.** The frontend (20260826.6, the version 2026.9.1 pins)
offers no URL that opens the automation editor on a given blueprint:
`showAutomationEditor` passes its initial config through a module variable
(`src/data/automation.ts`, `initialAutomationEditorData`), not the URL. What
it does offer is the blueprint list, `/config/blueprint/dashboard`, where a
click on a row calls `showAutomationEditor({alias, use_blueprint: {path}})`
(`src/panels/config/blueprint/ha-blueprint-overview.ts`, `_handleRowClicked`
→ `_createNew`). `target_ready_manual` links there — a same-host link, which
`ha-markdown-element` leaves in the same window — names the blueprint as the
list shows it, and gives the automation name to type into it. One click on
the link, one on the row, two fields and Save.

If the copy fails (a read-only configuration, a full disk), the link becomes a
My Home Assistant `blueprint_import` link
(`src/panels/my/ha-panel-my.ts`: `blueprint_import` →
`/config/blueprint/dashboard/import`, parameter `blueprint_url`) to the same
file on GitHub, in the instance language. Nothing else on the screen changes.

**The fallback stays.** The screen keeps the action name (`{service}`) for
somebody who prefers to build the automation themselves, and the `alert:`
block (`{snippet}`) for somebody who wants reminders and an Acknowledge
button — both are what 0.8.0 already showed, now after the blueprint rather
than instead of it.

**Rejected:**

- *Creating the automation from the options flow.* Core keeps UI automations
  in `automations.yaml` behind the `config` integration's HTTP views; writing
  one from an integration is reaching much further into core than copying a
  file core itself would copy, and an automation the user never saw being
  built is not one they own.
- *A blueprint per alert, with the automation name baked in.* One more file
  per alert in the user's configuration, orphaned when the alert is removed,
  and a public path per slug. Typing a name the screen shows is cheaper.
- *Only a My Home Assistant import link.* It needs internet access, GitHub,
  and the My Home Assistant redirect configured, and ends on an import dialog
  before the blueprint is usable — three things that can fail before the
  first click helps. It is the fallback, not the way.
- *Writing the file at every start-up.* It would recreate a file the user
  deleted on purpose, at every restart.

### 2. A done message never rings louder than the target's `done_priority`

#### 2.1 The rule

A target may carry **`done_priority`**, one of `info`, `normal`, `high`,
`critical`. Absent means **`normal`**. It is written only when it is not
`normal`, so every target stored before 0.9.0, and every target created
through `target` alone, keeps the exact row it had.

A **done message** is routed at the lower of two priorities: the priority it
would otherwise have had — after the caller's `data.priority` and after
`escalate_when_nobody_home` — and the target's `done_priority`. The ceiling is
applied last, so it holds whatever raised the call.

The capped priority is the effective one everywhere downstream, exactly as an
escalated one is (ADR-0021 §1): the silence and snooze bypass, the
`authenticationRequired` flag, the critical payload and the `priority` of the
`routed` event. In particular a done message capped at `normal` is held by a
person's silence like any `normal` message — the end of a 3 a.m. leak waits
for the morning instead of waking the house a second time.

`done_priority: critical` restores the 0.8 behaviour for a household that
wants it; `done_priority: info` makes the end of an alert as quiet as the
router can make it.

#### 2.2 Which calls are done messages

Two kinds already were (contract v0.5, ADR-0019 §5), and keep everything they
had — the episode filter (`not_notified`) and the `-done` default tag:

- observer mode's `on|off → idle` message;
- any call carrying `data.switchboard_done: true` (the blueprint of §1 sends
  one).

One kind is new, and is a done message **for its priority only**:

- **the call a Home Assistant `alert:` makes through its `notifiers:` while it
  is ending.** Core's `end_alerting` sets `_firing = False`, then awaits
  `_notify_done_message()`, and only then calls `async_write_ha_state()`. The
  router's legacy service runs inside that await (a non-blocking
  `services.async_call` starts its handler eagerly,
  `homeassistant/core.py` `ServiceRegistry.async_call`,
  `async_create_task_internal(..., eager_start=True)`). At that instant the
  live `AlertEntity.state` property already answers `idle`, while the state
  machine still holds `on` (or `off` if it was acknowledged). During the
  first message the entity says `on` and the state machine `idle`; during a
  `repeat` both say `on`; between episodes both say `idle`. That
  disagreement is only a **suspicion** (amended, see below): it also lasts
  after a `done_message` template that failed to render. So: when a call
  reaches `notify.switchboard_<slug>` (or `notify.switchboard` resolving to
  `<slug>`), the row names an `alert_entity`, the `alert` entity component
  (`homeassistant/helpers/entity_component.py`, `DATA_INSTANCES`, the same
  lookup core's own `async_update_entity` does) holds that entity, its live
  `state` is `idle` and the stored state is `on` or `off`, the handler yields
  once (`asyncio.sleep(0)`); only if the stored state then reads `idle` is
  the call that alert's done message.

Why priority only. That call has carried the target's ordinary default tag
(`switchboard-<slug>`) since 0.5, so on a phone it **replaces** the alert's
notification, which is what a household that wired an `alert:` sees today and
wants to keep: one notification, which ends reading "all clear". Giving it the
`-done` tag would leave the critical notification on the screen next to the
all-clear, because a `notifiers:` target is not tidied up (contract v0.5
§"Closing an episode", unchanged). And the episode filter is not applied
either: making the end of an alert depend on how the episode recorded its
first message is a risk this sprint does not need to take to stop a phone
ringing. Both can be revisited on their own.

When anything about the recognition is missing — `alert` not loaded, the
entity not a core `AlertEntity` (a template or a test entity), the call
arriving after core already wrote `idle` — the call is routed exactly as in
0.8. The recognition fails towards the old behaviour, never towards dropping
a message.

#### 2.3 Where it is set

`done_priority` is a field of the public step `target_advanced`, right after
`done_message`, with the same four values and labels as `default_priority`.
ADR-0021 §1 gave escalation a step of its own to avoid amending
`target_advanced`'s field list; this ADR amends it instead, because the
setting belongs next to the text it governs and a one-field screen for it
would be harder to find than to justify. The contract's v0.9 addendum lists
the ten fields.

#### 2.4 Alternatives rejected

- *Recognising the done message by its text* (the row's `done_message`, or a
  configured string). The alert renders its own template; the row would have
  to repeat it, and the two drift the first time somebody edits one.
- *An `alert:` pattern instead of code.* An `alert:` has one `notifiers:` list
  and one static `data`, shared by all three messages; no YAML can tell the
  router which call is the last one.
- *Reading the state machine alone.* At the decisive instant it still says
  `on` — that is the bug.
- *A `done_priority` defaulting to the target's own priority* (no change
  unless asked). The observed behaviour is the bug; a default that keeps it
  would make every household find the setting after the first false alarm.

#### 2.5 A deferred done message keeps its ceiling

A done message held by a silence is deferred like any other, and its flush
re-runs the whole decision (ADR-0019 §3). For the two kinds that carry
`switchboard_done: true` in their `data`, the flush sees the key again. For
the new kind it would not, so a stored deferral gains one optional key,
`done: true`, read as false when absent. Older records need no migration and
an older version reading a newer record ignores the key, so the store version
does not move.

### 3. Observer mode does not carry reminders — said, not changed

Every place that recommends observer mode now says what it does not do, in
`en`, `fr` and `es`:

- the `observer_mode` help on `target` and `target_edit`: one message when the
  Home Assistant alert goes off and one when it ends, **no reminders**; for
  reminders, untick it and list the router under the alert's `notifiers:`;
- `target_ready`: the same sentence, after "nothing else to do";
- `target_saved` (observer off): that this way, the alert's reminders are
  sent too;
- the README's "Wiring a target to an alert", the quickstart and the doctrine.

**A doctrine-compatible way to follow repeats, proposed and not implemented.**
§2.2 shows the router can tell the three calls of an alert apart at call
time. A target in observer mode whose alert *also* lists
`switchboard_<slug>` under `notifiers:` could therefore route only the
`repeat` calls (entity and state machine both `on`) and ignore the first
message (entity `on`, state machine `idle` — observer mode routes it on the
transition) and the done message (observer mode routes its own). Core's
alert keeps the clock; the router owns no timer. It is not implemented here
because a recognition that fails — an alert that is not a core
`AlertEntity`, a call that arrives late — would send every message twice, and
a duplicate critical push is worse than a missing reminder. It needs its own
sprint, a test on a real instance, and the maintainer's decision.

## Contract changes (docs/contract.md, v0.9 addendum)

- One optional target key, `done_priority`, and the ceiling rule of §2.1.
- One more kind of call that is a done message for its priority (§2.2).
- `target_advanced` holds ten fields.
- One frozen path and six frozen input names: the blueprint
  `notify_switchboard/alert_from_a_sensor.yaml` and its inputs — automations
  built from it name both.

## Consequences

- A newcomer who adds an alert tied to nothing reaches a working automation
  without writing a trigger or an action.
- The end of a critical alert is announced, quietly, and waits for the
  morning if somebody is asleep. A household that wants the old behaviour
  sets `done_priority: critical`.
- The recognition of §2.2 leans on two core implementation details — the
  order of `end_alerting` and the live `state` of `AlertEntity` — in a core
  integration whose development is frozen ("DEVELOPMENT OF THE ALERT
  INTEGRATION IS FROZEN", `alert/entity.py`). If core ever reorders them, the
  recognition stops and the all-clear rings as in 0.8; nothing else breaks.
  `docs/known-issues.md` records it.
- `test_s6_target_editor.py`'s field list of `target_advanced` gains
  `done_priority`; that amendment, and nothing else, is listed in
  `tests/acceptance/README.md` §Sprint 9.

## Amendment 2026-10-12 — correction round

A code review ("go with fixes") and a non-technical French reading (8/10) of
the first implementation, plus an end-to-end run on the maintainer's dev
instance, led to the following.

### §2.2, amended: a suspicion confirmed, never trusted alone

The first implementation treated "live `idle`, stored `on`/`off`" as proof.
A review probe showed it is not: when the alert's `done_message` template
raises — `{{ states('sensor.h') | float }}` with the sensor `unavailable` —
the exception stops `end_alerting` before `async_write_ha_state()`, and the
two answers stay apart until the next firing. Every call to the target in
that window, a critical "second leak" included, was capped.

The handler now yields once (`asyncio.sleep(0)`) when it suspects the end.
For the real done message, `end_alerting` resumes in the meantime and writes
`idle` (with several notifiers, after the last one); a stuck alert writes
nothing. Only a stored `idle` after the yield confirms. Anything else keeps
the requested priority: **a real alarm is never downgraded; when in doubt it
rings.** Tested with a failing template and with one alert calling two
targets.

A call that goes through a `notify.group` containing `switchboard_<slug>` is
not recognised: the group calls the router from a task of its own, after the
state is already `idle`. The all-clear then rings at the target's priority, as
in 0.8 (`docs/known-issues.md`).

### §1, amended: the alert is saved before its confirmation

The confirmation screens were titled "Alert saved" while nothing was written
until they were submitted — and `target_ready_manual` invites the user to
leave through the blueprint link, which discards an options flow. The target
is now written to `entry.options` when the `target` or `target_edit` form is
submitted (`async_update_entry`, a deep copy); `target_saved`, `target_ready`
and `target_ready_manual` are informative and their submit only closes the
flow, or opens `target_advanced` when its box is ticked, which writes again.
This amends ADR-0022 §3 ("nothing is written until the last step") for the
target confirmations only.

### §1, amended: the blueprint

- The start trigger no longer ignores `unknown`/`unavailable` as a *from*
  state: a leak starting during a restart (`unknown → on`) or a Zigbee sensor
  coming back wet (`unavailable → on`) sets the alert off. The done trigger
  still ignores a change *to* them.
- `source_url` and the fallback import link point at this version's release
  tag (`v0.9.0`), not `main`, so "Re-import" never fetches a blueprint newer
  than the integration that installed it; a test ties the tag to the
  manifest version.
- The French and Spanish names start with the integration's name as those
  screens show it ("Standard de notification (Notify Switchboard) : …",
  "Centralita de notificaciones (Notify Switchboard): …"), so the blueprint
  is found under the name the user knows.

### §3, amended: no YAML key on screen

The word `notifiers` leaves the interface: the `observer_mode` help says that
the next screen explains how to keep reminding people until somebody answers,
and the technical detail stays in the documents. The advanced `message` and
`done_message` help say that without a Home Assistant alert those texts are
set in the automation.
