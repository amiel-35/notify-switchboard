# ADR 0022: A first alert without code — a derived code name, observer mode by default, a menu in three blocks, a night the user owns, and a confirmation before removal

Date: 2026-10-12

## Status

Accepted (maintainer's go on 2026-10-12, sprint 8).

## Context

0.7.1 rewrote the whole interface in plain language. A second review by a
non-technical reader, on the question "could I configure my first alert
without help?", scored it **4/10**. The people half of the options flow was
fine (6–7/10). The target half was where the reader stopped, and for reasons
that have nothing to do with wording:

- **A code name to invent.** The `target` step opens on `slug`, "Short
  identifier — lowercase letters, no spaces". A reader who has just been told
  they are adding "a water leak" is asked to make up `water_leak` and is
  refused on the first capital letter. The slug is plumbing: it is what
  `notify.switchboard_<slug>` is built from, nothing more.
- **A YAML block to paste, and a restart.** `target_saved` shows an `alert:`
  block whatever was chosen. For a target in observer mode — the recommended
  way, where the router watches the alert itself — the block is not needed at
  all, but it is shown anyway, and it says "then restart Home Assistant".
- **The recommended switch shipped off.** `observer_mode` is described as
  "the recommended way" and defaults to `false`.
- **A menu of thirteen entries**, three of which are "advanced settings of"
  something, in an order that interleaves people, targets and global options.
  Home Assistant menus are flat: there is no separator, no heading, no
  collapsed group (`async_show_menu`, `homeassistant/data_entry_flow.py`).
- **A removal with no "are you sure"**: picking a person in "Remove somebody"
  and submitting deletes them, and removes them from every target's audience,
  in one click.
- **A night that has to be built elsewhere first.** The silence picker offers
  `schedule`, `input_boolean` and `binary_sensor` entities, which presumes the
  reader already made one in **Settings → Helpers**.
- **A wake time with seconds.** `TimeSelector` renders `HH:MM:SS` in the
  frontend; its backend config schema in 2026.9.1 accepts no `no_second`
  option (`homeassistant/helpers/selector.py`, `TimeSelector.CONFIG_SCHEMA =
  make_selector_config_schema()`), so the integration cannot ask for less.
- **Pickers that only say a name.** "Bob" in "Change somebody" does not say
  whether Bob is the one with the iPhone and the night schedule.

None of this changes what the router *does*. Everything in this ADR is in the
options flow, its translations, and one action it can take on the user's
behalf (§5).

## Decision

### 0. Guard-rails, unchanged

- The router stays a pure notify proxy (ADR-0002): nothing here adds a
  `notify.*` call, an outgoing network call, or a dependency.
- No timer and no counter of the router's own (ADR-0021 §0). The night
  schedule of §5 is a core `schedule` entity; core runs its clock, not the
  router.
- No routing rule changes. No service, entity, `data` key, drop reason or
  `event.switchboard_delivery` type is added or removed.
- `STORAGE_VERSION` / `STORAGE_MINOR_VERSION` and the config entry
  `VERSION` / `MINOR_VERSION` do not move: nothing new is persisted by the
  router, and the shape of a stored target or person is unchanged.

### 1. The code name is derived, never typed

The `target` step no longer asks for `slug`. Its fields are, in this order:
`name`, `alert_entity`, `audience`, `observer_mode`.

When a target is **created**, its slug is derived from `name`:
`homeassistant.util.slugify(name)`, then de-duplicated against the slugs
already in the routing table by appending `_2`, `_3`, … — the same rule core's
`IDManager.generate_id` applies to helper ids
(`homeassistant/helpers/collection.py`), so the result reads like every other
id the user has met. A name that slugifies to nothing falls back to `alert`.

After creation the slug is **never renamed by the editor**:

- editing a target goes through an internal step, `target_edit`, that shows
  the slug in a `read_only` text field ("Behind-the-scenes name — this is what
  automations use"), pre-filled, and ignores whatever comes back in it;
- renaming a target changes its `name` and nothing else.

Existing targets keep their slug: nothing is migrated, and
`notify.switchboard_<slug>`, `explain`, the services and the routing-table
entity keep using the stored value. The frozen names of the contract are
untouched; what changes is the field list of a public step id (§7).

`read_only` is part of every selector's base config schema in 2026.9.1
(`make_selector_config_schema`, `homeassistant/helpers/selector.py`); a
frontend that ignored it would show an editable field whose edits are
discarded, which is safe.

### 2. Observer mode is on by default, and the YAML is shown only when it is needed

On the `target` step `observer_mode` defaults to **true**. Its default on the
internal `target_edit` step stays **false**, so a stored target submitted by a
client that omits the key keeps the 0.7 meaning of "absent".

After the `target` (or `target_edit`) step, the confirmation the user meets
depends on what they chose:

| Observer mode | Alert watched | Confirmation step | What it says |
|---|---|---|---|
| off | any | `target_saved` | the `alert:` block, exactly as 0.7.1, with `notifiers:` |
| on | an `alert.*` | `target_ready` | one line: "As soon as “{name}” goes off, these people are told: {audience}. Nothing else to do." — no YAML, no restart |
| on | none | `target_ready_manual` | the target watches nothing, so nothing will ever go off by itself; it is the service `notify.switchboard_<slug>`, to call from an automation |

All three are internal step ids (contract v0.6 already lists `target_saved`
as internal) and all three carry the `advanced` checkbox of ADR-0020 §1. Three
step ids rather than one with a code-assembled text keep every sentence in
`options.step.*`, where translators already work.

### 3. A menu in three blocks, one entry per thing

Home Assistant renders a menu as a flat list of `next_step_id` buttons
(`async_show_menu` builds `vol.In(menu_options)`); there is no separator and
no heading, so a "— People of the house —" line is not possible. Order and
wording carry the grouping instead. The top-level menu is exactly seven
entries:

| Entry | Label (en / fr) | Opens |
|---|---|---|
| `person` | Add somebody / Ajouter quelqu'un | the person picker, then `person_outputs` |
| `edit_person` | Change somebody / Modifier quelqu'un | one picker, then `person_outputs` |
| `remove_person` | Remove somebody / Retirer quelqu'un | one picker, then a confirmation (§4) |
| `target` | Add an alert / Ajouter une alerte | the `target` step |
| `edit_target` | Change an alert / Modifier une alerte | one picker, then `target_edit` |
| `remove_target` | Remove an alert / Retirer une alerte | one picker, then a confirmation (§4) |
| `general` | Settings / Réglages | a second menu |

`general` is now itself a menu, with five entries: `default_target` (the
target used by `notify.switchboard` — the form `general` used to be),
`critical_payload` (moved out of that form into its own step, same option,
same default), `ttl`, `test_person` and `test_target`.

The three entries `edit_person_advanced`, `edit_target_advanced` and
`edit_target_escalation` leave the menu, and their picker steps are removed.
What they opened is reached from the edit screens instead, by a checkbox, the
way `target_saved.advanced` already works (ADR-0020 §1):

- `person_outputs` gains `advanced` ("Set up their night now") → carries on
  into `person_advanced` for the same person;
- `target_edit` gains `advanced` → `target_advanced`, and `escalation` →
  `target_escalation`; ticking both opens one after the other. The confirmation
  steps of §2 keep their own `advanced` checkbox for a new target.

As before, nothing is written to `entry.options` until the last step of the
chain is submitted.

**Titles.** The label of every menu entry — at both levels — is exactly the
title of the screen it opens, in every language, so a user who clicked "Add an
alert" lands on a screen called "Add an alert". The menu labels use the word
the brief chose, *alert*, because that is what a newcomer comes to add; the
screens behind them keep calling the stored object a *target* where they
explain it (ADR-0020 §6 is not reopened), and the `target` step says once that
"each alert you add here is a target".

### 4. A removal says what will be lost, and asks

`remove_person` and `remove_target` are still pickers. Submitting one no longer
removes anything: it opens a confirmation step — `remove_person_confirm`,
`remove_target_confirm`, both internal — whose description says what will be
lost, and whose only field is a checkbox `confirm` ("Yes, remove").

- For a person: "{person} will no longer be told by: {targets}", listing the
  names of the targets whose audience holds them, or "no alert yet".
- For a target: the people it tells, and the service name that will stop
  doing anything.

Submitting with the box unticked is refused with an error on the field
(`not_confirmed`), not silently ignored: a confirmation that can be dismissed
by pressing Submit is not one. Closing the dialog is the way out, as for every
options flow.

### 5. "Create a night schedule for {person}" — a helper the user owns

`person_outputs` gains a checkbox `night_schedule`. When it is ticked and the
form is otherwise valid, the flow creates a core **`schedule` helper** named
after the person ("{person}'s night" / « Nuit de {person} » / "Noche de
{person}"), on from **22:00 to 07:00 every day**, and adds its entity id to
that person's `silence_entities`.

**The API, verified in 2026.9.1.** `schedule` keeps its UI-created helpers in
a `ScheduleStorageCollection` (`homeassistant/components/schedule/__init__.py`,
a `DictStorageCollection` from `homeassistant/helpers/collection.py`). Core
exposes that collection only through the websocket commands
`DictStorageCollectionWebsocket(storage_collection, "schedule", "schedule",
…).async_setup(hass)` registers — `schedule/list`, `schedule/create`, … —
and keeps no other reference to it: there is no `hass.data["schedule"]`, and
`async_setup` holds the collection in a local variable. The registered
`schedule/list` handler is the bound method `ws_list_item` of that
`StorageCollectionWebsocket` (not wrapped by `require_admin`, because
`schedule` does not pass `admin_only`), stored as
`hass.data["websocket_api"]["schedule/list"] = (handler, schema)`
(`homeassistant/components/websocket_api/__init__.py`,
`async_register_command`). The flow follows that handler to its
`storage_collection` and calls `StorageCollection.async_create_item(data)` —
the very method the `schedule/create` command calls, with the same validation
(`ScheduleStorageCollection._process_create_data` runs
`BASE_SCHEMA | STORAGE_SCHEDULE_SCHEMA`). Once it returns, the collection's
change listener has added the entity (`_CollectionLifeCycle._collection_changed`
awaits `async_add_entities`), so the entity id is read from the entity
registry by `("schedule", "schedule", <item id>)`.

This lookup is the one place this integration reaches through a core
implementation detail rather than a documented Python API, because none
exists. It is fenced accordingly:

- if `schedule` is not loaded, the flow sets it up (`async_setup_component`
  with no YAML; it is part of `default_config` and almost always loaded);
- if the handler, its `__self__` or its `storage_collection` is not there, or
  creation raises, the step shows `night_schedule_failed` on the checkbox and
  writes nothing — the person is not saved half-done;
- a schedule already named that way is **reused**, not duplicated, so ticking
  the box twice gives one night.

A block cannot cross midnight (`valid_schedule` requires `from < to`), so each
day carries two blocks, `00:00:00–07:00:00` and `22:00:00–24:00:00`, which core
treats as one continuous night (the `next_event` it publishes at 22:00 is
07:00 the next morning only through the 24:00 → 00:00 join; the router reads
`next_event` as "the end of the current block", ADR-0020 §3, so a deferred
message is flushed at 00:00 and re-decided, still silenced, then at 07:00 —
which is the documented behaviour of a re-armed deferral, ADR-0019 §3).

**Ownership.** The helper belongs to the user from the moment it exists. The
router does not record that it created it, never edits it, never deletes it
— not when the person is removed, not when the entry is removed. Doctrine §2.1
says the router *reads* the state Home Assistant models and does not own it;
creating an ordinary helper on the user's explicit request, and then reading
it exactly like one they made by hand, keeps that line. The user edits its
hours in **Settings → Helpers**, like any schedule.

### 6. A wake time without seconds

`person_advanced.wake_time` becomes a text field instead of a
`TimeSelector`. It accepts `7:30`, `07:30`, `7h30`, `7 h 30`, `07:30:00` — the
forms a person types — and stores the normalised `"HH:MM:SS"` string the
contract has always documented (v0.7 §`sensor.switchboard_routing_table`:
"`wake_time` is the `"HH:MM:SS"` string the options carry"). It opens on the
stored value without seconds (`07:30`). Its help text gives an example. An
unreadable value is refused with the existing `invalid_time` error.

### 7. A person is understood from one line

Every person picker (`edit_person`, `remove_person`, `test_person`) labels a
person as "{name} — {devices}, quiet: {silences}": the devices by the same
labels the outputs picker uses (a phone by the device name its owner gave
it), the silences by their friendly names (so the helper of §5 reads "Bob's
night"). A person with no device reads "no device yet"; one with no silence
has no "quiet" part. The `value` stays the `person.*` entity id.

## Contract changes (docs/contract.md, v0.8 addendum)

- The public step id `target` holds **four** fields: `name`, `alert_entity`,
  `audience`, `observer_mode`; `observer_mode` defaults to true there. `slug`
  is derived (§1) and no longer a field of any step that can change it.
- `person_outputs` holds `outputs` and `silence_entities` — the two stored
  fields, unchanged — plus two flow-only checkboxes that store nothing,
  `night_schedule` and `advanced`.
- `person_advanced.wake_time` accepts times without seconds and still stores
  `"HH:MM:SS"`.
- `target_advanced` and `person_advanced` keep their ids and fields; they are
  reached from the edit screens rather than from menu entries of their own.

No other public name moves. The test step ids, `general`, `ttl` and every
picker remain internal.

## Alternatives rejected

- **Keep `slug` and pre-fill it from the name.** A form cannot react to a
  field it is showing (ADR-0018 §2), so the pre-fill would need a step of its
  own, and a pre-filled field still invites an edit that the next capital
  letter refuses.
- **A separator entry in the menu** ("— People of the house —"). Every menu
  entry is a step id that the frontend renders as a button; a separator would
  be a button that does nothing.
- **Creating the night as an internal router schedule.** That is a clock of
  the router's own (ADR-0021 §0) and a second, hidden place where a night
  lives. A core helper is visible, editable and survives the integration.
- **Deleting the helper with the person.** The user may have reused it
  elsewhere; deleting something we cannot prove is still ours is the kind of
  ownership doctrine §2.1 refuses.
- **`TimeSelector` with `no_second`.** Not accepted by the 2026.9.1 backend
  schema (§6).

## Consequences

- A newcomer adds an alert with one free-text name, one alert, one list of
  people and a switch already in the right position, and finishes on a
  sentence instead of a YAML block.
- Older acceptance tests that submitted `slug` to the `target` step, opened
  the three removed menu entries, or reached `test_*` / `ttl` from the top
  menu are amended for that and nothing else; the amendments are listed in
  `tests/acceptance/README.md` §Sprint 8.
- One core implementation detail (§5) is now load-bearing for one checkbox.
  If a future core moves the schedule collection, the checkbox fails visibly
  (`night_schedule_failed`) and nothing else breaks; `docs/known-issues.md`
  records it.
