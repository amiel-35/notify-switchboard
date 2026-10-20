# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.2.0] - 2026-09-07

**Highlights**

- If your card config still sets `snooze_minutes: [15, 60, 480]` from the
  0.1.x editor, remove it — the card now takes its durations from the
  router instead, and that old default would be rejected.
- Both cards now read Notify Switchboard 0.7.0's routing table, so target,
  snooze durations, and wake time no longer need to be repeated in YAML.
- The alerts card shows who acknowledged an alert, and can ask a kiosk
  user who they're snoozing for before acting.
- The README's new "Router version matrix" spells out what each router
  version (0.1–0.7) unlocks in these cards.

Consumes Notify Switchboard 0.7.0. Nothing here is required: against an
older router every 0.1.x behaviour is unchanged.

### Added

- Both cards read `sensor.switchboard_routing_table` (router 0.7.0) and
  derive from it what they used to demand in YAML.
  `switchboard-alerts-card` derives each alert's target slug (from the
  row's `alert_entity`), that target's own `snooze_minutes` and its
  `allow_acknowledge`; `switchboard-silence-tile` derives the tile
  person's `wake_time`. `target_map`, `snooze_minutes` and `wake_time`
  remain as **overrides** — set, they still win — and both editors now
  mark them "optional since Notify Switchboard 0.7.0".
- `switchboard-alerts-card` shows "Acknowledged by …" on an acknowledged
  alert, from the `person` / `user_id` the router 0.7.0 puts in the
  `acknowledged` payload of `event.switchboard_delivery`. The event
  entity keeps only its last event, so the line shows while that last
  event is this target's acknowledgement and disappears afterwards —
  the router publishes authorship nowhere else. A person the router could
  not resolve is shown as a shortened user id, never guessed at.
- `switchboard-alerts-card` option `person_picker` (default `false`): on a
  kiosk or wall tablet, Snooze first asks *who* it is for, listing the
  persons from the routing table by their `person.*` name plus an
  explicit "Everyone". Acknowledge never asks — the router reads the
  acting user from the call itself. The chooser is plain focusable
  buttons at the 48 px touch target, in the same disclosure as the
  durations, and forgets the choice when it closes.

### Changed

- A target that the routing table marks `allow_acknowledge: false` — or
  that carries no `alert_entity` at all, which is the router's own test
  (`bool(alert_entity) and allow_acknowledge`) — is acknowledged with the
  native `alert.turn_off` instead of `notify_switchboard.acknowledge`,
  which the router would refuse.
- The kiosk person picker offers only the persons of **that target's own
  audience**. `notify_switchboard.snooze` refuses a person outside the
  row's audience and raises a `repairs` issue when a card keeps asking, so
  a name the router would refuse is never offered; an audience whose
  entries are all bare `notify.*` outputs shows no picker at all.
- The `person` option is held to that same audience: when the routing
  table's row for a target does not name the configured person, the card
  snoozes for the whole audience — the label saying so — instead of
  sending a name the router would refuse. The menu stays; only the person
  is dropped. With no row derived (an older router), the option is sent
  exactly as before.
- A target the routing table publishes with an empty `snooze_minutes` has
  snooze switched off — the router accepts no duration for it — and the
  card now hides its snooze menu instead of falling back to the built-in
  `[15, 60, 480]`, every one of which would have been refused. The
  built-in fallback applies only when the routing table holds no row for
  that alert. **If your card still carries `snooze_minutes: [15, 60, 480]`
  from the 0.1.x editor, delete the option** to pick up each target's own
  durations.
- Where the routing table describes the target the card will call, a
  `snooze_minutes` override now **narrows** that target's own list rather
  than replacing it: the router refuses any duration it does not offer, so
  only the durations both agree on are shown, and none at all when they
  agree on none. A `target_map` naming a target the router does not
  publish keeps the override whole — the 0.1.x path, where the card is the
  only source of durations.
- Picking a snooze duration now closes that row's menu and returns focus
  to its Snooze button, instead of leaving an open panel offering an
  action already taken.
- `snooze_minutes: []` is accepted in the card config and read as "derive
  from the router" — it is what the editor emits once every duration is
  cleared — rather than rejected with an error card.
- "Acknowledged by …" is dropped when the alert has changed since the
  acknowledgement event: an alert that fired again is a new one nobody has
  acknowledged yet, and the earlier acknowledger is not credited with it.
- A routing-table `persons` entry whose `entity_id` is not a `person.*` is
  dropped as malformed rather than offered in the picker.
- `snooze_minutes` and `wake_time` are no longer defaulted in
  `setConfig`, and the alerts editor no longer pre-fills the snooze
  durations field. A stored default was indistinguishable from a
  deliberate choice and would have shadowed the routing table forever.
  The built-in fallbacks (`[15, 60, 480]`, `07:00`) still apply when
  neither the config nor the router says otherwise.

### Documentation

- README: added a "Router version matrix" mapping each Notify Switchboard
  router version (0.1–0.7) to what these cards show or do, and dropped the
  stale "planned for Notify Switchboard 0.2.0" / "not yet part of the
  frozen router contract" wording now that those services and entities
  have shipped.

## [0.1.1] - 2026-09-07

**Highlights**

- Fixes the compact alerts badge title wrapping letter-by-letter in a
  narrow sections column.
- The compact badge shows count chips only by default; its title only
  appears once explicitly configured, and it no longer wraps.
- The badge now asks dashboards for a little more column width so it
  isn't squeezed down to a single column.

### Fixed

- `switchboard-alerts-card` compact badge: the title no longer wraps
  letter by letter in a narrow sections column (e.g. "Al / ert / es").
  The compact badge now shows chips only by default — `title` is only
  rendered on the badge once explicitly configured, and when it is, it is
  laid out to never wrap (`white-space: nowrap` + ellipsis, with chips
  shrinking first). `getGridOptions()` for compact mode now declares
  `min_columns: 3` / `columns: 4` so the sections view has less room to
  squeeze it down to a single column in the first place. (#1)

## [0.1.0] - 2026-09-07

**Highlights**

- Initial release: `switchboard-alerts-card` (list, acknowledge, and
  snooze alerts) and `switchboard-silence-tile` (one person's silence
  status and controls).
- Config is validated up front — a bad option shows a clear Lovelace
  error naming it instead of a card that crashes.
- Accessible by default: focus-trapped dialogs, icon-plus-text state
  (never colour alone), and disabled actions that stay focusable and
  explain themselves.
- Visual editors with English, French, and Spanish translations, with a
  graceful fallback to native `alert.*` actions where a Notify
  Switchboard service isn't available yet.

### Added

- `switchboard-alerts-card`: lists `alert.*` entities with acknowledge,
  un-acknowledge, and (when the router supports it) snooze actions. Compact
  badge mode with a dialog, full inline list mode.
- `switchboard-silence-tile`: shows one person's silence state, active
  snooze count, and last notification, with silence / clear-snoozes /
  lift-silence controls.
- Full `setConfig` validation on both cards: `entities`, `snooze_minutes`,
  `mode`, `target_map`, `show_acknowledged`, `person` and `wake_time` are
  checked up front, so a bad config produces a Lovelace error card naming
  the option instead of a card that throws during render.
- `unavailable` / `unknown` alerts are a distinct fourth state — a neutral
  chip with text and a `mdi:help-circle-outline` icon, no actions, and its
  own count on the compact badge. They are never shown as acknowledged.
- Compact badge count chips pair an icon and an `aria-label` with the
  number: state is never conveyed by colour alone.
- The badge dialog traps focus (Tab / Shift+Tab cycle inside it) and
  Escape closes it and restores focus to the badge button.
- Optional `person` on the alerts card, passed to
  `notify_switchboard.snooze`. Without it the menu says the snooze applies
  to everyone.
- "Today" footer on the alerts card, reading
  `sensor.switchboard_dropped_today` and `event.switchboard_delivery` when
  those entities exist.
- Clicking an alert's name opens Home Assistant's more-info dialog.
- `getGridOptions()` on both cards for the sections layout.
- Visual editors built on `ha-form` with entity/select/object selectors and
  translated labels, degrading to a YAML hint when the Home Assistant
  frontend globals are absent. Emitted configs never carry empty keys.
- English, French, and Spanish translations, selected from
  `hass.locale.language`.
- Version banner logged on load.
- Graceful degradation: every action that depends on a Notify Switchboard
  0.2.0 service checks `hass.services` first and falls back to native
  `alert.*` actions, or marks itself `aria-disabled` with a visible
  explanation.

### Fixed

- "Clear" no longer invents `notify_switchboard.silence(minutes: 0)`, a
  call that is not in the router contract. Clearing snoozes calls
  `unsnooze`; lifting a silence calls the dedicated `unsilence` service.
- `sensor.<person>_active_snoozes` in `unavailable` / `unknown` is reported
  as unknown ("—") instead of being read through `Number()` and shown as
  "No active snoozes".
- "Until wake" is computed on the Home Assistant instance's timezone
  (`hass.config.time_zone`) rather than the browser's.
- Cards only re-render when an entity they actually read changes, instead
  of on every state change in the instance; the 30 s duration tick is
  skipped when nothing is listed.
- The snooze menu's `<summary>` keeps its native role and exposes
  `aria-expanded`; Escape closes it and restores focus.
- Disabled tile actions stay focusable (`aria-disabled`) and the tile
  explains why in one visible line.
- The dialog scrim uses `--dialog-scrim-color`, hover text uses
  `--text-primary-color`, and the host no longer paints its own background
  over the theme's `ha-card`.

[Unreleased]: https://github.com/amiel-35/notify-switchboard-cards/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/amiel-35/notify-switchboard-cards/compare/v0.1.1...v0.2.0
[0.1.1]: https://github.com/amiel-35/notify-switchboard-cards/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/amiel-35/notify-switchboard-cards/releases/tag/v0.1.0
