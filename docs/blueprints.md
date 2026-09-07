# Blueprints

Automation blueprints that call Notify Switchboard's per-target service,
`notify.switchboard_<target>` (see [`contract.md`](contract.md)). They cover
the *information* half of the doctrine's "two natures" split — one-off facts
— not the *persistent* half.

`alert:` is a native, YAML-only Home Assistant integration, not an
automation platform, so **no blueprint here creates an `alert:`**. For a
lasting condition (a leak, a fault that should repeat/be acknowledged), copy
one of the complete snippets in [`docs/examples/`](examples/) instead and
list `switchboard_<target>` under its `notifiers:`.

All three blueprints live under
[`blueprints/automation/notify_switchboard/`](../blueprints/automation/notify_switchboard/)
and share the same idea: resolve a `target_slug` input to the service
`notify.switchboard_<target_slug>` and call it with `data.source_entity` set
to whatever entity triggered the automation, so voice-adapter deny-lists and
diagnostics can trace a message back to its origin.

## Information from a state change

**File:** [`blueprints/automation/notify_switchboard/information_event.yaml`](../blueprints/automation/notify_switchboard/information_event.yaml)

The general-purpose one: any entity, any state transition (or "any change at
all" if you leave from/to empty), becomes one routed notification. Use it
for a door left open, a delivery arriving, a threshold crossed once.

[![Open your Home Assistant instance and show the blueprint import dialog with a specific blueprint.](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fraw.githubusercontent.com%2Famiel-35%2Fnotify-switchboard%2Fmain%2Fblueprints%2Fautomation%2Fnotify_switchboard%2Finformation_event.yaml)

| Input | Required | Default | Notes |
|---|---|---|---|
| `trigger_entity` | yes | — | The entity to watch. |
| `trigger_from` | no | *(any)* | Only trigger from this state. |
| `trigger_to` | no | *(any)* | Only trigger to this state. |
| `target_slug` | yes | — | Target slug; calls `notify.switchboard_<target_slug>`. |
| `message` | yes | — | Template; `trigger.to_state` / `trigger.from_state` available. |
| `title` | no | `""` | Passed through as `data.title`. |
| `priority` | no | `info` | `info` \| `normal` \| `high` \| `critical`. |

Example instance:

```yaml
automation:
  - alias: "Front door opened"
    use_blueprint:
      path: notify_switchboard/information_event.yaml
      input:
        trigger_entity: binary_sensor.front_door
        trigger_to: "on"
        target_slug: doors
        message: "{{ trigger.to_state.name }} opened."
        priority: info
```

## Source-unavailability watchdog (ADR-013)

**File:** [`blueprints/automation/notify_switchboard/source_unavailable_watchdog.yaml`](../blueprints/automation/notify_switchboard/source_unavailable_watchdog.yaml)

The KLIPPBOK case: a sensor that goes `unavailable`/`unknown` and stays that
way produces nothing on its own — no state change to alert on, just silence.
This blueprint watches a list of entities and fires once an entity has been
unavailable/unknown for more than N minutes, naming the entity and the
threshold in the message.

[![Open your Home Assistant instance and show the blueprint import dialog with a specific blueprint.](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fraw.githubusercontent.com%2Famiel-35%2Fnotify-switchboard%2Fmain%2Fblueprints%2Fautomation%2Fnotify_switchboard%2Fsource_unavailable_watchdog.yaml)

| Input | Required | Default | Notes |
|---|---|---|---|
| `watched_entities` | yes | — | One or more entities; the trigger fires per entity. |
| `minutes` | no | `15` | How long an entity must stay unavailable/unknown first. |
| `target_slug` | yes | — | Target slug. |
| `priority` | no | `high` | `info` \| `normal` \| `high` \| `critical`. |

Example instance:

```yaml
automation:
  - alias: "Rain gauge and boiler sensor watchdog"
    use_blueprint:
      path: notify_switchboard/source_unavailable_watchdog.yaml
      input:
        watched_entities:
          - sensor.rain_gauge
          - sensor.boiler_flow_temp
        minutes: 15
        target_slug: source_unavailable
        priority: high
```

This is the one-shot variant — it fires once per entity, then re-arms if
that entity recovers and later goes unavailable again. Prefer a repeating,
acknowledgeable version instead? See
[`docs/examples/alert_source_unavailable.yaml`](examples/alert_source_unavailable.yaml)
(a template `binary_sensor` plus a native `alert:`). The two are
independent; nothing stops you running both.

## Appliance cycle finished

**File:** [`blueprints/automation/notify_switchboard/cycle_finished_information.yaml`](../blueprints/automation/notify_switchboard/cycle_finished_information.yaml)

A washing machine, dishwasher, or dryer's "running" `binary_sensor` going
from `on` to `off` is a one-off fact. This blueprint reports it, with an
optional `tag` for Notify Switchboard's de-duplication.

[![Open your Home Assistant instance and show the blueprint import dialog with a specific blueprint.](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fraw.githubusercontent.com%2Famiel-35%2Fnotify-switchboard%2Fmain%2Fblueprints%2Fautomation%2Fnotify_switchboard%2Fcycle_finished_information.yaml)

| Input | Required | Default | Notes |
|---|---|---|---|
| `cycle_entity` | yes | — | A `binary_sensor` that is `on` while the appliance runs. |
| `target_slug` | yes | — | Target slug. |
| `message` | no | `"{{ trigger.to_state.name }} has finished."` | Template. |
| `title` | no | `""` | Passed through as `data.title`. |
| `priority` | no | `info` | `info` \| `normal` \| `high` \| `critical`. |
| `tag` | no | `""` | Passed through as `data.tag`. |

Example instance:

```yaml
automation:
  - alias: "Washing machine finished"
    use_blueprint:
      path: notify_switchboard/cycle_finished_information.yaml
      input:
        cycle_entity: binary_sensor.washing_machine_running
        target_slug: appliances
        tag: washing_machine
```

## Marking a "back to normal" message (v0.5, ADR-0019 §5)

None of the three blueprints shipped here sends one today, but an `alert:`
block or an automation of your own often does. From 0.5.0, add
`switchboard_done: true` to such a call's `data` and it becomes the target's
**done** message: it reaches only the people the target's current episode
actually reached, and everybody else in the audience is dropped with the
reason `not_notified` rather than being told that something they never heard
about is over.

```yaml
action: notify.switchboard_leak
data:
  message: "Back to normal"
  data:
    switchboard_done: true
```

It only changes anything on a target that names an `alert_entity`: a target without
one has no episodes, so such a message routes to the whole audience like any
other. Changing the blueprints themselves to use the key is a separate,
smaller change.

## Escalation after N minutes (v0.7, ADR-0021 §9)

"Twenty minutes after the alert started, if nobody has acknowledged it, tell
somebody else." The router deliberately does **not** do this: it owns no timer
and no counter of its own, and a rule of that shape needs one. Home Assistant
already ships the timer, in the one place where it is cancelled, restored and
reconciled for you — a template `binary_sensor`'s `delay_on`.

Three pieces, none of them a blueprint, all of them YAML you paste once:

1. **A template `binary_sensor` that is `on` only once the alert has been
   firing for N minutes.** `delay_on` is core's timer: it starts when the
   condition becomes true, it is cancelled when the condition stops being true
   before it elapses, and it is re-evaluated on restart.

   ```yaml
   template:
     - binary_sensor:
         - name: "Leak unacknowledged for 20 minutes"
           unique_id: leak_unacknowledged_20m
           # `alert.*` is `on` while it is firing and nobody has acknowledged
           # it, and `off` once somebody has (core sets `_ack`), so "still on"
           # is the acknowledgement check -- no bookkeeping of your own.
           state: "{{ is_state('alert.leak', 'on') }}"
           delay_on: "00:20:00"
   ```

2. **A second `alert:` watching that sensor**, with its own repeat and its own
   notifier — the escalation's own alert, independent of the first one.

   ```yaml
   alert:
     leak_escalated:
       name: "Leak — still nobody"
       entity_id: binary_sensor.leak_unacknowledged_for_20_minutes
       state: "on"
       repeat: [30]
       can_acknowledge: true
       skip_first: false
       notifiers:
         - switchboard_leak_escalated
   ```

3. **A second target**, `leak_escalated`, whose audience is the wider one and
   whose `default_priority` is the louder one. It is an ordinary target: it
   defers, snoozes, acknowledges and clears exactly like the first, and
   `escalate_when_nobody_home` works on it too.

What this buys over a router-side `escalation_after_minutes`, which is why the
feature was deferred rather than shipped:

- the delay is **punctual**, because core evaluates `delay_on` on its own
  clock. A router-side rule could only be evaluated when the alert next called
  the router, so `20` minutes would have rounded up to the alert's `repeat`
  interval;
- the escalation is a real entity you can see, graph and test in Developer
  tools, instead of a field whose effect only shows up in a notification;
- rolling it back is deleting three blocks, and the original alert never
  knew about any of it.

The one thing it does not give you is a single form to fill in. That is the
trade ADR-0021 §9 made, and `docs/ADR/0021-escalation-and-places-reduced.md`
records what would have to change for the router to take it back.

## How to import

Click a badge above (needs the [My Home Assistant](https://my.home-assistant.io/)
component enabled, on by default), or manually: **Settings → Automations &
scenes → Blueprints → Import blueprint**, and paste the raw GitHub URL, e.g.

```
https://raw.githubusercontent.com/amiel-35/notify-switchboard/main/blueprints/automation/notify_switchboard/information_event.yaml
```

## On the templated action name

All three blueprints call `notify.switchboard_{{ target_slug }}` — a
templated action name, not a static one. This is deliberate, and verified
against Home Assistant core's own service-call schema
(`SERVICE_SCHEMA` in `homeassistant/helpers/config_validation.py`, which
accepts `dynamic_template` for the action/service field): it lets one
blueprint work with any target without needing a
`notify.switchboard` + `target: [...]` indirection. The trade-off: if
`target_slug` does not match any target's slug, the per-target service simply
does not exist yet and the call fails as an ordinary "service not found"
error in the log — you will not get the friendlier `unknown_target`
drop-and-repair-issue behaviour described in `contract.md`, because that
only fires for calls to the default `notify.switchboard` service with a
`target:` list. Double-check the slug against the target (or
copy it from **Settings → Devices & services → Notify Switchboard →
Configure**) before relying on a blueprint in production.
