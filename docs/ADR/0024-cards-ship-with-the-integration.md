# ADR 0024: The dashboard cards ship with the integration

Date: 2026-10-20

## Status

Accepted (maintainer's go on 2026-10-20, after the HACS default-store review).

## Context

Up to 0.9.0 the two dashboard cards (`switchboard-alerts-card`,
`switchboard-silence-tile`) lived in their own repository,
`amiel-35/notify-switchboard-cards` (cards 0.2.0), installed from HACS as a
separate *Dashboard* download, with its own version and a router version
matrix to say which card features each router release unlocked.

Both repositories were submitted to the HACS default store. The HACS
reviewer closed the card submission and requested changes on the
integration's: a card that exists to serve one integration, by the same
author, belongs inside that integration, so users get both in a single
install and the two can never drift apart in version. The request is
specific: put the built JavaScript under
`custom_components/notify_switchboard/www/`, serve it from its own static
path, register it as a dashboard resource during setup, release, and ask for
review again.

The cards already depend on this integration and nothing else: the silence
tile only works with its entities and actions, and the alerts card is built
around its routing table. The version matrix existed only because the two
could drift.

## Decision

### 0. Guard-rails, unchanged

- The router stays a pure notify proxy (ADR-0002): serving a static file and
  writing one dashboard resource send no notification and call no output.
- No service, entity, `data` key, drop reason or `event.switchboard_delivery`
  type is added or removed. The config entry and store versions do not move.

### 1. One repository, one version

The cards' sources move to `cards/` in this repository, unchanged but for
paths and the points below. Their build lands in
`custom_components/notify_switchboard/www/` (the bundle and its source map)
and is **committed**: the release workflow zips `custom_components/` as it
is, so the committed file is what ships, and a CI job rebuilds it and fails
when it differs from the sources. The cards take the integration's version
(`cards/package.json` follows `manifest.json`, checked by a test), so the
banner a browser console prints names the integration release.

The separate repository is archived once 0.10.0 is out, with a README that
points here. Its history stays there; its changelog is copied to
`docs/history/cards-changelog.md` and its README becomes `docs/cards.md`.

### 2. Served by the integration

`async_setup` registers one static path, `/notify_switchboard` →
`www/`, with cache headers (`homeassistant/components/http/server.py`:
`StaticPathConfig`, `HomeAssistantHTTP.async_register_static_paths`). It
lives in `async_setup`, not in the entry: the entry reloads on every options
change, and a path cannot be registered twice. Without `http` (a test
instance) nothing is registered.

### 3. Registered as a dashboard resource

On every entry setup, idempotently:

- **Resources managed from the UI** (`ResourceStorageCollection`,
  `homeassistant/components/lovelace/resources.py`): exactly one `module`
  resource whose path is `/notify_switchboard/notify-switchboard-cards.js`,
  with `?v=<integration version>` as its query string. A missing one is
  created; one at another version is updated in place; duplicates are
  deleted. The version in the URL is the cache-buster that long-lived cache
  headers need.
- **Resources written in YAML** (`ResourceYAMLCollection`): the integration
  cannot and does not edit the user's YAML. The same URL is loaded as an
  extra frontend module (`homeassistant/components/frontend/__init__.py`:
  `add_extra_js_url`), so the cards work there too, at the cost of loading
  on every page rather than only on dashboards.
- **No dashboards** (`lovelace` not loaded): nothing is done.

Registering the cards never fails the entry, nor `async_setup`: an error is
logged as a warning and setup goes on. The resource is registered after the
router is wired, and an exception there would leave the entry in
`SETUP_ERROR` with its platforms and services still loaded, which the next
reload would trip over. Notifications matter more than the cards.

`async_remove_entry` removes the resource (or the extra module), so a
dashboard does not keep loading a file nobody serves.

`http`, `frontend` and `lovelace` are `after_dependencies`, not
`dependencies`: every real installation loads them, the code handles their
absence, and the test suite does not need the frontend package.

### 4. The old resource is reported, not removed

A dashboard that still loads the former repository's bundle — any resource
named `notify-switchboard-cards.js` other than ours: `/hacsfiles/…`,
`/local/community/…`, or a copy under `/local/` — defines
the same elements from an older bundle, and whichever the browser loads
first wins. That resource belongs to HACS, which removes it when the old
repository is uninstalled; deleting it here would leave HACS believing it
is installed. A `repairs` issue, `legacy_cards_resource`, says what to
remove and where; it is deleted on the next setup that no longer finds the
resource, and with the entry.

The cards stay usable when both bundles load: every
`customElements.define` is guarded, and the new bundle's card-picker
entries too. The old bundle's are not, so while it is loaded the picker may
list a card twice.

### 5. What is not done

- No card is rewritten: their behaviour, options and tests are the 0.2.0
  ones. Their graceful fallbacks for an older router stay in the code; they
  cost nothing and keep a stale browser cache harmless.
- No option to turn the resource off. A household that does not want the
  cards can ignore them; a dashboard that does not name them loads a 22 kB
  (gzip) module and renders nothing from it.

## Contract changes (docs/contract.md, v0.10 addendum)

The bundle's URL, the two card types (`custom:switchboard-alerts-card`,
`custom:switchboard-silence-tile`) and one `repairs` key
(`legacy_cards_resource`).

## Consequences

- One install, one version, one changelog. The card version matrix is gone.
- The repository gains a Node toolchain under `cards/` and one CI workflow
  (`.github/workflows/cards.yml`). The review checklist forbids workflow
  edits outside a CI sprint; this one is accepted because a committed build
  with no check that it matches its sources would ship stale cards
  silently. It adds a job; it changes no existing one.
- Anyone who installed the cards from the old repository has to remove them
  from HACS once; the repair and the changelog say so. Their card
  configurations need no change.
- The release zip grows by the bundle and its source map (about 280 kB
  uncompressed).
