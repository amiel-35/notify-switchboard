# ADR 0018: Zero-config and explainability — `explain`, discovered Companion outputs, a managed default row, consistency repairs

Date: 2026-09-07

## Status

Accepted.

## Context

0.3.0 pays the debts a HACS review would stop on. What it does not fix is the
first hour of use, and the first argument the router will ever lose.

**The first hour.** A newcomer who installs the integration from HACS gets an
empty routing table and a form that asks for `outputs` as free text. To fill
it they have to know that Companion push is a *legacy* notify service, that
its name is `slugify("mobile_app_" + <the device name they typed into the
Companion app months ago>)`, and that `notify.` may or may not be part of what
they type. Nothing in the UI tells them any of that, and a typo produces no
error at all — it produces a `missing_output` repair three failed deliveries
later. Then they still have to invent a routing-table row, pick a slug, and
set it as the default target before `notify.switchboard` does anything at all.
Every one of those steps is knowledge the instance already holds: the
`mobile_app` config entries know which phones belong to which Home Assistant
user, and `person.user_id` links a user to a person.

**The first argument.** "Why didn't I get the leak alert?" has no answer today
that a user can reach. The routing decision is real and auditable —
`sensor.switchboard_dropped_today` carries a `reasons` attribute, the
diagnostics carry a decision log — but both are *post mortem*: they describe
messages that were already sent, in aggregate, without saying what would
happen to the next one, or why. The five 0.2 services act; none of them
answers a question. A user cannot check a configuration without firing a real
notification at their household.

Neither gap needs a new routing rule. Both are discovery, defaults and
diagnosis over the decision engine that 0.1.0 already has, which is why this
ADR deliberately adds no concept to §"Routing decision" of the contract.

Three smaller findings from the same reading are folded in here because they
have the same shape — the router knows something the user has to discover the
hard way:

- a person configured with an empty `outputs` list sits in an audience and is
  dropped with `no_outputs` on every single message, silently, forever;
- a row whose `alert_entity` names an `alert.*` that does not exist (a typo, a
  YAML block that was renamed) acknowledges nothing and observes nothing, and
  nothing says so;
- a row that has just been saved needs an `alert:` block written by hand
  against a `notifiers:` name (`switchboard_<slug>`) the user has to derive.

## Decision

### 1. `notify_switchboard.explain` — a read-only sixth service

A sixth `notify_switchboard.*` service, registered in `async_setup` next to
the five of ADR-0016/ADR-0017 §5, with
`supports_response=SupportsResponse.ONLY`
(`homeassistant/core.py`: `SupportsResponse` at line 2539,
`ServiceRegistry.async_register(..., supports_response=...)` at line 2725,
`ServiceRegistry.async_call(..., return_response=...)` at line 2863; a service
registered `ONLY` refuses a call made without `return_response=True`, lines
2896-2918).

Fields:

| Field | Required | Meaning |
|---|---|---|
| `target` | yes | a routing-table slug |
| `priority` | no | one of `info` / `normal` / `high` / `critical`; defaults to the row's `default_priority`, exactly as `data.priority` does on a real call |
| `person` | no | a `person.*`; defaults to the row's whole audience |

Response:

```yaml
target: leak            # the slug that was evaluated
priority: normal        # the effective priority the evaluation used
persons:                # keyed by person entity id, core's idiom for a
  person.alice:         # per-entity response (cf. weather.get_forecasts)
    decision: routed    # routed | deferred | dropped
    until: null         # ISO 8601 local instant, `deferred` only
    reason: null        # a drop reason from the frozen list, `dropped` only
    detail: "…"         # a translated sentence, always present and non-empty
    outputs: []         # `notify.*` services this message would reach
    missing_outputs: [] # configured outputs that are not registered services
```

Rules that make the shape unambiguous:

- **`persons` is a mapping keyed by the `person.*` entity id**, not a list.
  Core answers per-entity questions that way (`weather.get_forecasts`,
  `calendar.get_events`), and a card that wants one person should not have to
  scan a list.
- **`decision` is one of exactly three values.** `deferred` is reported when
  the person would be silenced by one of their own configured
  `silence_entities`, has a `wake_time`, and the priority is not `critical` —
  the same three conditions `Switchboard._async_defer` applies, so `explain`
  cannot claim a deferral the dispatcher would not make.
- **`until` is populated for `deferred` and for nothing else.** The expiry of
  a snooze or of a temporary silence belongs in `detail`, not in `until`:
  `until` answers "when will this message arrive", and a dropped message never
  arrives.
- **`reason` is populated for `dropped` and for nothing else**, and its value
  is one of the drop reasons already frozen by the contract. No new reason is
  introduced. In practice `explain` can report `not_in_audience`,
  `unknown_person`, `presence`, `silenced`, `snoozed`, `recursion` and
  `no_outputs`; `unknown_target` cannot occur (it raises, see below) and
  `delivery_failed` is not predictable by definition.
- **`detail` is always a non-empty translated sentence**, in the instance
  language, naming the thing the user has to look at: *which* silence entity
  is on, *when* the snooze lifts, the presence rule *and* the person's current
  state, the outputs a routed message would reach. The wording is the coding
  agent's; that it exists, is translated in en/fr/es and names the deciding
  object is the specification.
- **`outputs` and `missing_outputs` carry full `notify.*` service names.**
  Everywhere else in this integration an output is stored bare
  (`mobile_app_alice`) because that is what the router compares; `explain` is
  read by a human or by a card, and the useful answer to "where would this go"
  is something you can paste into Developer tools. `outputs` is empty for a
  `dropped` person: it is what *would be called*, and nothing would be.
  `missing_outputs` is computed whatever the decision — a broken output is
  worth reporting even to somebody who is currently snoozed.
- **A person outside the row's audience is not an error.** `explain` with an
  explicit `person` who is known to the router but absent from the row answers
  `dropped` / `not_in_audience`. That is the single most likely question
  ("why does Bob never get this one?") and refusing it would send the user
  back to reading the options.
- **An unknown target, or a `person` the router does not know, raises**
  `ServiceValidationError` with the existing translation keys
  `unknown_target` / `unknown_person`, like every other service (ADR-0015).
  With no config entry loaded it raises `no_loaded_entry`, like the other five
  (ADR-0017 §5).

**`explain` is a pure evaluation.** It calls no `notify.*` service, increments
no counter (`routed_today`, `dropped_today`, `deferred_today` are untouched),
fires no `event.switchboard_delivery`, queues no deferral, writes no snooze
and does not persist the store. It re-uses `router.decide` over
`Switchboard.build_context()` and stops there. This is not a nicety: a service
somebody runs to *understand* their configuration must not change it, and a
card that calls `explain` on every render must not inflate the day's counters.

Rejected: a `switchboard.explain` **template function** or a
`sensor.switchboard_explanation` entity. A template function is not reachable
from Developer tools > Actions, which is where a user debugging a
notification already is; an entity would need a target to be pinned in the
options before it could say anything, which is the opposite of a diagnostic
tool. Also rejected: making `explain` `SupportsResponse.OPTIONAL` — there is
nothing to do with a call that discards the answer, and `ONLY` makes that a
loud refusal instead of a silent no-op.

### 2. Companion outputs are discovered, labelled and pre-selected

The person editor is split in two options-flow steps, because a form cannot
react to a field it is showing:

| Step | Fields | Reached from |
|---|---|---|
| `person` | `entity_id` (the `person.*`) | the `init` menu, to add a person |
| `person_outputs` | `outputs`, `silence_entities`, `wake_time` | `person` and `edit_person` |

`edit_person` keeps picking an existing row and now opens `person_outputs`
directly. Nothing about the stored options shape changes: a person row is
still `{entity_id, outputs, silence_entities, wake_time}`, written in one
piece when `person_outputs` is submitted.

In `person_outputs`, `outputs` becomes a
`selector.SelectSelector(SelectSelectorConfig(options=…, multiple=True,
custom_value=True, sort=False))`
(`homeassistant/helpers/selector.py`, `SelectSelectorConfig` line 1883,
`SelectOptionDict` line 1869). `custom_value` keeps the 0.1 behaviour of
typing a service that does not exist yet — a phone that has not registered,
an output created later — and `sort=False` is load-bearing: the frontend
would otherwise re-sort the list and destroy the ordering below.

The option list is **every registered `notify.*` service except this
integration's own** (`switchboard`, `switchboard_<slug>`), read from
`hass.services.async_services_for_domain("notify")`
(`homeassistant/core.py` line 2647). Every option is a `SelectOptionDict`.

The services that belong to *this* person's phones come **first**, and their
`label` carries a translated marker (`common.this_persons_device`) next to the
service name; every other option's `label` is the service name itself. The
link is exact, not a name heuristic:

1. the `person.*` entity publishes the Home Assistant user it is linked to as
   the `user_id` state attribute
   (`homeassistant/components/person/__init__.py` line 650, writing
   `PersonEntityStateAttribute.USER_ID`, `person/const.py` line 17);
2. each Companion registration is a `mobile_app` config entry whose `data`
   holds `user_id` and `device_name`
   (`homeassistant/components/mobile_app/const.py`: `CONF_USER_ID` line 17,
   `ATTR_DEVICE_NAME` line 34; the entry is created from the registration
   payload in `mobile_app/config_flow.py` lines 50-57);
3. the legacy push service of a registration is named from that same
   `device_name`: `mobile_app/notify.py` `push_registrations` (line 140) keys
   its `targets` by `entry.data[ATTR_DEVICE_NAME]` (line 148), and
   `notify/legacy.py` `BaseNotificationService.async_register_services`
   (line 274) registers each target as
   `slugify(f"{self._target_service_name_prefix}_{name}")` (line 279) — the
   **whole** string is slugified, prefix included. The router already composes
   exactly that name in `dispatcher.companion_service_name`.

So: for each `mobile_app` config entry whose `data["user_id"]` equals the
person's `user_id` attribute, `companion_service_name(data["device_name"])` is
that person's own output — kept as an option only if the service is actually
registered, since a registration without push does not produce one.

For a **new** person those services are the `suggested_value` of `outputs`
(`OptionsFlow.add_suggested_values_to_schema`, already used by 0.2.0 to
pre-fill an edited row). Editing an existing person keeps suggesting what is
stored: discovery must never silently re-add an output somebody removed.

Rejected: guessing the service from the person's own name
(`mobile_app_<person object_id>`), which is what the doctrine's examples
suggest and what a household with two phones per person breaks immediately.
Rejected too: reading `mobile_app`'s `hass.data` — the config entries are the
public surface, `hass.data` is not.

### 3. Focus binary sensors are proposed as silence entities

Same step. `silence_entities` keeps its `EntitySelector` (domains
`binary_sensor`, `schedule`, `input_boolean`, `multiple=True`) and gains, for
a **new** person only, a `suggested_value`: the `binary_sensor` entities
registered by one of that person's `mobile_app` config entries whose
`entity_id` or entity-registry `translation_key` contains `focus`. That is
iOS's Focus sensor, which the Companion app registers per device, and it is
the single most useful silence source a phone can offer.

Android's "Do Not Disturb" is deliberately **not** proposed: it is a `sensor`
with several string states (`off`, `priority_only`, `alarms_only`,
`total_silence`), and the router's silence contract is "state is `on`". Making
it work needs a one-line template `binary_sensor`, which belongs in
`docs/quickstart.md`, not in a selector that would silently never match.

### 4. A managed `default` row, created and kept in sync

When a person is added through the options flow **and the routing table is
empty**, the router creates one row and points the default target at it:

```python
{
    "slug": "default",
    "name": <translated common.default_target_name>,
    "class": "general",
    "default_priority": "normal",
    "alert_entity": None,
    "audience": [<every configured person>],
    "presence_rule": "always",
    "allow_acknowledge": False,
    "snooze_minutes": [],
    "default_data": {},
    "observer_mode": False,
    "message": None, "done_message": None, "default_title": None,
    "managed": True,          # new, and the only new options key of 0.4
}
```

and `default_target` becomes `"default"`. `notify.switchboard` therefore
works — really works, reaching a real phone — as soon as one person with one
output exists, which after §2 is one form with everything pre-filled.

`managed` is a new **optional** row key. Absent means false, so every row
written by 0.1-0.3 keeps behaving exactly as it does today, and no storage
migration is needed.

While `managed` is true, the row's `audience` is rewritten to every configured
person on every options write: adding a second person adds them to the default
target without anybody having to remember to. Removing a person removes them,
as it already does for every row.

**Submitting the row editor for that row clears `managed`** — any field, even
an unchanged one. The rule is deliberately blunt: the moment a user opens the
default row and presses submit, they have taken ownership of its audience, and
a table that silently re-adds a person they just removed is worse than no
automation at all. Nothing ever sets `managed` back to true; re-creating it
means deleting the row and adding a person to an empty table.

Rejected: a hidden, non-editable row. It would need its own UI to explain
itself and would strand anybody who wants to narrow the audience. Rejected
too: syncing the audience of *every* row with no audience — that is a
different feature (a "everyone" pseudo-audience) and it would change the
routing semantics this sprint promises not to touch.

### 5. Two consistency repairs

Both follow the shape ADR-0017 §4 established: `severity=warning`,
`is_fixable=False` (there is nothing the integration can do; the fix is in the
user's configuration), translated in `strings.json` and all three translation
files, raised once, deleted when the condition disappears on reload
(`homeassistant/helpers/issue_registry.py`, `async_create_issue` /
`async_delete_issue`, already used by `dispatcher._async_review_person_user_ids`).

| Issue | Condition | Placeholders |
|---|---|---|
| `person_without_outputs` | a person who is in the audience of at least one row has an empty `outputs` list | `person` |
| `alert_entity_missing` | a row's `alert_entity` is not in the state machine `ALERT_ENTITY_GRACE_SECONDS` after the entry was set up | `slug`, `entity_id` |

Issue ids are `person_without_outputs_<person entity id>` and
`alert_entity_missing_<slug>`, one per person / per row.

`person_without_outputs` is evaluated at setup, next to
`_async_review_person_user_ids`: an options change reloads the entry, so that
is also the moment the gap is closed. A person in no audience raises nothing —
without a row there is nothing to fail.

`alert_entity_missing` cannot be evaluated at setup: at that moment the
`alert` component may not have been set up yet, and a router that shouts about
every alert during startup would train users to ignore it. The check runs once,
`ALERT_ENTITY_GRACE_SECONDS` after the entry's own setup, scheduled with
`homeassistant.helpers.event.async_call_later` (line 1552). The constant is
**60 seconds** and lives in `dispatcher.py`, as a plain module constant, for
exactly the reason `OUTPUT_TIMEOUT_SECONDS` does (ADR-0017 §3): it is a
backstop, not a tuning knob, and the acceptance suite must be able to reach
past it without waiting a minute. Issues for a slug the table no longer has,
or for a row that no longer names an alert, are deleted at setup; a row whose
alert has since appeared has its issue deleted at the next grace check.

The existing `missing_output_*` issue (an output that is not a registered
service) is unchanged, and keeps the caveat `docs/known-issues.md` records for
it.

### 6. "Test this person" / "Test this target" in the options flow

Two menu entries, `test_person` and `test_target`, each a step that sends
**one real message through the real routing path** — counted, evented,
deferred or dropped exactly like any other — and then shows what happened.

- `test_target` asks for a slug and routes to that row.
- `test_person` asks for a `person.*` and routes to the row that reaches them:
  the `default_target` when that person is in its audience, otherwise the
  first row (in stored order) whose audience contains them. A person in no
  audience aborts with `nothing_to_test`.
- The message is the translated `common.test_message`; the title is whatever
  the row's `default_title` says, as for any caller that supplies none.
- The call carries `data.tag: switchboard-test` (constant
  `TEST_MESSAGE_TAG` in `const.py`). The tag is what lets a user — and a
  Companion notification channel, and the deferral store's `(person, target,
  tag)` key — tell a test from the real thing.
- Both then show the step `test_result`, whose description carries the
  `explain` answer for the same call through
  `description_placeholders={"result": …}`: one line per person, each naming
  the person and their `detail`. Submitting `test_result` returns to the
  options menu; nothing is written to `entry.options` by a test.

A real message rather than a dry run is the point: it proves the *output*
works, which `explain` cannot. `explain` is what gives the step its
explanation, so the two features pay for each other.

### 7. The `alert:` snippet, on the row editor's confirmation step

Submitting the `target` step no longer writes the options directly. A valid
row goes to a new confirmation step, `target_saved`, which shows a
ready-to-paste YAML block through `description_placeholders={"snippet": …}`;
submitting *that* step is what writes `entry.options`.

The block defines the `alert:` the row expects, keyed by the object id of the
row's `alert_entity` when it has one (that is the alert the row is tied to)
and by the slug otherwise, with a `notifiers:` list containing
`switchboard_<slug>` — the legacy service name, without the `notify.` prefix,
which is what `alert:` wants — a `state:` and a `repeat:` example, and a
placeholder `entity_id:` for the entity the alert watches, which the router
cannot know.

Hassfest rule to respect while writing it: a placeholder in `strings.json`
must never be wrapped in single quotes (`'{snippet}'`), or the string is
rejected. Braces *inside the value* handed to `description_placeholders` are
fine — this snippet contains none, but a `repeat:` example is close enough to
templating that it is worth saying.

## What does not change

- Every v0 / v0.2 / v0.3 frozen name, the four `event.switchboard_delivery`
  event types, the drop reasons, the `data.*` input keys, and the routing
  decision itself. `explain` reads it; nothing here writes a new rule into it.
- The five services of ADR-0016: fields, effects, refusals, non-admin status.
- The `Store` schema and its minor version: `managed` lives in
  `entry.options`, not in the store, and nothing here persists anything new.
- Observer mode, per-row texts, the fan-out guarantees, the callback
  resolution order.
- `notify.switchboard`'s own behaviour when no target is given: it uses
  `default_target`, which §4 now fills in on its own instead of leaving `None`.

## Consequences

- `docs/contract.md` gains a "v0.4 addendum (ADR-0018)" block: `explain` in
  the frozen service names with its response keys, the `managed` row key, the
  two repair keys and the test tag. Third amendment authorized by ADR-0011's
  "requires an ADR" clause; released as 0.4.0, still not a major version,
  because nothing is removed or renamed.
- `strings.json` and `translations/{en,fr,es}.json` grow: the `explain`
  service and its fields, `common.this_persons_device`,
  `common.default_target_name`, `common.test_message`, the `detail` sentences
  for every decision and drop reason, the new options steps
  (`person_outputs`, `target_saved`, `test_person`, `test_target`,
  `test_result`) with their `{snippet}` / `{result}` placeholders, the two new
  `issues` entries, and the two new `init` menu entries.
- The options flow gains four steps and loses none; `person` keeps its id but
  now asks a single question.
- `quality_scale.yaml` can claim `discovery`-adjacent friendliness it could
  not before; it still cannot claim anything about `explain` beyond
  `action-setup`, which it already has.
- A future ADR is needed to make `ALERT_ENTITY_GRACE_SECONDS` configurable, to
  add a `decision` value to `explain`, to give `explain` a side effect of any
  kind, or to make `managed` recoverable once cleared.
