# Quickstart: a working `notify.switchboard` in about ten minutes

Install, add one person, add one alert, watch a notification arrive — from
0.8.0 none of these steps needs YAML or a restart when the alert is tied to a
Home Assistant alert you already have. The only step that is not optional:
add the integration and add one person — their phones and Focus sensors are
already filled in — and `notify.switchboard` works. This follows the public
contract in [`contract.md`](contract.md); every word used here is defined
once, in the [Glossary](../README.md#glossary).

## 1. Add the integration

Install from HACS (see [`../README.md`](../README.md)), restart, then
**Settings → Devices & services → Add integration** → **Notify Switchboard**.
Setup takes no input.

## 2. Add a person — the only required step

Open **Configure → Add somebody** and pick a `person.*`. The form is
pre-filled: **Where to tell them** lists this instance's `notify.*` services,
with the phones registered to *this person's* Home Assistant user marked as
theirs and pre-selected (via the Companion registration's `user_id`, not a
guess from the name); **When not to disturb them** proposes their iPhone Focus
sensors. You can still type a service that does not exist yet — a speaker
becomes a person's output the same way, once it is a `notify.*` service (see
[`../README.md`](../README.md#adding-a-speaker-as-an-output)). Tick **Create a
night schedule** and a `schedule` helper named after them, 22:00–07:00 every
day, is created and used as their quiet time — it is yours afterwards, in
**Settings → Helpers**. That is the whole form: **wake time** (typed `7:30`)
and the morning **summary** are optional, behind the **Set up their night
now** box.

Submitting this form on an **empty** routing table also creates one target,
`default`, with that person as its audience, so `notify.switchboard` now
reaches a real phone. That target is *managed*: a second person joins it
automatically until you open its editor and submit, which hands it to you for
good.

Android exposes Do Not Disturb as a multi-state `sensor`, not an `on`/`off`
`binary_sensor` — bridge it with a template
(`state: "{{ states('sensor.alice_phone_do_not_disturb_sensor') not in ['off', 'unknown', 'unavailable'] }}"`)
and pick that as the silence entity instead.

## 3. Add an alert

**Configure → Add an alert** asks four things: a name, **what sets it off**
(an optional Home Assistant `alert.*`), who to tell, and **Tell people as soon
as it goes off** (observer mode, on by default). Its **automation name** is
made from its name: "Water leak" becomes `notify.switchboard_water_leak`, and
stays so even if you rename it later.

- **With a Home Assistant alert picked**, the last screen just says who will
  be told. Nothing to copy, nothing to restart. People get one message when
  that alert goes off and one when it ends — **not its reminders** (`repeat`).
- **With nothing picked** — Home Assistant only creates alerts in YAML — the
  last screen puts the blueprint **Notify Switchboard: set an alert off from
  a sensor** in your blueprints (in your language) and links to them: click
  it, pick your sensor, type the automation name the screen shows
  (`water_leak`), save. That automation also sends a back-to-normal
  message that wakes nobody, if you give it one. The alert is already saved
  when that screen appears, so following its link loses nothing. Below the link, the same screen still explains
  the action `notify.switchboard_water_leak` for an automation of your own,
  and the `alert:` block to paste if you want reminders and an Acknowledge
  button (replace `binary_sensor.CHANGE_ME` with your sensor, restart, then
  pick that alert under **What sets it off**).
- **For reminders**, turn observer mode off: the Home Assistant alert then
  lists the router under `notifiers:` and every `repeat` reaches people; the
  last screen shows that block.

However it is wired, the back-to-normal message rings at **normal** at most
(**Importance of the back-to-normal message**, in the alert's advanced
settings), so the end of a critical alert does not sound like the alarm.

Both wiring styles:
[`../README.md`](../README.md#wiring-a-target-to-an-alert); more examples in
[`examples/`](examples/).

## 4. Test it from the options menu

**Configure → Settings → Send somebody a test message** or **Send a test
message through an alert** sends one *real* message
through the ordinary routing path (tagged `switchboard-test`) and reports what
happened to each person, in the same words `explain` uses.

## 5. Ask why — `notify_switchboard.explain`

**Developer tools → Actions**, `notify_switchboard.explain`, called with
**Return response**:

```yaml
action: notify_switchboard.explain
data:
  target: leak    # priority and person are optional, and default to the target's own / the whole audience
```

It answers, per person, without changing anything at all — no notification,
counter, event or queued deferral:

```yaml
target: leak
priority: normal
persons:
  person.alice:
    decision: dropped          # routed | deferred | dropped
    reason: silenced           # a drop reason, dropped only
    detail: "person.alice is silenced by input_boolean.quiet_hours. Only a critical message would get through."
    outputs: []                # what would be called
```

A person outside the target's audience is answered (`dropped` / `not_in_audience`), not refused.

## 6. When something is wrong

**Settings → Repairs** surfaces three silent failures: a person with no
notify service, a target pointing at an alert that does not exist, and a
notify service that keeps failing. Diagnostic entities:
`sensor.switchboard_routed_today` / `_dropped_today` / `_deferred_today`, and
per person `binary_sensor.<person>_silenced`, `sensor.<person>_last_notification`.

## Acknowledge and snooze from the phone

If a target has an `alert.*` and **Allow acknowledgement**, Companion
notifications get **Acknowledge** and one **Snooze `<n>`** button per
duration — each also a service a card or script can call the same way.

## Next

Already have `notify.mobile_app_*` calls scattered through automations? Read
[`migration-guide.md`](migration-guide.md) instead of starting here. One-off
facts rather than a lasting alert: [`blueprints.md`](blueprints.md). Full
field-by-field behaviour: [`contract.md`](contract.md).
