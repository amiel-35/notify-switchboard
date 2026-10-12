# Blueprints

Automation blueprints that call Notify Switchboard's per-target service,
`notify.switchboard_<target>` (see [`contract.md`](contract.md)). They cover
one-off facts, not a lasting condition — `alert:` is native YAML, not an
automation platform, so **no blueprint here creates an `alert:`**. For a
lasting condition (a leak, a fault that repeats or needs acknowledging), copy
a snippet from [`docs/examples/`](examples/) instead and list
`switchboard_<target>` under its `notifiers:`.

One ships **inside the integration** and is put in your blueprints for you;
the other three live under
[`blueprints/automation/notify_switchboard/`](../blueprints/automation/notify_switchboard/)
and are imported by hand. All four call `notify.switchboard_<target>` with
`data.source_entity` set to the triggering entity.

## Set an alert off from a sensor (shipped with the integration)

**Files:** [`custom_components/notify_switchboard/blueprints/<language>/alert_from_a_sensor.yaml`](../custom_components/notify_switchboard/blueprints/)
— English, French and Spanish, the same automation with translated texts
(Home Assistant does not translate blueprints).

This is the automation an alert tied to no Home Assistant alert needs. You do
not import it: the first time **Add an alert** ends on "it will not go off on
its own", the integration copies the file for your language to
`blueprints/automation/notify_switchboard/alert_from_a_sensor.yaml` in your
configuration — only if no file is there — and the screen links to your
blueprints. Click it, pick the sensor, type the alert's automation name, save.
The file is yours from then on: it is never overwritten and never removed,
not even when Notify Switchboard is. If it cannot be copied, the screen links
to the import dialog instead:

[![Open your Home Assistant instance and show the blueprint import dialog with a specific blueprint.](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fraw.githubusercontent.com%2Famiel-35%2Fnotify-switchboard%2Fv0.9.0%2Fcustom_components%2Fnotify_switchboard%2Fblueprints%2Fen%2Falert_from_a_sensor.yaml)

| Input | Required | Default | Notes |
|---|---|---|---|
| `trigger_entity` | yes | — | The sensor that notices the problem. |
| `trigger_to` | no | `on` | The state that sets the alert off. |
| `alert_name` | yes | — | The alert's automation name: calls `notify.switchboard_<alert_name>`. |
| `message` | no | `""` | Empty means the sensor's name. |
| `done_message` | no | `""` | Sent with `switchboard_done: true` when the sensor leaves that state — never louder than the alert's `done_priority`. Empty means nothing is sent. |
| `priority` | no | `default` | `default` sends none, so the alert's own applies; else `info` \| `normal` \| `high` \| `critical`. |

The start trigger fires from any state, so a leak that starts during a
restart (`unknown → on`) or a sensor that comes back already wet
(`unavailable → on`) sets the alert off. The done trigger ignores a change to
`unavailable` / `unknown`: a sensor dropping off the network does not
announce the end of anything. The file's `source_url` is pinned to this
version's release tag, so **Re-import** never fetches a newer blueprint than
the integration you run. In French and Spanish its name starts with the
integration's name as those screens show it ("Standard de notification
(Notify Switchboard) : …"). This path has no Acknowledge button and no reminders: for those, use a
Home Assistant `alert:` (see [`docs/examples/`](examples/)).

```yaml
automation:
  - alias: "Water leak"
    use_blueprint:
      path: notify_switchboard/alert_from_a_sensor.yaml
      input:
        trigger_entity: binary_sensor.leak_kitchen
        alert_name: water_leak
        done_message: "The kitchen is dry again."
```

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

Only **Set an alert off from a sensor** sends one (its `done_message`), but
your own automation often does too. Add `switchboard_done: true` to such a call's
`data` and it becomes the target's **done** message — reaching only the
people that target's current episode actually reached:

```yaml
action: notify.switchboard_leak
data:
  message: "Back to normal"
  data:
    switchboard_done: true
```

The episode filter only changes anything on a target that names an
`alert_entity`; one without has no episodes, so the message routes to the
whole audience as usual. On every target, a done message is routed at no more
than the target's `done_priority` (*normal* unless you changed it). The
`done_message` of an `alert:` that lists `switchboard_<target>` under
`notifiers:` is recognised as one too, without any key.

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

Every blueprint here calls `notify.switchboard_{{ target_slug }}` (or
`{{ alert_name }}`) — templated, not static, so one blueprint works with any
target. If that input does not match a target's slug, the call fails as an ordinary "service not found"
error rather than the friendlier `unknown_target` repair (which only fires
for the default `notify.switchboard` service with a `target:` list).
Double-check the slug before relying on a blueprint in production.
