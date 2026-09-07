# Quickstart: a working `notify.switchboard` in about ten minutes

Install, add one person, write the `alert:` block, restart, watch a
notification arrive. The only step that is not optional has no YAML at all:
add the integration and add one person — their phones and Focus sensors are
already filled in — and `notify.switchboard` works. This follows the public
contract in [`contract.md`](contract.md); every word used here is defined
once, in the [Glossary](../README.md#glossary).

## 1. Add the integration

Install from HACS (see [`../README.md`](../README.md)), restart, then
**Settings → Devices & services → Add integration** → **Notify Switchboard**.
Setup takes no input.

## 2. Add a person — the only required step

Open **Configure → Add or update a person** and pick a `person.*`. The form is
pre-filled: **Notify services** lists this instance's `notify.*` services,
with the phones registered to *this person's* Home Assistant user marked as
theirs and pre-selected (via the Companion registration's `user_id`, not a
guess from the name); **Silence entities** proposes their iPhone Focus
sensors. You can still type a service that does not exist yet — a speaker
becomes a person's output the same way, once it is a `notify.*` service (see
[`../README.md`](../README.md#adding-a-speaker-as-an-output)). That is the
whole form: **wake time** and night **summary** are optional, in **Advanced
settings of a person**.

Submitting this form on an **empty** routing table also creates one target,
`default`, with that person as its audience, so `notify.switchboard` now
reaches a real phone. That target is *managed*: a second person joins it
automatically until you open its editor and submit, which hands it to you for
good.

Android exposes Do Not Disturb as a multi-state `sensor`, not an `on`/`off`
`binary_sensor` — bridge it with a template
(`state: "{{ states('sensor.alice_phone_do_not_disturb_sensor') not in ['off', 'unknown', 'unavailable'] }}"`)
and pick that as the silence entity instead.

## 3. Tie a target to an alert

**Configure → Add or update a target** asks five things: a slug, a name, the
`alert.*` it is about, the audience, and whether the router watches it itself
(**Observer mode** — start here, no YAML change needed). Both wiring styles:
[`../README.md`](../README.md#wiring-a-target-to-an-alert); more examples in
[`examples/`](examples/).

## 4. Test it from the options menu

**Configure → Test a person** or **Test a target** sends one *real* message
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
