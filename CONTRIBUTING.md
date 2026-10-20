# Contributing

Thanks for considering a contribution to Notify Switchboard.

## Ground rules

- **English only** in code, comments, commit messages, and documentation.
  Translation files (`translations/*.json`, `cards/src/i18n/*.ts`) are the
  exception.
- **Pull requests only.** `main` is protected; nothing is pushed directly.
  One PR = one reviewed increment.
- **Conventional commits.** Prefix commit subjects with `feat:`, `fix:`,
  `docs:`, `test:`, `chore:`, `refactor:`, or `ci:`, e.g.
  `feat: add snooze duration to options flow`.
- **Tests are required** for any behavioral change: config flow changes,
  new notify data handled, new entities or services. CI must be green
  (hassfest, HACS validation, lint, tests, cards) before a PR is merged.
- **No product decisions specific to one household.** Classes, persons, and
  rules are configuration, not code (see `docs/ARCHITECTURE.md`).

## Development setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements_dev.txt
```

```bash
ruff format --check .
ruff check .
mypy custom_components/notify_switchboard
pytest --cov=custom_components.notify_switchboard
```

## The dashboard cards

The cards' sources live in `cards/` (TypeScript, Lit 3, Vite). The build
lands in `custom_components/notify_switchboard/www/` and is **committed**:
it is what the release zip ships, and CI fails when it does not match the
sources. Change a card, rebuild, commit both.

```bash
cd cards
npm install
npm run dev          # rebuilds the bundle on every change
npm run lint
npm run format:check
npm run typecheck
npm test
npm run build
npm run size         # <= 60 kB gzip
```

The cards carry the integration's version: bump `cards/package.json` with
`manifest.json` (a test checks they match), then rebuild.

Code style for the cards:

- TypeScript strict mode, no `any` without a very good reason.
- Lit 3 components, no decorators (see `cards/src/cards/*/*.ts`: a
  `static properties` class field, plain class fields for private state).
- Only hand-written types from `cards/src/ha-types.ts` for the `hass`
  object; do not add `custom-card-helpers`.
- Only theme CSS variables for color, never hardcoded hex values.
- Every interactive control needs a `>=48px` touch target, a visible focus
  state and an `aria-label`. Never rely on color alone to convey state.
- New user-facing strings go in all three `cards/src/i18n/*.ts` files
  (`en.ts` is the source; `fr.ts` and `es.ts` are typed against its keys).
- Component tests use Vitest and jsdom with a fake `hass`
  (`cards/test/fake-hass.ts`). A feature that calls a
  `notify_switchboard.*` action is tested with the action present and
  absent.

### Screenshots

The screenshots in `docs/cards.md` come from a live Home Assistant
instance. To refresh them, have a development instance reachable (default
`http://localhost:18124`) with a `trusted_networks` auth provider and a
dashboard (default `/cards-e2e/e2e`) rendering one alerts card in `full`
mode, one in `compact` mode and one silence tile; install Chromium once with
`npx playwright install chromium`; then run `node scripts/screenshots.mjs`
from `cards/`. `HA_BASE_URL`, `HA_DASHBOARD_PATH` and
`PLAYWRIGHT_CHROMIUM_PATH` override the defaults. The files land in
`docs/cards/screenshots/`.

## Adding or changing user-facing strings

Update `custom_components/notify_switchboard/strings.json` (the source of
truth, English) and `translations/en.json` together, then update
`translations/fr.json` and `translations/es.json` with real, natural
translations — not machine-literal ones. `tests/test_translations.py`
checks that all three files expose the same set of keys.

## Reporting issues

Open an issue with your Home Assistant version, the integration version,
relevant logs (`custom_components.notify_switchboard: debug` in
`logger:`), and steps to reproduce.
