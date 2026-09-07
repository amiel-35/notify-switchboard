# How this project is built

This integration — and its siblings Cast Notifier, AirPlay Notifier, Assist
Satellite Notifier and Notify Switchboard Cards — is written almost entirely
by AI models, under the direction and responsibility of a single human
maintainer. This page says exactly how, so that you can judge the result
with the right expectations.

## Roles

- **The maintainer** owns the product need, every product decision (names,
  licence, scope, what gets deployed at home), the tests on real devices,
  and whatever code review they choose to do. They do not write the code.
- **An orchestrating model** (Claude, "Fable" tier) writes the doctrine,
  the sprint briefs, splits the work, launches the other agents, verifies
  their output, deploys to a throw-away development instance, tags and
  publishes releases, and reports to the maintainer. It rarely writes code
  itself; when it does, the commit says so.
- **Coding agents** (Claude Opus for the core, Sonnet for the periphery):
  one agent per sprint and per repository, each in its own git worktree,
  with no access to the maintainer's home instance.
- **A specification agent** writes, before any code, the ADR, the addendum
  to the frozen public contract and the acceptance tests — which must fail.
- **A reviewing agent with a fresh context** — it has not seen the brief
  nor the coder — reads the diff and returns go / no-go with numbered
  findings. Every release so far had at least one no-go fixed before
  publication.
- **Read-only exploration agents** inventory the code base, compare with
  neighbouring projects and brainstorm.

## The sprint cycle

brief → spec (ADR + contract + failing acceptance tests) → code (tests
first) → independent review → fixes → second review → end-to-end run on a
development Home Assistant instance (Docker, fixtures, no real data) →
merge → tag → release → report to the maintainer.

## Rules every agent works under

- **Native first.** Any claim about Home Assistant behaviour cites the file
  in a local clone of the targeted core version (2026.9.1 today). A wrong
  claim was caught exactly this way once.
- **Frozen public contract.** Every change to a public name or behaviour
  goes through a numbered ADR and a contract test.
- **Refusals raise** a translated `ServiceValidationError`; nothing fails
  silently.
- **en / fr / es from day one.** Spanish is machine-translated and labelled
  as such until a native speaker reviews it.
- **Nothing personal in the repository**: no first names, no details of
  the maintainer's infrastructure.
- **Nothing on the maintainer's production instance** without their
  explicit agreement; development happens on a disposable instance.
- **Merge only on green CI** — a rule broken once, on a formatting job,
  stated and repaired the same morning.
- **One agent per worktree**, conventional commits, a `Co-Authored-By`
  trailer naming the model on every commit.

## Honest limits

- All code and all documentation are model-generated; the review is also a
  model. The only human tests are the maintainer's on real devices, and
  `docs/known-issues.md` says plainly which paths were never exercised on
  hardware.
- A README can contain a mistake nobody has seen. Reports to the
  maintainer say what was verified, how, and what was not.
- Issues and pull requests from humans are read by the maintainer, and
  answered either by them or by an agent under their supervision; the
  answer says which.

If you find this unacceptable for your installation, that is a legitimate
choice; this page exists so that it can be an informed one.
