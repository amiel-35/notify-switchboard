# ADR 0020: Consolidation — a five-field target, an optional wake time, one vocabulary, and documents that tell the truth

Date: 2026-09-07

## Status

Accepted.

## Context

0.1 → 0.5.1 added a routing decision, six services, three diagnostic sensors,
three per-person entities, per-row texts, discovery, a managed default row,
`explain`, a time to live, a wake-time summary, episodes and cleared
notifications. Every one of those was justified by its own ADR. Nobody ever
subtracted anything.

An independent product review of the result counted what a newcomer has to
meet before their first message is delivered: **about twenty-eight concepts,
and fifteen fields on the first form they are shown**. The routing table row
editor asks for a slug, a name, a class, a default priority, an alert, an
audience, a presence rule, an acknowledgement flag, a list of snooze
durations, a default `data` object, an observer-mode flag, two Jinja
templates, a default title and a "clear the back-to-normal message" flag —
in one screen, before anything has ever been routed. Twelve of those fifteen
have a default that is right for almost everybody.

The review also found three smaller things that cost more than they look:

- One of the fifteen fields, `class`, is **read by nothing**. `parse_target`
  copies it into `TargetConfig.target_class` and no consumer exists: not the
  decision, not `explain`, not a sensor, not a service, not a card. It has
  been asked for on every row since 0.1.0 and answered for nobody.
- The documents disagree with each other and with the code. `docs/quickstart.md`
  is titled "in five minutes"; `README.md` links to it as "route your first
  alert in ten minutes"; `docs/ARCHITECTURE.md`'s suite S7 row promises "an
  external user routes an alert in 10 minutes". The router roadmap still says
  "Router S6 — Escalation … Planned", which is no longer what S6 is.
- The same object is called a *row*, a *rule*, a *routing-table row*, a
  *target* and — in the legacy `notify` service's own `target:` field — a
  *target list of targets*. `strings.json` alone uses "row" eleven times for
  the thing the menu calls a target.

None of that is a bug. All of it is the reason a household that installs this
integration does not finish installing it.

The maintainer's decision after the review was explicit: **stop adding,
consolidate**. 0.6.0 introduces no routing semantics, no entity, no service and
no drop reason. It removes a field, splits two forms, settles one word per
concept, and makes the documents match the code.

One thing in this ADR is nevertheless a behaviour change, and it is here on
purpose: making `wake_time` optional is meaningless if leaving it empty
silently turns "hold this until morning" into "drop this". §3 decides what an
absent wake time means, narrowly enough that no installation written against
0.1 → 0.5 changes behaviour.

## Decision

### 1. The target editor is two steps: five fields, then the rest

`async_step_target` — step id **`target`**, public — asks exactly five things,
in this order:

| Field | Selector | Default |
|---|---|---|
| `slug` | `TextSelector` | required |
| `name` | `TextSelector` | required |
| `alert_entity` | `EntitySelector(domain="alert")` | optional, `None` |
| `audience` | `SelectSelector(multiple=True)` | required, `[]` |
| `observer_mode` | `BooleanSelector` | `False` |

That is the whole schema. Nothing else may be added to it without an ADR.

`async_step_target_advanced` — step id **`target_advanced`**, public — holds
everything that was in the same form up to 0.5.1, with **identical selectors
and identical defaults**:

`default_priority` (`normal`), `presence_rule` (`always`), `allow_acknowledge`
(`False`), `snooze_minutes` (`""`), `default_data` (`{}`), `message` (absent),
`done_message` (absent), `default_title` (absent), `clear_done` (`False`).

The five are the smallest set that produces a row which actually routes: an
identity the user chooses (`slug`, `name`), the alert it is about
(`alert_entity`), the people it is for (`audience`), and whether the router
watches that alert itself or waits to be called (`observer_mode`). The nine
others all have a defensible silent default — `normal` priority, `always`
presence, no buttons, no templates — and every one of them is a preference,
not a prerequisite.

`observer_mode` is in the five and not in the advanced list because §6 makes
observer mode the *primary* documented path: a field the README recommends
first cannot live behind a second menu entry.

**Where the advanced step is reached from.** Two ways, and both matter:

- From the options menu, through a new entry labelled "Advanced settings of a
  target", which is the picker step `edit_target_advanced` (a
  `SelectSelector` of slugs) followed by `target_advanced`. A menu entry *is*
  a step id in Home Assistant — `async_show_menu`
  (`$HA_CORE_SRC/homeassistant/data_entry_flow.py` line 878) builds
  `vol.Schema({"next_step_id": vol.In(menu_options)})` at line 894 — so
  offering a labelled menu entry requires a step of its own; it cannot be a
  parameterised call into `target_advanced`.
- Straight after saving a row. `target_saved` keeps its place directly after
  `target` and keeps carrying the `alert:` snippet in
  `description_placeholders` (`async_show_form`,
  `$HA_CORE_SRC/homeassistant/data_entry_flow.py` line 706, placeholder
  argument line 712). Its description gains one sentence naming where the
  advanced settings live, and its schema — empty until now — gains one
  `vol.Optional("advanced", default=False)` boolean. Ticked, the flow
  continues to `target_advanced` for the row just described instead of
  writing and ending; unticked (and `{}` submitted, as every S4 test does),
  nothing changes at all.

**What each step writes.** `target` builds the whole row, as it does today,
filling the nine advanced values from the row being edited when there is one
and from the documented defaults when there is not; `target_saved` writes it,
unchanged from 0.5.1. `target_advanced` writes the row it was opened on with
its nine fields replaced, and **touches none of the five**. Editing the
priority of a row must never be able to reset its audience — that is the
0.2.0 data-loss bug (`docs/known-issues.md`) re-introduced by a split, and
avoiding it is the whole reason the split writes field by field rather than
rebuilding from the form.

`managed` (ADR-0018 §4) is cleared by **either** step: submitting either half
of the editor is the user taking ownership of the row.

### 2. The person editor is two steps as well

`person_outputs` — step id **`person_outputs`**, public — keeps exactly two
fields: `outputs` and `silence_entities`, with the discovery, the ordering,
the "this person's device" marker and the `custom_value` tolerance of
ADR-0018 §2, unchanged.

`person_advanced` — step id **`person_advanced`**, public — holds `wake_time`
(optional, `TimeSelector`) and `summary` (`BooleanSelector`, default `True`),
with their 0.5.1 defaults and their 0.5.1 storage discipline: `summary` is
written only when it is `False`, so a person row edited without opening the
advanced step keeps the exact dict it had.

It is reached from the options menu, through the picker step
`edit_person_advanced` labelled "Advanced settings of a person". Unlike the
target editor there is no confirmation step to hang a shortcut on, and
`person_outputs` does **not** grow a checkbox: it is the one form a first
install has to fill, and it stays at two fields.

The person editor therefore stays `person` → `person_outputs` for a new
person, and `edit_person` → `person_outputs` for an existing one; nothing on
that path changes.

### 3. An absent `wake_time` means "until the silence ends", not "drop it"

Up to 0.5.1, `Switchboard._async_defer` refuses to queue anything for a person
whose `wake_time` is `None`, so a message that arrives while such a person is
silenced is dropped with reason `silenced`. Moving the field into an advanced
step without deciding this would make the common case — a person who never
opens the advanced step — the case where the night silently eats messages.

From 0.6.0:

- **With a `wake_time`:** everything is exactly as in 0.5.1 — deferral until
  the wake time, early flush when the last configured silence lifts
  (ADR-0019 §4), re-decision at the flush (§3), TTL (§1), summary (§2),
  catch-up at setup.
- **Without a `wake_time`,** a message that the silence rule would drop is
  **deferred** instead, and its flush instant is the earliest end published by
  the person's own configured silence entities. In core 2026.9.1 exactly one
  domain publishes such an end: `schedule`, whose entity carries a
  `next_event` state attribute holding the instant the current block finishes
  (`$HA_CORE_SRC/homeassistant/components/schedule/const.py` line 43,
  `ATTR_NEXT_EVENT`; set in
  `$HA_CORE_SRC/homeassistant/components/schedule/__init__.py`, the
  `ScheduleEntityStateAttribute.NEXT_EVENT` entry of the extra state
  attributes). The message is delivered by the existing early flush when that
  schedule turns `off`, and the instant is what arms the fallback timer and
  what `explain` reports as `until`.
- **Without a `wake_time` and with no silence entity that publishes an end** —
  an `input_boolean`, a Companion Focus `binary_sensor`, a temporary
  `notify_switchboard.silence` — nothing changes: the message is dropped with
  reason `silenced`, exactly as in 0.1 → 0.5.

Nothing else moves. No new drop reason, no new `event.switchboard_delivery`
type, no fourth `decision` value; `until` keeps its frozen meaning of a real
instant, which is precisely why the rule is scoped to silences that have one.
The TTL of ADR-0019 §1 applies to these deferrals unchanged, and the setup
catch-up covers them because their flush instant is knowable.

The rule is deliberately narrow. Deferring against *any* silence entity would
queue a message behind an `input_boolean` that may never turn off, with no
upper bound, nothing to put in `until`, and a change of behaviour for every
installation that has left `wake_time` empty since 0.1.0 — which is the
opposite of what a consolidation release is for.

### 4. `class` is removed, and a stored one is ignored

`class` leaves the routing-table row: the `target` schema, `strings.json` and
the three translations, `TargetConfig.target_class`, `parse_target`,
`CONF_CLASS`, `ATTR_CLASS`, `DEFAULT_TARGET_CLASS` (so the bootstrapped
`default` row of ADR-0018 §4 no longer carries `class: "general"`), and every
example in `README.md`, `docs/quickstart.md`, `docs/ARCHITECTURE.md` and
`tests/acceptance/README.md`.

A value already stored is **ignored**: it is not read, not migrated, not
shown, and not deleted. There is no store migration and no options rewrite —
`entry.options` keeps whatever it holds until the user next edits that row,
at which point the row is rebuilt without the key. `diagnostics.py` strips
`class` from every routing-table row it dumps, so a dead key cannot reappear
in a bug report and be mistaken for something the router reads.

Older ADRs (ADR-0018 §4's example row) are historical records and are left as
they were written.

### 5. The TTL defaults are documented defaults, not frozen values

`info` 120, `normal` 720, `high` none stay exactly as they are, and stay
`DEFAULT_TTL_MINUTES` in `const.py`. What changes is their **status**: the
contract's v0.6 addendum classifies them as defaults that a minor version may
change, not as frozen values a caller may rely on. A household that needs a
specific number says so through `entry.options["ttl_minutes"]` or through
`data.ttl_minutes`, both of which are frozen and both of which already exist.

The `ttl` step keeps its own step id and its own menu entry, and keeps
showing the three values in force. Folding it into `general` would put four
fields on a form that has one, which is the shape this release is removing.

### 6. One word per concept, and a glossary that owns it

- A row of the routing table is a **target**, everywhere a user can read the
  word: `strings.json` and the three translations, `README.md`,
  `docs/quickstart.md`, `docs/ARCHITECTURE.md`, `docs/known-issues.md`, every
  `repairs` title and description, every `ServiceValidationError` message.
  Not a *row*, not a *rule*, not a *routing-table row*.
- The legacy `notify.switchboard` service's own `target:` field is **the
  notify `target` list**, spelled that way, mentioned where it has to be
  (`docs/contract.md` §Input, and once in `README.md`) and nowhere else.
- A `person.*` is a **person**. `fr`: *cible* and *personne*; `es`: *destino*
  and *persona* — both already the established words in `translations/`, so
  the work there is removing *ligne* / *fila* and *règle* / *regla*, not
  re-translating.
- `README.md` gains a **Glossary** section defining, once each: target,
  person, output, audience, presence rule, silence, snooze, wake time, quiet
  hours, deferral, summary, episode, observer mode. "Quiet hours" is defined
  as *not a concept of this integration* — it is what a silence entity plus a
  wake time add up to — because it is the phrase people arrive with.
  `docs/quickstart.md`, `docs/ARCHITECTURE.md`, `docs/contract.md` and
  `docs/migration-guide.md` link to it rather than redefining anything.

The word "rule" survives in exactly one place: **presence rule**, the name of
a field. `tests/acceptance/test_s6_vocabulary.py` enforces both halves.

### 7. The documents say what is true

- **One duration claim: ten minutes**, measured on the real path — install,
  add a person, write the `alert:` block, restart, see a notification. The
  quickstart's title, `README.md`'s documentation list and
  `docs/ARCHITECTURE.md`'s suite S7 row all say ten, and the quickstart says
  what the ten minutes include, restart and YAML in.
- **Observer mode is the primary path in `README.md`**, as it already is in
  the quickstart: the router watches the alert, and the `notifiers:` example
  comes second, for a household that would rather drive the router from the
  alert. The five-line core `notify: platform: tts` speaker recipe stays where
  it is.
- **A migration guide**, `docs/migration-guide.md`: where to start when you
  already have N inline `notify.mobile_app_*` calls and M `alert:` blocks —
  one target per alert, the `default` target first, `explain` to check a row
  before trusting it, and a rollback that is one line (remove the target;
  the alert's own `notifiers:` are untouched).
- **`docs/ARCHITECTURE.md`'s roadmaps are rewritten** to the decided sequence:
  router 0.6.0 consolidation (this ADR), 0.7.0 escalation and places, reduced
  in scope; later, and unscheduled: labels, per-row authentication override,
  intents. The suite S3/S4 rows keep their "superseded by core `notify:
  platform: tts` + Music Assistant" marking and no row anywhere still says a
  feature is "planned for S7" that S7 no longer covers.

### 8. Accepted design moves out of "known issues"

`docs/known-issues.md` is for findings that were accepted *instead of being
fixed*. Three of its entries are not findings at all: they describe design the
maintainer chose, which bends a stated doctrine principle for a stated reason.
They move to a new `docs/accepted-deviations.md`, one entry each, naming the
principle bent and why it was accepted:

| Deviation | Principle it bends |
|---|---|
| A temporary `notify_switchboard.silence` is state the **router** owns, rather than an `input_boolean` the user owns | "Native first" (ADR-0001) and "the router is a pure proxy" (ADR-0002) |
| An **episode** is a small persisted record of who was told and on which outputs | ADR-0002 again: a proxy that remembers is no longer only a proxy |
| **`not_in_audience` is not counted** in `sensor.switchboard_dropped_today` | "Nothing is silently lost" (`docs/contract.md` §Routing decision) |

Nothing is deleted. Each moved entry leaves a one-line pointer in
`docs/known-issues.md`, and the known-issues entry that records the *visible
consequence* of the third one — "a flushed deferral can leave the day's
figures short" — moves with it, since it is the same decision seen from the
counters.

### 9. Two upstream issues get a written draft

`docs/upstream/`, English, ready to paste, filed by the maintainer:

1. **`cancel_on_shutdown` is inoperative for the timer handles
   `async_call_later` creates.**
   `HomeAssistant._cancel_cancellable_timers`
   (`$HA_CORE_SRC/homeassistant/core.py` line 1265) only cancels a scheduled
   handle when `type(handle._args[0]) is HassJob` (lines 1270-1272).
   `async_call_later` (`$HA_CORE_SRC/homeassistant/helpers/event.py` line
   1552) schedules `loop.call_at(loop.time() + delay,
   _run_async_call_action, hass, job)` at line 1570, so `args[0]` is the
   `HomeAssistant` object and the flag is never seen; `async_call_at` (line
   1533) has the same shape at line 1548. The same is true of
   `_TrackPointUTCTime.async_attach` (line 1461), which schedules
   `loop.call_at(..., self)` at line 1464, so `args[0]` is the dataclass —
   which is why `AlertEntity._schedule_notify`
   (`$HA_CORE_SRC/homeassistant/components/alert/entity.py` line 132) passes
   `cancel_on_shutdown=True` through `async_track_point_in_time` and still
   leaves a lingering timer. Reproduction: schedule
   `HassJob(cb, cancel_on_shutdown=True)` through `async_call_later`, run
   `_cancel_cancellable_timers`, observe the handle still scheduled.
2. **`AlertEntity` never reads its watched entity's current state.**
   `AlertEntity.__init__`
   (`$HA_CORE_SRC/homeassistant/components/alert/entity.py`, class at line
   30) sets `self._firing = False` (line 71) and subscribes to *future*
   changes with `async_track_state_change_event` (lines 76-78); there is no
   `async_added_to_hass` that reads the watched entity. After a restart, an
   alert whose condition is still true is `idle`. The consequence for a
   long-lived alert, and for anything watching it: no `idle → on` transition
   is ever produced for a condition that never stopped being true, so an
   observer sees the leak as over. Recorded here since 0.5.0
   (`docs/known-issues.md`, "an episode left open across a real Home
   Assistant restart").

### 10. The cards README (separate repository)

Out of this repository's scope and handled by a separate small PR: remove the
"planned for 0.2.0" wording, add a feature matrix by router version (0.2
services, 0.4 `explain`, 0.5 summary tag), and keep saying that `target_map`
and `snooze_minutes` are required until the routing-table entity ships in
0.7.0. Recorded here so the decision is not lost between two repositories.

## Alternatives rejected

**Hide the advanced fields behind a collapsible section of one form.**
Possible in core 2026.9.1: `data_entry_flow.section` with `collapsed: True`
(`homeassistant/data_entry_flow.py`, line 939) groups fields of one form and
folds them by default — the first version of this ADR wrongly said no such
marker existed (corrected 2026-09-07 after the 0.6.0 implementation). Rejected
anyway, for a different reason: a section has no step id, so the cards and the
documentation could not link to "the advanced settings of a target", and the
`target_saved` snippet step would have to sit after a longer form. A second
step *is* the collapsible section here, and it has a public name.

**Keep `class` "for later".** It costs one line to keep and it looks free. It
is not: it is a field on the form this release exists to shorten, a key in the
normative options shape, a translated label and description in three
languages, a column in every documented example, and a question a newcomer has
to answer before they can save anything. A key nothing reads is not a feature
waiting to happen, it is debt with a friendly face. If grouping ever earns its
place it will come back as labels (0.7.0 and after), with a consumer.

**Make an absent `wake_time` defer against any silence entity.** Rejected in
§3: no upper bound, nothing to report as `until`, and a behaviour change for
every installation that has left the field empty.

**Fold the `ttl` step into `general`.** Rejected in §5: it un-does the split
this release is making.

**Rename `target` to something less overloaded.** The word collides with the
legacy `notify` service's own `target:` field, which is a real cost. It is
also a frozen public name in six places — `notify.switchboard_<target>`, the
`target` field of five services, the `target` key of an `explain` response —
and renaming it would be a major version for a vocabulary problem that one
spelled-out phrase ("the notify `target` list") solves.

## Consequences

- **Version 0.6.0**, and a **v0.6 addendum to `docs/contract.md`** — the fifth
  amendment authorized under ADR-0011. It removes `class` from the row keys
  (never a documented input, never read, so its removal is not a break),
  makes `wake_time` optional with the §3 meaning, reclassifies the TTL
  defaults as changeable, and pins `target`, `target_advanced`,
  `person_outputs` and `person_advanced` as public step ids. Everything else
  in the contract is untouched.
- **Public step ids.** Cards and documents link to an options step by id, so
  the four above may not be renamed without an ADR. `edit_target_advanced`
  and `edit_person_advanced` are pickers, not destinations, and stay private.
- **The options menu grows by two entries and the first target form loses
  ten fields.** That is the trade the review asked for: a menu is scanned,
  a form is filled in.
- **`entry.options` shape.** `class` stops being written; nothing else
  changes, and no migration runs. The normative shape in
  `tests/acceptance/README.md` and the `make_target` builder in
  `tests/acceptance/conftest.py` drop it, keeping `klass=` as an explicit
  opt-in so `test_s6_class_removed.py` can still build a legacy row.
- **`strings.json` and `translations/{en,fr,es}.json`** gain the two advanced
  steps, the two picker steps, their menu labels, and the `advanced` field of
  `target_saved`; they lose the `class` label and description; and every
  remaining string that called a target a row or a rule is rewritten.
- **`docs/` gains** `accepted-deviations.md`, `migration-guide.md` and
  `upstream/` (two drafts); `README.md` gains a Glossary; `known-issues.md`
  keeps every entry, marked or pointed elsewhere.
- **No new routing rule, entity, service or drop reason**, with the single,
  scoped exception of §3, which is why §3 is written as narrowly as it is.
- **A future ADR is needed to**: give a target a label or a group (the
  successor of `class`), add escalation or places (0.7.0), expose the routing
  table as an entity, or widen §3 to silences that publish no end.
