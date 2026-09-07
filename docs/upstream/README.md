# Upstream issue drafts

Two findings about Home Assistant core that came out of building this
integration, written as issues ready to paste into
[`home-assistant/core`](https://github.com/home-assistant/core/issues). They
are drafts on purpose: **the maintainer files them**, under their own account,
after checking that nobody has filed the same thing in the meantime.

Both are read against **core 2026.9.1**, and every line number below was
checked against that tag. Line numbers move; the function and attribute names
are what to search for if they have.

| Draft | What it is about | Where it bites this integration |
|---|---|---|
| [`cancel-on-shutdown-async-call-later.md`](cancel-on-shutdown-async-call-later.md) | `HassJob(cancel_on_shutdown=True)` is silently ignored for every timer handle `async_call_later`, `async_call_at` and `_TrackPointUTCTime` create | Lingering-timer failures in tests around `alert`, recorded in [`../known-issues.md`](../known-issues.md) |
| [`alert-entity-startup-state.md`](alert-entity-startup-state.md) | `AlertEntity` never reads the state of the entity it watches, so a condition that was already true at startup produces no transition | An episode left open across a restart, recorded in [`../known-issues.md`](../known-issues.md) |

Neither is a blocker for anything here: both are worked around, and both
workarounds are documented where they live.
