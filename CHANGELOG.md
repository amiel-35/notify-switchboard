# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

Router 0.6.0 — **consolidation** (contract v0.6 addendum, ADR-0020), on top of
the 0.5.1 and 0.5.0 notes below, which are in `main` but not tagged.

Every release since 0.1.0 added something. This one subtracts: a newcomer now
meets **five fields** on the first form instead of fifteen, one word per
concept instead of four, and documents that agree with the code. It introduces
**no routing rule, no entity, no action and no drop reason** — with one scoped
exception, the meaning of an absent wake time, because moving that field behind
an advanced step without deciding what leaving it empty means would have turned
"hold this until morning" into "drop this".

### Changed

- **The target editor is two steps.** `target` asks exactly five things —
  `slug`, `name`, `alert_entity`, `audience`, `observer_mode` — and a second
  step, `target_advanced`, holds the nine that used to sit on the same form
  (`default_priority`, `presence_rule`, `allow_acknowledge`, `snooze_minutes`,
  `default_data`, `message`, `done_message`, `default_title`, `clear_done`)
  with **identical selectors and identical defaults**. A target created
  through the basic step alone is byte-for-byte the row 0.5 wrote for the same
  five answers, and routes the same way.
- **The person editor likewise.** `person_outputs` keeps `outputs` and
  `silence_entities`; `wake_time` and `summary` move to `person_advanced`.
- **Each half writes only its own fields.** Changing a priority can never
  empty an audience, and changing a phone can never delete somebody's night —
  the 0.2.0 data-loss bug a careless split re-creates. `managed` is cleared by
  either half of the target editor, as submitting the editor always has.
- **Two new options-menu entries**, "Advanced settings of a target" and
  "Advanced settings of a person", plus one checkbox on the step that shows
  the `alert:` snippet. A menu entry is a step id in Home Assistant, so each
  needs a picker of its own.
- **One word per concept.** A routing-table row is a **target**, in every
  user-facing string, every repair, every error message and every document, in
  English, French and Spanish. "Rule" survives only as *presence rule*. The
  `target:` field of a `notify.switchboard` call is spelled "the notify
  `target` list" where the two meanings meet.
- **The `ttl_minutes` defaults are documented defaults, not frozen values.**
  `info` 120, `normal` 720, `high` none are unchanged and stay where they are;
  what changes is their status — a minor version may pick other numbers, and
  no caller may rely on a particular one. The mechanism (the option, the
  per-call override, the meaning of `null` and of `0`) stays frozen.
- **An absent `wake_time` now means "until the silence ends", not "drop it"** —
  narrowly. A silenced person with no wake time is **deferred** when one of
  their configured silence entities publishes its own end; in core 2026.9.1
  that means a `schedule.*` and its `next_event` attribute. That instant arms
  the fallback timer, bounds the setup catch-up and is what `explain` reports
  as `until`. A silence that publishes no end — an `input_boolean`, a
  Companion Focus sensor, a temporary `notify_switchboard.silence` — still
  drops with reason `silenced`, exactly as in 0.1 → 0.5, so no installation
  that has left the field empty since 0.1.0 changes behaviour.

### Fixed

- **A deferral without a wake time no longer loses its timer when a temporary
  silence outlives the night.** The fallback timer introduced above was armed
  on the end the person's configured silence published, and on nothing else.
  A `notify_switchboard.silence` asked for after the message was queued can
  end later than that: the flush at the schedule's end held the message,
  correctly, and the re-arm that followed read a schedule that had just gone
  `off` and published nothing, so no timer was left at all. The queue then
  waited for the next night to end, which for a message with a time to live
  usually means it never arrived. Both instants are now weighed together, the
  way the wake-time branch already weighed them.
- **`notify_switchboard.unsilence` releases the queue it frees.** The service
  lifted the silence, cancelled its expiry timer and stopped there, while the
  deferral timer stayed armed on that same, now meaningless, expiry: a message
  the silence alone was holding went out at the end of the quiet that had just
  been cancelled by hand — or, when the wake time was the earlier candidate,
  not until the next morning. `unsilence` now reads the queue the way ADR-0019
  §4 reads a configured silence going `off`: nothing else holding it, flush on
  the spot; a night still on, re-arm on the end that is left.
- **A re-arm never targets an instant that has already passed.** A timer
  firing exactly at a schedule's `next_event` can run before that schedule's
  own state write lands, and `async_track_point_in_time` does not refuse a
  point in the past — it fires on the next pass of the loop. Arming on the end
  that has just passed had the flush and the re-arm chase each other.
- **The `alert:` block shown after saving an observer-mode target no longer
  names `notifiers:`.** Observer mode *is* the router watching the alert
  itself; the block it needs has no `notifiers:` list, as `README.md` has
  always said. Emitting one wired the row both ways at once — the alert
  calling the router on every `repeat`, and the router routing the same
  transition on its own — so pasting the block as instructed produced
  duplicated notifications. The step now also says which of the two wirings
  the block it is showing follows.
- **`default_data` is redacted in a diagnostics dump with core's own
  `REDACTED`.** It was replaced with a bare `REDACTED` while message bodies,
  redacted by `async_redact_data`, read `**REDACTED**`; two spellings in one
  document read as two different things.

### Removed

- **The `class` key of a routing-table row.** It was asked for on every target
  since 0.1.0 and read by nothing: `parse_target` copied it into
  `TargetConfig.target_class` and no consumer existed. Gone from the schema,
  the strings, the documents and the examples, along with `CONF_CLASS`,
  `ATTR_CLASS` and `DEFAULT_TARGET_CLASS`. A value already stored is
  **ignored** — not read, not migrated, not deleted — and is stripped from the
  routing table a diagnostics dump exposes, so a dead key cannot be mistaken
  in a bug report for something the router reads. There is no store migration.

### Documentation

- **`README.md` gains a Glossary** defining, once each: target, person,
  output, audience, presence rule, silence, snooze, wake time, quiet hours,
  deferral, summary, episode, observer mode. "Quiet hours" is defined as *not
  a concept of this integration* — it is what a silence entity and a wake time
  add up to — because it is the phrase people arrive with. The other documents
  link to it rather than redefining anything.
- **Observer mode is the primary documented path in `README.md`**, as it
  already was in the quickstart; the `notifiers:` example comes second.
- **One duration claim: about ten minutes**, in the quickstart's title, in
  `README.md`'s documentation list and — as the suite S7 acceptance criterion
  it has always been — in `docs/ARCHITECTURE.md`. The quickstart says what the
  ten minutes include (the YAML and the restart) and that the figure is an
  estimate read off those steps, not a stopwatch reading: nobody has timed it.
- **`docs/migration-guide.md`** (new): where to start when you already have N
  inline `notify.mobile_app_*` calls and M `alert:` blocks. One target per
  alert, the `default` target first, observer mode so nothing in the YAML has
  to change, `explain` to check a target before trusting it, and a rollback
  that is one menu action.
- **`docs/accepted-deviations.md`** (new): the three places where this
  integration knowingly bends one of its own principles — a temporary silence
  the router owns, an episode it persists, `not_in_audience` it does not count
  — each naming the principle it bends and why the maintainer accepted it. The
  known-issues entry that records the visible consequence of the third moved
  with it. Nothing was deleted, and `docs/known-issues.md` points here.
- **`docs/upstream/`** (new): two ready-to-file issue drafts, with core line
  numbers and a runnable reproduction for the first —
  `cancel_on_shutdown` being inoperative for the handles `async_call_later`,
  `async_call_at` and `_TrackPointUTCTime` create, and `AlertEntity` never
  reading its watched entity at startup.
- **`docs/ARCHITECTURE.md`'s roadmap is rewritten** to the decided sequence:
  0.6.0 consolidation, 0.7.0 escalation and places reduced in scope, then —
  unscheduled — labels, a per-target authentication override, intents and the
  routing table as an entity. No line anywhere still says a feature is planned
  for a sprint that no longer covers it.
- **The Glossary says what the code does.** *Snooze* records that the action
  without a `person` snoozes the target's whole audience; *Deferral* records
  that it takes one of the person's **own** silence entities, a temporary
  `notify_switchboard.silence` alone being dropped rather than deferred.
  `README.md` no longer claims that every word in bold on the page is defined
  there — bold is used for emphasis all over it — and names the vocabulary it
  means instead.
- **The known-issues entry moved to `accepted-deviations.md` is a pointer, not
  a copy.** It had been left behind in full, so the same paragraph was
  maintained in two places.
- **The upstream drafts are honest about what they are.** Both "possible fix"
  blocks say they are untested sketches; the `alert` one shows the line that
  has to store the watched entity id first, because `AlertEntity` never keeps
  it; and `async_call_at` is cited at its real line.
- **`docs/migration-guide.md`** says that emptying a `notifiers:` list needs a
  restart — `alert` ships no reload action — and explains the nested `data:`
  in its first example rather than leaving it to look like a typo.
- **`docs/fr/doctrine.md` carries a header saying it is a snapshot** written
  before 0.6.0, where *classe* still exists and a routing-table row is called a
  *ligne*. It is not maintained; `docs/contract.md` and the Glossary are.
- **`target_saved` says that ticking its checkbox defers the save** to the next
  form, which is what it does: the target is written when `target_advanced` is
  submitted.

---

Router 0.5.1 — a fix on top of the 0.5.0 notes below, which are in `main` but
not tagged. No public name, option, event type or drop reason changes.

### Fixed

- **A key the router adds no longer reaches outputs that cannot read it.**
  0.5.0 wrote the default `data.tag` onto the shared payload, so **every**
  output of every person received it — a speaker adapter, a Telegram bot, an
  e-mail notifier, none of which have any use for a Companion tag. The router
  is a pure proxy (ADR-0002): an output receives the caller's `data` merged
  with the row's `default_data`, plus only the keys that output reads. The
  default `tag` is now written on `mobile_app_*` outputs and on the bare
  `persistent_notification` (where it is the source of `notification_id`);
  `actions` and `authenticationRequired` stay Companion-only, as they already
  were. A `tag` **the caller** set is the caller's own key and still reaches
  every output.

  This was not cosmetic. The sibling adapters of this suite refuse an unknown
  `data` key by design — AirPlay Notifier validates its `data` with a
  voluptuous schema (`PREVENT_EXTRA` by default), Assist Satellite Notifier
  checks an explicit `ALLOWED_DATA_KEYS` — and both raise
  `ServiceValidationError` on a refusal, so from 0.5.0 a routing row whose
  person output was `notify.airplay_*` or `notify.satellite_*` failed on every
  single call. Cast Notifier tolerates extra keys, which is why it went
  unnoticed. Everything the router reasons about internally is unchanged: the
  effective tag is still computed for every message, still recorded into the
  episode, still the `(person, target, tag)` de-duplication key, and both the
  Companion clear and the `persistent_notification` dismiss still find their
  notification.

### Documentation

- `docs/ADR/0019-night-catch-up-and-closing-the-loop.md` gains the amendment
  **2026-09-07 (2)** with the rule and its rationale; the v0.5 addendum of
  `docs/contract.md` and its "The default `tag` and `notification_id`" section,
  `docs/ARCHITECTURE.md` and `README.md` say which output each router-added key
  reaches.
- `tests/acceptance/test_s5_output_keys.py` pins it: one message, three
  outputs, three different payloads — and a caller's own `tag` on all three.
- Core already ships a `notify` that speaks: the legacy `platform: tts`
  notify platform (`homeassistant/components/tts/notify.py`) pauses,
  announces and resumes on a Music Assistant player, and interrupts a raw
  Cast player. `README.md`, `docs/quickstart.md` and `docs/fr/doctrine.md`
  now show that five-line recipe for a speaker output instead of implying
  none exists; `docs/ARCHITECTURE.md`'s roadmap marks the sibling
  `notify-cast` / `notify-airplay` rows superseded by it. Assist Satellite
  Notifier is unaffected — `assist_satellite` still has no `notify` platform
  of its own.

---

Router 0.5.0 — night, catch-up and closing the loop (contract v0.5 addendum,
ADR-0019), on top of the router 0.4.0 and 0.3.0 changes further down, which are
in `main` but not tagged either. 0.4.0 made the first hour of use bearable;
this release makes the *night* bearable, and closes what the router opens. Two
new drop reasons, three optional options keys, two `data` keys and one store
migration — no new action, no new event type, no renamed name.

### Added

- **A time to live on a deferred message.** A message held for somebody's wake
  time is a promise that it is *late*, not that it is eternal. Each priority
  now has a life span, counted from the moment the message was queued and read
  **at the flush** rather than frozen at queue time: `info` 120 min, `normal`
  720 min, `high` none, `critical` not applicable (it is never held back). The
  new global option `ttl_minutes` changes the policy, per priority, through a
  **Time to live** step in the options; `data.ttl_minutes` changes it for one
  call, and `data.ttl_minutes: 0` means "keep this one whatever the household
  policy says". A message whose time has run out leaves the queue and is
  dropped with the new reason **`expired`** — counted, evented, in the
  `reasons` attribute — instead of announcing at 07:00 that the front door was
  open at 23:31.
- **One summary at the wake time.** Eleven deferred messages used to be eleven
  notifications, eleven sounds and eleven banners, in a burst, at the exact
  moment somebody opens their eyes. When more than one message survives for a
  person, they now get **one** notification per output: a translated title
  carrying the number of lines, one line per message in queue order, and
  messages sharing a `tag` collapsed to the most recent one, across rows. Its
  `data` is *built*, not merged — `tag: switchboard-summary`, the union of the
  switchboard's own `switchboard_*` keys, and nothing else: no caller key, no
  row default data and **no Companion buttons**, which on a digest of three
  alerts could only acknowledge an arbitrary one of them. The new per-person
  option `summary` (**Summarise the night**, on by default, written into the
  row only when it is off) turns it back into one notification per message. A
  digest is a delivery like any other, so it is recorded into every episode
  that contributed a line to it, under the tag `switchboard-summary`: the
  person a digest woke is told when the alert ends, and the digest is cleared
  with it.
- **Episodes, and a "back to normal" that goes to the right people.** For every
  routing-table row that names an `alert_entity` — in observer mode or not —
  the router now remembers one **episode**: from that alert's `idle → on` to
  its return to `idle`, which persons actually received at least one of its
  messages, which `notify.*` outputs answered, and under which tags. It is
  persisted with the snoozes and the deferrals (`Store` minor version 3 → 4,
  migration inserts an empty list), so a restart in the middle of a leak does
  not widen the done message. A **done** message — observer mode's own, or any
  call carrying the new documented key **`data.switchboard_done: true`** —
  reaches only those persons; everybody else in the audience is dropped with
  the new reason **`not_notified`**. A row with no `alert_entity` has no
  episodes, so the key changes nothing there.
- **Every message has a name, so a notification can be replaced and cleared.**
  `data.tag` now defaults to `switchboard-<slug>`, `switchboard-<slug>-done`
  for a done message and `switchboard-summary` for a digest; a caller's own tag
  always wins. `data.notification_id` mirrors the effective tag and is added
  for the bare `persistent_notification` output only — the one core documents
  as reading it (`homeassistant/components/notify/__init__.py`, the
  `persistent_notification` service handler) — so a repeat updates the
  dashboard notification instead of stacking a second one.
- **Closing the loop when an episode ends.** After the done message has gone
  out, every `mobile_app_*` output the episode reached is called with
  `message: clear_notification` and the episode's tag (core's own literal,
  `homeassistant/components/mobile_app/const.py`, `CLEAR_NOTIFICATION`; the
  Companion app on the device is what removes the notification), and
  `persistent_notification.dismiss` is called for the matching id when that
  output was reached. The done message keeps a tag of its own so it survives
  that clear; the new optional row key **`clear_done`** (**Clear the
  back-to-normal message**, off by default) extends the clear to it. A clear is
  **not a message**: it is not counted, it fires no `event.switchboard_delivery`,
  no routing rule applies to it, it is bounded by the same
  `OUTPUT_TIMEOUT_SECONDS` as any other output call, and a failure is logged
  and swallowed. The whole closing sequence is **observer mode only**
  (ADR-0019 §6, amendment (a)): a row driven by its alert's own `notifiers:`
  list sends its "back to normal" before the state reaches `idle`, so clearing
  there would wipe the message that just arrived. Nothing else narrows it — in
  particular the clear does not ask what wrote the `alert.*` state.

### Changed

- **A flush re-runs the whole decision, not just the silence.** Until 0.4.0 a
  queued message re-checked exactly one thing before going out
  (`docs/known-issues.md`, 2026-09-07). From 0.5.0 the flush runs the same
  `router.decide` an inbound call runs, over the world as it is at that moment,
  with the message's **original** priority written back into the rebuilt
  request — so a row whose `default_priority` changed overnight cannot silently
  re-grade it. Somebody who left the house under a `home_only` row is dropped
  with `presence`, somebody who snoozed the row at 02:00 with `snoozed`,
  somebody whose row was deleted with `unknown_target`. `silenced` is the one
  outcome that still **holds** the message and re-arms the flush: the night is
  not over, which is the whole point of a deferral.
- **The night ends when it ends.** The router was already subscribed to every
  person's configured `silence_entities`; it refreshed a binary sensor and
  returned. Now, when the **last** active one turns `off` and no temporary
  `notify_switchboard.silence` is running, that person's queue is flushed on
  the spot, through the same code path (so the time to live, the re-decision
  and the summary all apply). `wake_time` stays the upper bound: nothing waits
  longer than it used to. A person with a night schedule *and* a Focus sensor
  needs both off — one of two lifting is not the end of a night.
- Both entry points into a flush now go through a task of the config entry's
  own, so a flush never runs inside the timer sweep or the state write that
  triggered it. Unloading the entry **waits** for that task rather than
  cancelling it — `_async_process_on_unload` cancels only `_background_tasks`
  and gives `_tasks` ten seconds — which is what a flush wants, since it takes
  messages out of the store before delivering them and saves once at the end. A
  flush that has not begun by then stands down instead of running against
  listeners that are already detached, and nothing re-arms a deferral timer
  past that point.
- **A flush is visible in the diagnostics.** Every message a flush re-decides
  now writes its own `decision_log` entry, in the shape an inbound call writes,
  with `flush: true` to tell the two decisions on the same message apart; a
  message still held by the silence appears there too. And a refusal that comes
  back *beside* a delivery — `recursion`, when one of a person's outputs is a
  `notify.switchboard*` service — is counted at the flush as it always was on
  the live path, instead of being discarded with the rest of the decision.
- The router subscribes to **every row's** `alert_entity`, not only to the
  observed ones, because every such row has episodes. Only the *routing* half
  of the handler is still reserved to observer mode.
- `sensor.switchboard_dropped_today` gains `expired` and `not_notified` in its
  `reasons`; the four `event.switchboard_delivery` event types are unchanged
  and both new reasons travel in the existing `dropped` event.
- `strings.json` and `translations/{en,fr,es}.json` gain the summary strings
  (`common.summary_title` with its `{count}`, `common.summary_line`,
  `common.summary_line_untitled`), a `detail` sentence for each new reason, and
  the three new options fields.
- The options flow's working copy is built key by key rather than copied, so
  every optional key has to be named in it: `ttl_minutes`, new in this version,
  is carried through explicitly, and an unrelated edit — a person's outputs, a
  row's audience — cannot drop the household's expiry policy. (Nothing shipped
  ever lost it: there was no `ttl_minutes` to lose before 0.5.0.)

### Documentation

- `docs/ADR/0019-night-catch-up-and-closing-the-loop.md`, the v0.5 addendum of
  `docs/contract.md`, and `tests/acceptance/test_s5_*.py`.
- `docs/ARCHITECTURE.md`: the deferral lifecycle is redrawn with two entry
  points and four outcomes, and gains a section on episodes and the clears.
- `README.md`: "The night", "Closing the loop", and a table of every `data` key
  a caller can set.
- `docs/blueprints.md`: how to mark a "back to normal" message with
  `switchboard_done` (the blueprints themselves are unchanged).
- `docs/known-issues.md`: the 2026-09-07 S2 entry is resolved in both halves,
  and one new entry records what Sprint 5 could not close — an episode left
  open across a real Home Assistant restart, because core's `AlertEntity` never
  re-reads its watched entity (ADR-0019 §6, amendment (d)).

---

Router 0.4.0 — zero-config and explainability (contract v0.4 addendum,
ADR-0018), on top of the router 0.3.0 changes further down, which are in `main`
but not tagged either. Every feature here is discovery, defaults and diagnosis
over the decision engine 0.1.0 already had: no new routing semantics, no new
event type, no new drop reason, and one optional routing-table row key.

### Added

- **`notify_switchboard.explain`, a sixth and read-only action.** Declared
  `SupportsResponse.ONLY`, so it must be called with `return_response`. Given a
  `target` (and optionally a `priority` and a `person`) it answers, per person:
  `decision` (`routed` / `deferred` / `dropped`), the ISO `until` of a
  deferral, the `reason` of a drop, a **translated `detail`** naming what
  actually decided — which silence entity is on, when the snooze lifts, the
  presence rule against the person's current state — and the `notify.*`
  services the message would reach (`outputs`) or that are configured but not
  registered (`missing_outputs`). It is a pure evaluation: no notification is
  sent, no counter moves, no `event.switchboard_delivery` fires, no deferral is
  queued and nothing is persisted. A known person who is simply not in the
  row's audience is answered (`dropped` / `not_in_audience`) rather than
  refused; an unknown target or person raises `ServiceValidationError` with the
  existing translation keys, and with no loaded entry it raises
  `no_loaded_entry` like the other five. Declared in `services.yaml` with
  `en`/`fr`/`es` translations like the other five, so Developer tools > Actions
  generates its field editor.
- **Companion outputs are discovered, labelled and pre-selected.** The person
  editor's `outputs` field is now a multi-select of the instance's own
  `notify.*` services instead of free text. The push services of the phones
  registered to *that person's* Home Assistant user come first, carry a
  translated "this person's device" marker, and are pre-selected for a new
  person. The link is exact — the `user_id` a `mobile_app` config entry stores
  against the `user_id` a `person.*` publishes — never a guess from a name. A
  service that does not exist yet can still be typed (`custom_value`), which is
  the 0.1 behaviour this replaces.
- **iOS Focus sensors are proposed as silence entities.** For a new person, the
  `binary_sensor` entities of their own Companion registrations whose entity id
  or translation key contains `focus`. Android's Do Not Disturb is deliberately
  not proposed (it is a `sensor` with several string states); `docs/quickstart.md`
  now carries the one-line template `binary_sensor` that bridges it.
- **A managed `default` row, so a fresh install works after one form.** The
  first person added to an **empty** routing table also creates a row —
  translated name, class `general`, priority `normal`, presence `always`, that
  person as its audience, flagged `managed` — and points `default_target` at
  it. `notify.switchboard` therefore reaches a real phone as soon as one person
  with one output exists. While the flag is true the row's audience is every
  configured person, so a second person joins it automatically. **Submitting
  the row editor for that row — any field — clears `managed` permanently**, and
  nothing ever sets it back.
- **Two consistency repairs**, both `warning`, both not fixable from the repair
  itself, both translated and both deleted when their cause disappears:
  `person_without_outputs` (a person in the audience of at least one row with
  no notify service at all — until now they were dropped with `no_outputs` on
  every message, silently and for ever) and `alert_entity_missing` (a row tied
  to an `alert.*` that is not in the state machine
  `dispatcher.ALERT_ENTITY_GRACE_SECONDS` — 60 s — after the entry was set up;
  not at setup, where the `alert` component may simply not have loaded yet).
- **"Test a person" / "Test a target" in the options menu.** Each sends one
  *real* message through the ordinary routing path — counted, evented, deferred
  or dropped like any other — carrying the public `data.tag: switchboard-test`,
  and then shows the `explain` answer for that same call in the step
  description. A real message rather than a dry run is the point: it proves the
  *output* works, which `explain` cannot.
- **The `alert:` snippet, on a new confirmation step.** Saving a routing-table
  row now ends on `target_saved`, which shows a ready-to-paste `alert:` block
  keyed on the row's own alert (or its slug), with `notifiers:
  [switchboard_<slug>]`, a `state:`, a `repeat:` example and an obvious
  `entity_id:` placeholder. Nothing is written to the options until that step is
  submitted.

### Changed

- **The person editor is two steps**, `person` (pick the `person.*`) then
  `person_outputs` (services, silence entities, wake time). A form cannot react
  to a field it is showing, so pre-selecting somebody's phones requires the
  person to have been chosen earlier. `Edit a person` picks the row and opens
  `person_outputs` directly, still on the **stored** values: discovery never
  silently re-adds an output somebody removed. The stored options shape is
  unchanged.
- **`managed` is a new optional routing-table row key**, and the only options
  change of 0.4. Absent means false, so every row written by 0.1–0.3 behaves
  exactly as it does today and no storage migration is needed.
- **Documentation rewritten around the zero-config path**: `docs/quickstart.md`
  now opens on "add the integration, add one person, you are done", with the
  `alert:` block, the test steps and `explain` after it; `README.md` gains My
  Home Assistant buttons for HACS and for the config flow.

---

Router 0.3.0 — debts and robustness (contract v0.3 addendum, ADR-0017). No new
user-facing concept: no TTL, no summary, no escalation, no new option key.

### Added

- **Translated entity names, frozen entity ids.** Every entity of the
  integration is now named through an `entity.<platform>.<key>.name` string in
  `strings.json` and in `translations/{en,fr,es}.json`, so a French or Spanish
  instance reads French or Spanish names. The **entity ids do not change, in
  any language** — `binary_sensor.<person>_silenced`,
  `sensor.<person>_last_notification`, `sensor.<person>_active_snoozes`,
  `sensor.switchboard_routed_today`, `sensor.switchboard_dropped_today`,
  `sensor.switchboard_deferred_today` and `event.switchboard_delivery` stay
  exactly as documented, so no `alert:`, automation or card breaks. This is not
  automatic: `fr` and `es` are `NATIVE_ENTITY_IDS` languages, on which core
  builds object ids out of the *localized* name, which is why the ids are
  pinned explicitly (see `custom_components/notify_switchboard/entity.py`).
- **`sensor.switchboard_deferred_today` is a frozen public name.** It has
  existed in code since 0.1.0; it now sits in `docs/contract.md` next to its
  two siblings and is pinned by the contract test. Nothing about the entity
  changes.
- **A `person_without_user_id` repair.** Raised once per person who is in the
  audience of a row that adds Companion buttons (`allow_acknowledge`, or a
  non-empty `snooze_minutes`) and whose `person.*` is not linked to a Home
  Assistant user — the link Notify Switchboard needs to tell *who* pressed a
  button. Severity warning, not fixable from the repair itself (the link is
  made in Settings → People), translated, and deleted on the next reload once
  the link exists.

### Changed

- **Fan-out is parallel and bounded.** Every (person, output) delivery of one
  routing decision is now attempted concurrently, each wrapped in a 30 second
  per-output timeout (`dispatcher.OUTPUT_TIMEOUT_SECONDS`). A phone that is off
  the network no longer holds back everybody else's notification, and the wall
  time of a decision is bounded by its slowest single output rather than by the
  sum of them all. A timed-out or failing output is accounted for exactly as a
  failed delivery already was: same repair, same `delivery_failed` drop reason
  when *every* output of a person failed, same counter, same `dropped` event.
  No new drop reason and no new event type. The **order** of the resulting
  `event.switchboard_delivery` events is now explicitly not promised; the
  counts and the per-person outcomes still are.
- **`person.user_id` is the canonical link for Companion callbacks.** A
  callback whose `context.user_id` matches a `person.*` is attributed to that
  person, whatever the event's `device_id` says. The `device_id` lookup remains
  as a fallback only and is logged at DEBUG as such; it has still never been
  observed on a real device (`docs/known-issues.md`).
- **The five `notify_switchboard.*` actions are registered in `async_setup`**
  (quality-scale rule `action-setup`) and therefore exist whether or not a
  config entry is loaded. An automation that names one of them no longer fails
  its own validation at startup with "action not found" because an entry
  happened to be unloaded. Called while no entry is loaded, each raises a
  translated `ServiceValidationError` (`no_loaded_entry`). Unloading an entry
  removes their ability to act, not the actions themselves.
- **`quality_scale.yaml` tells the truth.** Every rule of every tier is
  assessed: `action-setup`, `docs-actions`, `entity-translations` and `brands`
  become `done`, and silver, gold and platinum are assessed rather than left
  out.

### Fixed

- **A lingering midnight timer when Home Assistant stops.** Config entries are
  not unloaded on shutdown, so nothing ran the switchboard's teardown: the
  daily counter reset armed by `async_track_time_change`, the
  `mobile_app_notification_action` bus listener and the state trackers all
  stayed attached to a loop that was going away. `EVENT_HOMEASSISTANT_STOP` now
  detaches everything, not just the deferral and silence timers. This was
  visible as an intermittent "Lingering timer after test …
  `Switchboard._async_reset_counters`" in the config-flow tests.
- **An ERROR with a traceback at every shutdown.** The teardown above kept the
  `EVENT_HOMEASSISTANT_STOP` unsub in the same list as the others and called it
  again from `async_shutdown`, after core's one-time listener had already
  removed it — so every single stop logged "Unable to remove unknown job
  listener" with a `ValueError`. The stop unsub now has its own slot and is
  called exactly once, whichever of the two paths runs.
- **`unknown_target` and `missing_output` repairs that never went away.** The
  issue registry is persisted and neither of those two was ever deleted, so the
  warning outlived the very change it asked for. Creating the missing routing
  row now clears its `unknown_target` repair on the reload; an output clears
  its `missing_output` repair on the first call that succeeds — restart or
  not, the deletion no longer depends on an in-memory counter — or when it is
  removed from every person's outputs.
- **A person lost from the counters.** When one person's delivery raised an
  unexpected error, the fan-out logged it and moved on without counting that
  person at all — neither routed nor dropped. It is now counted as
  `delivery_failed`, the same as any other delivery that reached nobody.
- **Per-person devices are named after the person.** The virtual device used
  the person's object_id titled (`person.alice` → "Alice"), ignoring the
  friendly name a user set in the UI ("Alice Martin"). It now reads the
  `friendly_name` attribute, falling back to the old titled form when there is
  none — or no state at all yet.
- **`quality_scale.yaml` parses.** One unquoted comment containing ": " made
  the whole self-assessment file invalid YAML. A unit test now parses it and
  checks it assesses exactly hassfest's rule set for 2026.9.1.

### Documentation

- `docs/contract.md` gains a "v0.3 addendum (ADR-0017)" block; ADR-0017 records
  the four decisions and the one non-guarantee.
- The `done_message` fallback order is stated identically everywhere it appears
  (`docs/contract.md` is authoritative): the row's `done_message` template, then
  the alert's own `done_message` attribute, then the translated
  `common.back_to_normal`. `tests/acceptance/README.md` and
  `docs/sprints/sprint-2-brief.md`, which had it backwards, are corrected;
  `tests/acceptance/test_s3_done_message.py` pins it.
- `docs/known-issues.md`: the two entries this release resolves are removed, and
  one is added about what `Entity.suggested_object_id` actually does in core
  2026.9.1.
- `README.md` no longer says the quickstart and the blueprints are planned, and
  links `docs/how-this-is-built.md`.

## [0.2.0] - 2026-09-07

Router 0.2.0 — UI services (contract v0.2 addendum, ADR-0016).

### Added

- **Five `notify_switchboard.*` services** for callers that are not a
  Companion push notification — a card, a script, an automation:
  `acknowledge`, `snooze`, `unsnooze`, `silence`, `unsilence`. They reuse the
  Companion code paths and differ in one respect only: a service call has a
  caller, so a refused or invalid call raises a `ServiceValidationError` with a
  translated message instead of being logged and swallowed. `acknowledge`
  keeps the ADR-0009 allow-list; `snooze` additionally refuses a duration the
  row does not offer, and an explicit `person` outside the row's audience.
  Declared in `services.yaml`, with `en`/`fr`/`es` translations under
  `services` and `exceptions`.
- **Temporary, person-wide silence** (`silence` / `unsilence`), a second and
  independent source of silence the router owns: the person's configured
  `silence_entities` are still read, never touched. It is persisted in the
  same `Store` as snoozes (minor version 3, migrated), shows up in
  `binary_sensor.<person>_silenced` (with an `until` attribute while it runs),
  drops routing with the existing `silenced` reason, is bypassed by
  `priority: critical`, and expires both lazily and on its own timer — so the
  sensor goes back to `off` at the right minute, not at the next notification.
  `minutes` must be between 1 and 1440 (a day): anything outside that raises a
  translated `ServiceValidationError`, including the values large enough to make
  `datetime` arithmetic overflow. `unsilence` on somebody who is not silenced is
  a no-op, not an error.
- **Three optional per-row texts**: `message` and `done_message`, templates
  rendered with the row's alert's current state exposed as `alert`, and
  `default_title`, used as the outgoing title whenever the caller gave none —
  including every message observer mode generates. All three default to
  absent, so a routing table written for 0.1.0 behaves exactly as it did.
  This resolves the known-issues entry "a real `alert.*` never exposes
  `message` or `done_message`": the row, not the alert, is now the documented
  source of observer-mode text.
- **A `repairs` issue** when the same unknown target or unusable person has
  been refused by a service three times — a card left pointing at a renamed
  row, the counterpart of `MAX_CONSECUTIVE_OUTPUT_MISSES`. The count is
  **cumulative, not consecutive**: three refusals a week apart raise the issue
  just as three in a row do, because a card wired to a stale slug fires whenever
  somebody taps it rather than in bursts. It is reset — and the issue deleted —
  when that slug or person is accepted again, and at setup for everything the
  reloaded routing table now knows about, so fixing the cause in the options
  flow makes the warning go away. At most 20 distinct bad values get an issue
  of their own; past that a single `invalid_service_calls_many` stands for the
  rest, so a caller generating a fresh bad value every time cannot fill the
  (persisted) issue registry.

### Changed

- `binary_sensor.<person>_silenced` is now true when **either** silence source
  is active. Its `sources` attribute keeps its 0.1.0 meaning (the configured
  entities).
- Observer mode's `idle -> on` text order is now: the alert's own `message`
  attribute, the row's `message` template, the row's name. Its
  `on|off -> idle` order is: the row's `done_message` template, the alert's
  own `done_message` attribute, the translated `common.back_to_normal`
  (contract §"Per-row texts" and ADR-0016 §3 both put the row first here).
  Absent the new fields, both chains end exactly where 0.1.0 ended.
- A message silenced only by a temporary silence is dropped with reason
  `silenced` rather than deferred: `wake_time` is documented as the end of the
  *night* silence, and queueing an hour of requested quiet until tomorrow
  morning would be the wrong kind of late. A configured night silence still
  defers, even when a temporary silence is running on top of it.
- The routing-table options flow gained the three new text fields; the two
  template fields use a `TemplateSelector`, which refuses unparsable Jinja.
- **The options flow no longer forgets the row it is editing.** Two new menu
  entries, `Edit a person` and `Edit a target`, pick a row and open its form
  pre-filled with what is stored; a validation error now hands back what was
  typed instead of an empty form. The step writes the whole row, so opening it
  to change one word of `message` used to reset `done_message`,
  `default_title`, `snooze_minutes` and `default_data` to their defaults on
  submit.
- **A deferred message re-checks the silence before going out.** `wake_time` is
  a prediction that the night is over, not a promise: a schedule running late,
  a `notify_switchboard.silence` set in the small hours or a restart spanning
  the night used to push the whole queue at somebody still asleep. A
  still-silenced message stays queued and the flush is re-armed for whichever
  comes first, the end of the temporary silence or the next wake time.
  `critical` is delivered regardless. The rest of the routing decision is still
  not re-run (`docs/known-issues.md`).
- **Acknowledging carries the caller's context**, so the logbook credits the
  person who tapped the card or the Companion button rather than the
  integration. `alert.turn_off` gets a *child* of that context on purpose:
  core treats a non-empty `context.user_id` on an entity service call as an
  authorisation claim, and the row's ADR-0009 allow-list — not the caller's
  entity permissions — is what decides here. The `acknowledged` and `snoozed`
  `event.switchboard_delivery` events carry the caller's own context.
- Diagnostics now report the temporary `silences` alongside the snoozes and the
  deferrals. The three per-row texts stay unredacted: they are configuration
  the user typed, and it is their *rendered* output that is redacted.
- A temporary silence that expired while the entry was unloaded is now written
  back to the store when it is purged at setup, instead of only being dropped
  from memory.

### Known limitations

Added to [`docs/known-issues.md`](docs/known-issues.md); everything listed
under 0.1.0 that is still open stays open.

- The five services are **callable by any Home Assistant user, by design**.
  The wall tablet runs under a non-admin account and its cards are the main
  caller; what bounds them is the ADR-0009 allow-list, not the caller's role.
  `context.user_id` is logged and carried in the `acknowledged`/`snoozed`
  events, and Companion buttons keep `authenticationRequired` on `high` and
  `critical` rows. Revisit if a household needs it — the shape would be a
  per-row flag, not a restriction on the whole domain.
- A deferral re-checks the person's silence at flush time but **not** the rest
  of the routing decision: somebody who left the audience, went away under a
  `home_only` rule or snoozed the row since still receives their queued
  message.

## [0.1.0] - 2026-09-07

### Added

- **Routing table** in the options flow: people (their `notify.*` outputs,
  their silence entities, their wake time) and targets (slug, name, class,
  default priority, linked `alert.*`, audience, presence rule, acknowledgement,
  snooze durations, default data, observer mode), validated as a whole before
  anything is written.
- **Per-target legacy services**: `notify.switchboard_<slug>` for every row,
  alongside `notify.switchboard`, so an `alert` can name its row in
  `notifiers:`.
- **Decision engine** (`router.py`, pure functions): audience, presence rule,
  silence, active snooze, `critical` bypass, recursion rejection. Every drop
  carries a reason (`not_in_audience`, `unknown_person`, `presence`,
  `silenced`, `snoozed`, `recursion`, `unknown_target`, `no_outputs`,
  `delivery_failed`); only `not_in_audience` is left out of the daily count.
- **Companion buttons**: `Acknowledge` when the row has an alert and allows it,
  one `Snooze <n>` per configured duration, labels translated through the new
  `common` section, `authenticationRequired` on `high` and `critical` rows.
- **Companion callbacks**: acknowledging turns off the row's alert only when
  that alert is in the routing table (allow-list, refusals logged with
  `context.user_id`); snoozing stores `(person, target) -> expiry` in `Store`
  and survives a restart.
- **Night deferral**: a message silenced while the person is asleep is queued
  (latest wins per `tag`) and delivered at their wake time, correctly across
  midnight and across a DST change. A deferral whose wake time passed while
  Home Assistant was down is delivered at the next start, not a day later.
- **Observer mode**: watch a row's `alert.*` and route on `idle -> on` and
  `-> idle`, without being listed as a notifier.
- **Entities** of contract §3.5: `binary_sensor.<person>_silenced`,
  `sensor.<person>_last_notification`, `sensor.<person>_active_snoozes`,
  `sensor.switchboard_routed_today`, `sensor.switchboard_dropped_today` (with
  a `reasons` attribute), `event.switchboard_delivery`, plus the additional
  `sensor.switchboard_deferred_today` (attribute `queued`) so a queued night
  is not indistinguishable from a quiet one. Counters reset at local midnight
  and declare `last_reset`.
- **Repairs**: one issue for an unknown target, one for an output that has
  been unusable — missing, or raising on every call — for more than three
  consecutive calls.
- **Diagnostics** with `async_redact_data` on message bodies and every
  `default_data` value redacted (keys kept), plus the table, the snoozes, the
  deferrals and the last twenty decisions.
- `async_migrate_entry`, `async_remove_entry` (which deletes the stored
  document) and `ConfigEntry.version = 1` / `minor_version = 1`.
- Translations extended to the whole options flow, the repairs and the
  router-added labels, in `en`, `fr` and `es`.

### Changed

- The `NotifyEntity` is now explicitly the degraded path: it routes to the
  default row with priority `normal`.
- The legacy notify service is registered directly instead of through
  `discovery.async_load_platform`, so it survives a config entry reload.
- Options are no longer a flat `default_targets` list; the entry now stores
  `persons`, `targets` and `default_target`.

### Removed

- The pass-through `Router` of the scaffold.

### Upgrading from 0.0.1

The `NotifyEntity` unique_id changed. Setting the entry up now removes the
registry row left by the old scheme, so `notify.switchboard` is reused instead
of the entry appearing as an `unavailable` `notify.switchboard` plus a live
`notify.switchboard_2`. Nothing to do by hand.

### Known limitations

Detailed in [`docs/known-issues.md`](docs/known-issues.md):

- entity display names are hard-coded in English (their translation is
  planned; only the router-added button labels are translated today);
- `authenticationRequired` is derived from the row's priority and cannot be
  overridden per row;
- the options flow edits one person or one target per step;
- core's `alert` exposes neither `message` nor `done_message` as a state
  attribute, so observer mode always uses its fallbacks, and `alert.turn_off`
  does not cancel the repeat timer (both to be raised upstream);
- the Companion `device_id` path of the snooze callback has not been verified
  against a real device; `context.user_id` is tried first and does not depend
  on it.

[Unreleased]: https://github.com/amiel-35/notify-switchboard/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/amiel-35/notify-switchboard/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/amiel-35/notify-switchboard/compare/v0.0.1...v0.1.0
