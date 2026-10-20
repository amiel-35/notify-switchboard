#!/usr/bin/env node
// Captures the README screenshots against a real, running Home Assistant
// dev instance. See CONTRIBUTING.md "Screenshots" for how to run this.
//
// Requirements:
//   - A Home Assistant instance reachable at HA_BASE_URL (default
//     http://localhost:18124) with a `trusted_networks` auth provider that
//     allows bypassing login from wherever this script runs — no token or
//     login flow is driven here.
//   - A dashboard at HA_DASHBOARD_PATH (default /cards-e2e/e2e) that renders
//     one `switchboard-alerts-card` in `full` mode, one in `compact` mode,
//     and at least one `switchboard-silence-tile`.
//   - `playwright-core` installed (devDependency) and a Chromium build
//     already cached by a prior `npx playwright install` on this machine
//     (this script never downloads a browser itself).
import { chromium } from "playwright-core";
import { existsSync, mkdirSync, statSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { globSync } from "node:fs";

const __dirname = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(__dirname, "..");
const OUT_DIR = resolve(ROOT, "../docs/cards/screenshots");

const BASE_URL = process.env.HA_BASE_URL ?? "http://localhost:18124";
const DASHBOARD_PATH = process.env.HA_DASHBOARD_PATH ?? "/cards-e2e/e2e";
const DASHBOARD_URL = new URL(DASHBOARD_PATH, BASE_URL).toString();

const DESKTOP_VIEWPORT = { width: 1280, height: 800 };
const MOBILE_VIEWPORT = { width: 480, height: 900 };

function findChromiumExecutable() {
  if (process.env.PLAYWRIGHT_CHROMIUM_PATH) return process.env.PLAYWRIGHT_CHROMIUM_PATH;

  const cacheRoot = join(process.env.HOME ?? "", "Library/Caches/ms-playwright");
  const candidates = globSync("chromium-*/chrome-mac*/**/Chromium.app/Contents/MacOS/Chromium", {
    cwd: cacheRoot,
  }).concat(
    globSync(
      "chromium-*/chrome-mac*/**/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing",
      {
        cwd: cacheRoot,
      },
    ),
  );

  if (candidates.length === 0) {
    throw new Error(
      `No cached Chromium found under ${cacheRoot}. This script deliberately never runs ` +
        `"playwright install" — point PLAYWRIGHT_CHROMIUM_PATH at an existing browser binary instead.`,
    );
  }

  // Prefer the newest revision if several are cached.
  candidates.sort();
  const execPath = join(cacheRoot, candidates[candidates.length - 1]);
  if (!existsSync(execPath)) {
    throw new Error(`Resolved Chromium path does not exist: ${execPath}`);
  }
  return execPath;
}

async function waitForDashboardReady(page) {
  // The card custom elements must be upgraded and attached...
  await page
    .locator("switchboard-alerts-card")
    .first()
    .waitFor({ state: "attached", timeout: 15_000 });
  await page
    .locator("switchboard-silence-tile")
    .first()
    .waitFor({ state: "attached", timeout: 15_000 });
  // ...and any in-flight history/logbook fetch the alerts card kicks off on
  // first render must have resolved (it briefly shows a "Loading data..."
  // placeholder with a spinner). Wait on the spinner element, not on the
  // text, so this does not depend on the UI language.
  await page
    .locator("switchboard-alerts-card ha-spinner, switchboard-alerts-card ha-circular-progress")
    .first()
    .waitFor({ state: "detached", timeout: 10_000 })
    .catch(() => {
      /* never appeared — fine, nothing to wait out */
    });
  await page.waitForLoadState("networkidle");
  // Let card_mod/theme transitions and the ha-card raise-on-hover settle.
  await page.waitForTimeout(500);
}

// The README documents the English UI. The HA frontend takes its language from
// the user's profile (or the browser), so force it per context: the frontend
// honours a JSON-encoded `selectedLanguage` key in localStorage.
async function newEnglishContext(browser, options) {
  const ctx = await browser.newContext({ locale: "en-US", ...options });
  // This callback is serialised and evaluated inside the page, not in Node.
  await ctx.addInitScript(() => {
    /* global window */
    window.localStorage.setItem("selectedLanguage", JSON.stringify("en"));
  });
  return ctx;
}

async function shootElement(locator, path) {
  await locator.scrollIntoViewIfNeeded();
  await locator.screenshot({ path });
  assertNonEmpty(path);
}

function assertNonEmpty(path) {
  const { size } = statSync(path);
  if (size < 500) {
    throw new Error(`Screenshot at ${path} is suspiciously small (${size} bytes) — likely blank.`);
  }
}

async function main() {
  mkdirSync(OUT_DIR, { recursive: true });
  const executablePath = findChromiumExecutable();
  console.log(`Using Chromium at ${executablePath}`);
  console.log(`Dashboard: ${DASHBOARD_URL}`);

  const browser = await chromium.launch({ executablePath, headless: true });

  try {
    // --- Light theme, desktop ---------------------------------------
    const lightCtx = await newEnglishContext(browser, {
      viewport: DESKTOP_VIEWPORT,
      colorScheme: "light",
    });
    const lightPage = await lightCtx.newPage();
    await lightPage.goto(DASHBOARD_URL, { waitUntil: "networkidle" });
    await waitForDashboardReady(lightPage);

    const alertsCards = lightPage.locator("switchboard-alerts-card");
    const tiles = lightPage.locator("switchboard-silence-tile");

    await shootElement(alertsCards.nth(0), join(OUT_DIR, "alerts-card-full.png"));
    await shootElement(alertsCards.nth(1), join(OUT_DIR, "alerts-card-compact.png"));
    await shootElement(tiles.nth(0), join(OUT_DIR, "silence-tile.png"));

    const dashboardPath = join(OUT_DIR, "dashboard.png");
    await lightPage.screenshot({ path: dashboardPath, fullPage: true });
    assertNonEmpty(dashboardPath);

    await lightCtx.close();

    // --- Dark theme, desktop ------------------------------------------
    const darkCtx = await newEnglishContext(browser, {
      viewport: DESKTOP_VIEWPORT,
      colorScheme: "dark",
    });
    const darkPage = await darkCtx.newPage();
    await darkPage.goto(DASHBOARD_URL, { waitUntil: "networkidle" });
    await waitForDashboardReady(darkPage);

    const dashboardDarkPath = join(OUT_DIR, "dashboard-dark.png");
    await darkPage.screenshot({ path: dashboardDarkPath, fullPage: true });
    assertNonEmpty(dashboardDarkPath);

    await darkCtx.close();

    // --- Light theme, mobile viewport ----------------------------------
    const mobileCtx = await newEnglishContext(browser, {
      viewport: MOBILE_VIEWPORT,
      colorScheme: "light",
    });
    const mobilePage = await mobileCtx.newPage();
    await mobilePage.goto(DASHBOARD_URL, { waitUntil: "networkidle" });
    await waitForDashboardReady(mobilePage);

    const dashboardMobilePath = join(OUT_DIR, "dashboard-mobile.png");
    await mobilePage.screenshot({ path: dashboardMobilePath, fullPage: true });
    assertNonEmpty(dashboardMobilePath);

    await mobileCtx.close();
  } finally {
    await browser.close();
  }

  console.log(`Screenshots written to ${OUT_DIR}`);
}

main().catch((err) => {
  console.error(err);
  process.exitCode = 1;
});
