# Accepted deviations

Three places where this integration knowingly bends one of its own stated
principles, and what each one bought. They are **not** findings: nobody
reported them, nothing is waiting to be fixed, and none of them is a
compromise made under time pressure. They are design the maintainer chose,
recorded here so that the principle stays honest — a doctrine that is never
seen to bend is a doctrine nobody is reading.

[`known-issues.md`](known-issues.md) is the other file, and it is for findings
accepted *instead of being fixed*. The two were mixed until 0.6.0
(ADR-0020 §8). Vocabulary is the [Glossary](../README.md#glossary)'s.

---

## 1. A temporary silence is state the router owns

**The deviation.** `notify_switchboard.silence` sets a per-person silence that
lives in this integration's own `Store`, with an expiry the router schedules
and purges itself. Everything else the router reads about the world — presence,
a night schedule, a Focus sensor — is somebody else's entity.

**The principles it bends.** "Native first" ([ADR-0001](ADR/0001-native-first.md))
says a thing Home Assistant already models should be modelled with Home
Assistant's own object; "the router is a pure proxy"
([ADR-0002](ADR/0002-pure-proxy.md)) says it should hold no state of its own
beyond what it must. An `input_boolean` the household owns would satisfy both.

**Why it was accepted.** An `input_boolean` cannot expire. "Quiet for the next
hour", tapped from a notification while the phone is in a pocket, is the
gesture the service exists for, and it has no native equivalent: the user would
have to create one helper per person, add an automation to turn it off again,
and remember to do it twice for a household of two. The router already owns
snoozes, which are the same shape (an instant, per person, persisted, expiring)
and which nobody has ever proposed making native. The silence is therefore held
to the same standard as a snooze instead: it is persisted, it survives a
restart, it lifts on its own, it is visible in
`binary_sensor.<person>_silenced` with an `until` attribute, and it never
touches the entities the household owns.

**What it costs.** One more piece of state to migrate, and one place where the
answer to "why am I silent?" is inside this integration rather than in an
entity the user can see on a dashboard. `explain` names it explicitly for
exactly that reason.

---

## 2. An episode is a small persisted record of who was told

**The deviation.** For every target tied to an `alert.*`, the router remembers
one **episode** between the alert's `idle → on` and its return to `idle`: who
was actually notified, which notify services answered, and under which tags. It
is written to the `Store` and survives a restart.

**The principle it bends.** [ADR-0002](ADR/0002-pure-proxy.md) again, and more
directly than the silence does: a proxy that remembers is not only a proxy. A
strict reading of "pure" would have the router forward a message and forget it.

**Why it was accepted.** Without the memory, two things are wrong and neither
can be fixed anywhere else. A "back to normal" message goes to the whole
audience, including the people who slept through the alarm and are now being
told an incident they never heard about is over — which is the single most
common complaint about naive notification setups. And notifications the router
sent cannot be cleared when they stop being true, because nothing knows which
phones received them or under which tag. `alert` itself does not keep this: its
own `notifiers:` list is static, and it has no idea which of them actually
delivered. The episode is deliberately the smallest record that answers both
questions — recipients, outputs, tags — and it holds no message bodies.

**What it costs.** A store migration (minor version 4), one open episode that
can linger when Home Assistant restarts in the middle of an alert — see
[`known-issues.md`](known-issues.md), "an episode left open across a real Home
Assistant restart" — and a persisted object whose lifetime is decided by an
entity this integration does not own.

---

## 3. `not_in_audience` is not counted

**The deviation.** `sensor.switchboard_dropped_today` does not count a person
dropped with the reason `not_in_audience`, and neither does its `reasons`
attribute. The decision still records it, and `explain` still reports it.

**The principle it bends.** "Nothing is silently lost"
([`contract.md`](contract.md) §Routing decision): every dropped call is counted
and exposed with its reason. `not_in_audience` is a drop that is not counted.

**Why it was accepted.** A person outside a target's audience was never a
recipient of that message, so counting them would make the dropped counter a
function of the size of the household rather than of anything going wrong. On
an installation with six people and a target for two, every single message
would add four to "dropped today" — a number whose job is to be zero when the
router is working. The contract says such a person is "not considered", and
this is what not considering somebody looks like in a counter. Nothing is lost,
because nothing was ever addressed to them; the *decision* still holds the
reason, so diagnostics and `explain` can both show why somebody was left out.

**What it costs.** One case where the counters do not add up, recorded below,
and a reader who compares `deferred_today` with `routed_today + dropped_today`
and finds a gap.

### The visible consequence: a flushed deferral can leave the day's figures short

> Moved here from [`known-issues.md`](known-issues.md) in 0.6.0 (ADR-0020 §8).
> It is not a finding of its own — it is deviation 3 seen from the counters.

A deferral counted in `sensor.switchboard_deferred_today` whose person has left
the target's audience overnight re-decides at the flush to `not_in_audience` —
the one drop reason `UNCOUNTED_DROP_REASONS` deliberately does not count — and
so leaves the queue without reappearing in `routed_today` or `dropped_today`.
That is accepted rather than a defect because it is exactly what the live path
already does with the same decision: making the flush count it would mean the
same message is treated one way when it arrives and another way when it is
released, which is a worse inconsistency than a counter that is occasionally
one short.

---

## What would change any of these

Each one has a shape that would make it native, and none of them is closed:

1. If core ever ships an expiring boolean helper, the temporary silence becomes
   one and this deviation disappears.
2. If `alert` ever records its own delivery outcome, the episode shrinks to a
   pointer into it.
3. If the dropped counter ever grows a per-reason breakdown that a dashboard
   can filter, `not_in_audience` can be counted like everything else without
   drowning the headline number.

Anything that changes one of them needs an ADR, exactly as the decision to
accept it did.
