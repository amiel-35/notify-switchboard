# Blueprints

Automation blueprints that call Notify Switchboard's per-target service,
`notify.switchboard_<target>` (see [`contract.md`](contract.md)). They cover
one-off facts, not a lasting condition — `alert:` is native YAML, not an
automation platform, so **no blueprint here creates an `alert:`**. For a
lasting condition (a leak, a fault that repeats or needs acknowledging), copy
a snippet from [`docs/examples/`](examples/) instead and list
`switchboard_<target>` under its `notifiers:`.

All three live under
[`blueprints/automation/notify_switchboard/`](../blueprints/automation/notify_switchboard/)
and resolve a `target_slug` input to `notify.switchboard_<target_slug>`,
calling it with `data.source_entity` set to the triggering entity.

## Information from a state change

**File:** [`information_event.yaml`](../blueprints/automation/notify_switchboard/information_event.yaml)

Any entity, any state transition (or any change at all, left blank), becomes
one routed notification — a door left open, a delivery arriving, a threshold
crossed once.

[![Open your Home Assistant instance and show the blueprint import dialog with a specific blueprint.](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fraw.githubusercontent.com%2Famiel-35%2Fnotify-switchboard%2Fmain%2Fblueprints%2Fautomation%2Fnotify_switchboard%2Finformation_event.yaml)

| Input | Required | Default | Notes |
|---|---|---|---|
| `trigger_entity` | yes | — | The entity to watch. |
| `trigger_from` | no | *(any)* | Only trigger from this state. |
| `trigger_to` | no | *(any)* | Only trigger to this state. |
| `target_slug` | yes | — | Calls `notify.switchboard_<target_slug>`. |
| `message` | yes | — | Template; `trigger.to_state` / `trigger.from_state` available. |
| `title` | no | `""` | Passed through as `data.title`. |
| `priority` | no | `info` | `info` \| `normal` \| `high` \| `critical`. |

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

## Source-unavailability watchdog

**File:** [`source_unavailable_watchdog.yaml`](../blueprints/automation/notify_switchboard/source_unavailable_watchdog.yaml)

A sensor that goes `unavailable`/`unknown` and stays that way produces no
state change to alert on — just silence. This watches a list of entities and
fires once one has been unavailable/unknown for more than N minutes.

[![Open your Home Assistant instance and show the blueprint import dialog with a specific blueprint.](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fraw.githubusercontent.com%2Famiel-35%2Fnotify-switchboard%2Fmain%2Fblueprints%2Fautomation%2Fnotify_switchboard%2Fsource_unavailable_watchdog.yaml)

| Input | Required | Default | Notes |
|---|---|---|---|
| `watched_entities` | yes | — | One or more entities; fires per entity. |
| `minutes` | no | `15` | How long unavailable/unknown first. |
| `target_slug` | yes | — | Target slug. |
| `priority` | no | `high` | `info` \| `normal` \| `high` \| `critical`. |

This fires once per entity, then re-arms if it recovers and goes unavailable
again. For a repeating, acknowledgeable version instead, see
[`docs/examples/alert_source_unavailable.yaml`](examples/alert_source_unavailable.yaml)
(a template `binary_sensor` plus a native `alert:`) — the two are
independent, and nothing stops you running both.

## Appliance cycle finished

**File:** [`cycle_finished_information.yaml`](../blueprints/automation/notify_switchboard/cycle_finished_information.yaml)

A washing machine, dishwasher or dryer's "running" `binary_sensor` going from
`on` to `off` is a one-off fact, with an optional `tag` for de-duplication.

[![Open your Home Assistant instance and show the blueprint import dialog with a specific blueprint.](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fraw.githubusercontent.com%2Famiel-35%2Fnotify-switchboard%2Fmain%2Fblueprints%2Fautomation%2Fnotify_switchboard%2Fcycle_finished_information.yaml)

| Input | Required | Default | Notes |
|---|---|---|---|
| `cycle_entity` | yes | — | A `binary_sensor` that is `on` while it runs. |
| `target_slug` | yes | — | Target slug. |
| `message` | no | `"{{ trigger.to_state.name }} has finished."` | Template. |
| `title` | no | `""` | Passed through as `data.title`. |
| `priority` | no | `info` | `info` \| `normal` \| `high` \| `critical`. |
| `tag` | no | `""` | Passed through as `data.tag`. |

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

## Marking a "back to normal" message

None of the three blueprints above sends one, but an `alert:` block or your
own automation often does. Add `switchboard_done: true` to such a call's
`data` and it becomes the target's **done** message — reaching only the
people that target's current episode actually reached:

```yaml
action: notify.switchboard_leak
data:
  message: "Back to normal"
  data:
    switchboard_done: true
```

It only changes anything on a target that names an `alert_entity`; one
without has no episodes, so the message routes to the whole audience as
usual.

## Escalation after N minutes

"Twenty minutes after the alert started, if nobody has acknowledged it, tell
somebody else." The router deliberately does not own a timer for this. Build
it from three native pieces instead: a template `binary_sensor` with
`delay_on: "00:20:00"` that turns `on` once `alert.leak` has been firing that
long unacknowledged; a second `alert:` watching that sensor, with its own
`repeat:` and `notifiers:`; and a second target, `leak_escalated`, with a
wider audience and a louder default priority. Rolling it back is deleting
three YAML blocks, and the original alert never knew about any of it — see
[ADR-0021](ADR/0021-escalation-and-places-reduced.md) §9 for the full
reasoning.

## How to import

Click a badge above (needs the [My Home Assistant](https://my.home-assistant.io/)
component, on by default), or **Settings → Automations & scenes → Blueprints
→ Import blueprint**, pasting the raw GitHub URL, e.g.

```
https://raw.githubusercontent.com/amiel-35/notify-switchboard/main/blueprints/automation/notify_switchboard/information_event.yaml
```

## On the templated action name

All three blueprints call `notify.switchboard_{{ target_slug }}` — templated,
not static, so one blueprint works with any target. If `target_slug` does not
match a target's slug, the call fails as an ordinary "service not found"
error rather than the friendlier `unknown_target` repair (which only fires
for the default `notify.switchboard` service with a `target:` list).
Double-check the slug before relying on a blueprint in production.
