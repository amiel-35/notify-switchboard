# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

Nothing yet.

## [0.7.1] - 2026-09-07

### Added

- Home Assistant's own notification drawer (`notify.persistent_notification`)
  is offered in the **Where to tell them** and **Who to tell** pickers. It is
  the output a household has before any phone is registered.

### Changed

- The whole interface is rewritten in plain language — the setup, the options
  menu and its steps, field labels, error messages, warnings, entity names and
  the action descriptions — in French, English and Spanish.
- People, devices and targets appear under the names your household gave them.
  An entity id is shown only where you have to go somewhere and change
  something.
- Every entry in the output pickers now carries a readable label: another
  person's phone reads as the device its owner named, and anything else is
  shown in words with its service name in brackets.
- `notify_switchboard.explain`, **Send somebody a test message** and **Send a
  test message through a target** now name devices, presence rules, importance
  floors and whereabouts in words instead of raw values. Those sentences are
  written in the instance language, which the test result screen now says.
- Every reason a message can be dropped has a sentence of its own; until now
  `delivery_failed` and `unknown_target` fell back to a generic one.
- Importance and presence are picked from translated labels instead of `info` /
  `normal` / `high` / `critical` and `always` / `home_only` / `away_only`. The
  stored values are unchanged.
- `README.md` gains "Words used in the interface", mapping each word on the
  screen to the term the documentation uses.
- Nothing about routing changes: no new option, no new step, no stored data to
  migrate. Upgrading from 0.7.0 changes what you read, not what you get.

## [0.7.0] - 2026-09-07

### Breaking

- `data.priority` is no longer forwarded to phone (`mobile_app`) outputs.
  Critical alerts now carry the Home Assistant Companion critical keys instead.
  If you were setting `data: {priority: high}` to make an Android notification
  urgent, remove it. Every other kind of output — a bare `notify.*` service, a
  speaker, a webhook — still receives `priority` untouched.
- `notify.notify` and `notify.send_message` are refused as audience entries,
  including when typed by hand. `notify.persistent_notification` stays allowed.

### Added

- **Raise the importance when the house is empty**, a new setting on the
  **What happens when the house is empty** step of a target. When nobody in its
  audience is home, the message moves up one step: normal becomes important,
  important becomes critical. It only bites on a target that notifies absent
  people; with a `home_only` presence rule an empty house means everybody is
  dropped anyway.
- A silence entity can publish a `min_priority` attribute — the `data:` block of
  a core `schedule` becomes state attributes — and then holds only the messages
  below that floor. A night that keeps the shopping list quiet and lets the leak
  alarm through, with no automation of your own. An unreadable floor silences
  everything; when several silences are on, the strictest decides.
- **Make phones ring for critical alerts**, a new setting on the **Target used
  by default** step, on by default. A `critical` message then reaches a phone
  with the Companion critical keys — the iOS critical sound, Android's
  `alarm_stream` channel. A key you set yourself is never overwritten.
- An audience may name a `notify.*` service or a `notify` entity — a kitchen
  speaker, a wall tablet, Telegram, Alexa, a notify group — instead of a person.
  Such an output has no presence, no silence, no snooze and no deferral, and
  receives only your `data` merged with the target's default data. A `notify`
  entity receives `message` and `title` and nothing else. The pickers list
  services; an entity is reached by typing its id.
- `sensor.switchboard_routing_table`, listing your targets and people for a
  dashboard card. It never exposes a target's default data.
- `notify_switchboard.explain` gains `escalated` and `outputs`, and its
  `priority` now reports the raised importance.
- The `acknowledged` event carries `person` alongside `user_id`.

### Changed

- `sensor.switchboard_routing_table` publishes no `state_class`, so it is not
  compiled into long-term statistics; its two attributes are kept out of the
  recorder.
- A message routed to a `notify.persistent_notification` audience entry is not
  cleared when the alert ends, so it stays on the dashboard next to its own
  back-to-normal message.

## [0.6.0] - 2026-09-07

### Added

- `docs/migration-guide.md`: where to start when you already have a pile of
  inline `notify.mobile_app_*` calls and `alert:` blocks — one target per alert,
  observer mode so nothing in your YAML has to change, and a rollback that is
  one menu action. `README.md` gains a Glossary defining target, person, output,
  audience, presence rule, silence, snooze, wake time, deferral, summary,
  episode and observer mode.
- Two options-menu entries, **Advanced settings of a target** and **Set up
  somebody's night**, and a checkbox on the step that shows the `alert:`
  snippet.
- A five-line recipe for turning a speaker into an output, using core's own
  `platform: tts` notify platform, in `README.md` and `docs/quickstart.md`.

### Changed

- Adding a target asks five questions — **Short identifier**, **Name**, **Alert
  watched**, **Who to tell**, **Watch the alert directly**. The other nine moved
  to an **Advanced settings** step with the same choices and the same defaults.
  A target created from the basic step alone routes exactly as it would have
  before.
- The person editor is split the same way: devices and silences on the first
  step, **Wake time** and **Sum it all up in one message** on a second one. Each
  half writes only its own fields, so changing a phone can never erase somebody's
  night.
- A routing-table row is called a **target** everywhere — interface, errors,
  warnings and documentation, in all three languages. "Rule" survives only in
  *presence rule*.
- A silenced person with no wake time is now held until their silence ends,
  when that silence publishes its own end (a core `schedule`). A silence that
  publishes no end — an `input_boolean`, a Focus sensor, a temporary
  `notify_switchboard.silence` — still drops the message exactly as before.
- The expiry defaults (not very important 120 min, normal 720 min, important
  never) are documented defaults, not frozen values: a future version may pick
  other numbers. Set your own on **How long a message set aside stays useful**.

### Fixed

- `notify_switchboard.silence` and `notify_switchboard.unsilence` now release or
  re-arm the queue they affect. Lifting a silence by hand used to leave a held
  message waiting for the following night.
- A message held with no wake time no longer loses its timer when a temporary
  silence outlives the night — it used to wait for the next night, which for a
  message with an expiry usually meant it never arrived.
- Renaming or deleting a silence entity now counts as that silence lifting,
  instead of leaving the queue waiting for an "off" that never comes.
- The `alert:` block shown after saving a target in observer mode no longer
  carries a `notifiers:` list. Pasting it as instructed wired the alert both
  ways at once and produced duplicate notifications.

### Removed

- The **Class** field of a target, which nothing ever read. A value already
  stored is ignored — not migrated, not deleted — and there is nothing to do by
  hand.

## [0.5.1] - 2026-09-07

### Fixed

- The default `data.tag` no longer reaches outputs that cannot read it. 0.5.0
  wrote it onto every output of every person, and adapters that validate their
  data refused the call outright: since 0.5.0, somebody whose output was a
  `notify.airplay_*` or `notify.satellite_*` service received nothing at all.
  The default tag now goes to phone (`mobile_app`) outputs and to
  `notify.persistent_notification` only.
- A `tag` you set yourself is your own key and still reaches every output.

## [0.5.0] - 2026-09-07

### Added

- A message set aside for the morning can now expire: not very important after
  2 h, normal after 12 h, important never. Change it for the household on the
  new **How long a message set aside stays useful** step, or for one call with
  `data.ttl_minutes` (`0` means "keep this one whatever the household says").
  An expired message is dropped with the new reason `expired`, instead of
  announcing at 07:00 that the front door was open at 23:31.
- One summary instead of a burst. When more than one message survives the night
  for somebody, they get a single notification per device listing them, rather
  than eleven banners at the moment they open their eyes. Turn it off per person
  with **Sum it all up in one message**.
- A back-to-normal message now reaches only the people who actually received
  something for that alert; everybody else is dropped with the new reason
  `not_notified`. Mark your own back-to-normal call with
  `data.switchboard_done: true`.
- Every message gets a name (`data.tag`, `switchboard-<slug>` by default), so a
  repeat updates the notification already on the phone instead of stacking a
  second one. A `tag` you set always wins.
- When a watched alert ends, the notifications it left on each phone are cleared
  and the matching dashboard notification is dismissed. The new target setting
  **Clear the back-to-normal message** extends that to the back-to-normal
  message itself. This applies to targets in observer mode only.

### Changed

- A message released in the morning is decided again from scratch: somebody who
  left the house under a `home_only` target is dropped on presence, somebody who
  snoozed at 02:00 is dropped as snoozed, a deleted target drops the lot. Its
  original importance is kept, so a target whose default changed overnight
  cannot silently re-grade it.
- A queue is flushed as soon as the last silence turns off, instead of waiting
  for the wake time. Somebody with both a night schedule and a Focus sensor
  needs both off; the wake time stays the upper bound.
- `sensor.switchboard_dropped_today` gains `expired` and `not_notified` in its
  `reasons` attribute. No new event type.
- Upgrading migrates the stored snoozes and deferrals; nothing to do by hand.

## [0.4.0] - 2026-09-07

### Added

- `notify_switchboard.explain`, a new read-only action. For a target — and
  optionally an importance and a person — it answers, per person, whether a
  message would be routed, set aside or dropped and why: which silence is on,
  when the snooze lifts, which presence rule decided, and which services it
  would reach. Nothing is sent and no counter moves.
- A fresh install works after one form. Adding the first person also creates a
  `default` target pointing at them, so `notify.switchboard` reaches a real
  phone straight away. That target picks up each new person automatically until
  you edit it, after which it is yours.
- Phones are picked from a list instead of typed. The person editor offers the
  instance's notify services, marks the ones registered to that person's own
  Home Assistant user and pre-selects them. A service that does not exist yet
  can still be typed in.
- iOS Focus sensors are proposed as silence entities for a new person. Android's
  Do Not Disturb is not; `docs/quickstart.md` carries the one-line template
  sensor that bridges it.
- **Send somebody a test message** and **Send a test message through a target**
  in the options menu. Each sends one real message through the ordinary path —
  counted, deferred or dropped like any other — and then shows the explanation
  for it.
- The `alert:` block to paste is generated for you on a confirmation step after
  saving a target, keyed on that target's own alert. Nothing is written until
  you submit that step.
- Two new warnings when the configuration cannot work: a person in an audience
  with no notify service at all, and a target tied to an `alert.*` that does not
  exist.

### Changed

- The person editor is two steps: pick the person, then choose their devices,
  silences and wake time. **Change somebody's devices** opens the second step on
  what is stored, so the list of discovered phones never silently re-adds an
  output you removed.

## [0.3.0] - 2026-09-07

### Added

- Entity names are translated into French and Spanish. The entity **ids** are
  unchanged in every language, so no `alert:`, automation or dashboard card
  breaks.
- `sensor.switchboard_deferred_today`, with its `queued` attribute, is now a
  documented name that will not change. The entity itself is unchanged.
- A new warning when somebody in the audience of a target that offers
  Acknowledge or Snooze buttons is not linked to a Home Assistant user — the
  link needed to tell who pressed a button. Make it in Settings → People.

### Changed

- Notifications go out to every device at once, each with a 30 second timeout:
  one phone off the network no longer holds back everybody else. The order in
  which the delivery events fire is no longer promised; the counts and the
  per-person outcomes still are.
- The five `notify_switchboard.*` actions now exist even when the entry is
  unloaded, so an automation naming one no longer fails at startup with "action
  not found". Called with nothing loaded, each raises a translated error.
- A Companion button press is credited to the person whose `person.*` is linked
  to the Home Assistant user who pressed it, whatever the device says.

### Fixed

- A timer left running when Home Assistant stops, and an error with a traceback
  logged at every single shutdown.
- Warnings about a missing target or an unusable output now go away once the
  cause is fixed, instead of outliving the change they asked for.
- Somebody whose delivery raised an unexpected error is no longer missing from
  the counters; it counts as `delivery_failed` like any other delivery that
  reached nobody.
- A person's device is named after the friendly name you set ("Alice Martin")
  rather than the entity id ("Alice").

## [0.2.0] - 2026-09-07

### Added

- Five actions for callers that are not a Companion button — a dashboard card, a
  script, an automation: `notify_switchboard.acknowledge`, `snooze`, `unsnooze`,
  `silence` and `unsilence`. A refused or invalid call raises a translated error
  instead of being logged and swallowed.
- A temporary, person-wide silence (`silence` / `unsilence`), from 1 to 1440
  minutes. It shows in `binary_sensor.<person>_silenced` with an `until`
  attribute, survives a restart, expires on the minute, and is bypassed by a
  `critical` message. Your configured silence entities are read, never touched.
- Three optional per-target texts: **Wording of the message** and **Wording of
  the back-to-normal message**, both templates with the target's alert available
  as `alert`, and **Title by default**, used whenever a call gives no title. All
  three are empty by default.
- A warning when the same unknown target or unusable person has been refused
  three times — a dashboard card left pointing at a renamed target.

### Changed

- `binary_sensor.<person>_silenced` is on when either kind of silence is
  running. Its `sources` attribute still lists the configured entities only.
- A message silenced only by a temporary silence is dropped rather than held
  until morning: an hour of requested quiet should not become tomorrow. A
  configured night silence still holds it.
- A message held for the morning re-checks the silence before going out and
  waits again if the night is still on. A `critical` message goes out
  regardless.
- New **Change somebody's devices** and **Edit a target** menu entries open a
  form filled with what is stored, and a rejected form hands back what you
  typed. Opening a target to change one word no longer resets its other fields
  to their defaults.
- Acknowledging is credited in the logbook to the person who tapped the card or
  the button, not to the integration.
- The five actions are callable by any Home Assistant user, by design: the wall
  tablet runs under a non-admin account and its cards are the main caller. What
  bounds them is the target's own acknowledgement list, not the caller's role.

## [0.1.0] - 2026-09-07

### Added

- A routing table in the options: people (their notify services, their silence
  entities, their wake time) and targets (identifier, name, importance by
  default, watched `alert.*`, audience, presence rule, acknowledgement, snooze
  durations, default data, observer mode).
- `notify.switchboard`, plus one `notify.switchboard_<slug>` per target, so an
  `alert:` can name its target in `notifiers:`.
- Routing decides per person: audience, presence rule, silence, running snooze,
  a `critical` bypass and a refusal to call itself. Every drop carries a reason.
- Companion buttons: **Acknowledge** when the target watches an alert and allows
  it, and one **Snooze n** per configured duration. Acknowledging turns the
  alert off; a snooze survives a restart.
- Night deferral: a message that arrives while somebody is silenced is set aside
  and delivered at their wake time, correctly across midnight and across a
  daylight-saving change. One that came due while Home Assistant was down goes
  out at the next start, not a day later.
- Observer mode: watch a target's `alert.*` and route on its transitions without
  being listed in its `notifiers:`.
- Entities: `binary_sensor.<person>_silenced`,
  `sensor.<person>_last_notification`, `sensor.<person>_active_snoozes`,
  `sensor.switchboard_routed_today`, `sensor.switchboard_dropped_today` (with a
  `reasons` attribute), `sensor.switchboard_deferred_today` and
  `event.switchboard_delivery`. The counters reset at local midnight.
- Warnings for an unknown target and for an output that has been unusable —
  missing, or failing on every call — more than three times in a row.
- A diagnostics dump with message bodies and every default-data value redacted,
  plus the routing table, the snoozes, the deferrals and the last twenty
  decisions.
- Interface, warnings and button labels in English, French and Spanish.

### Changed

- The `notify.switchboard` entity is the degraded path: it routes to the target
  used by default, with normal importance.
- Upgrading from 0.0.1 reuses `notify.switchboard` instead of leaving an
  unavailable entity beside a new `notify.switchboard_2`. Nothing to do by hand.

[Unreleased]: https://github.com/amiel-35/notify-switchboard/compare/v0.7.1...HEAD
[0.7.1]: https://github.com/amiel-35/notify-switchboard/compare/v0.7.0...v0.7.1
[0.7.0]: https://github.com/amiel-35/notify-switchboard/compare/v0.6.0...v0.7.0
[0.6.0]: https://github.com/amiel-35/notify-switchboard/compare/v0.5.1...v0.6.0
[0.5.1]: https://github.com/amiel-35/notify-switchboard/compare/v0.5.0...v0.5.1
[0.5.0]: https://github.com/amiel-35/notify-switchboard/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/amiel-35/notify-switchboard/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/amiel-35/notify-switchboard/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/amiel-35/notify-switchboard/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/amiel-35/notify-switchboard/compare/v0.0.1...v0.1.0
