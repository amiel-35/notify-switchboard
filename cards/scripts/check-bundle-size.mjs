#!/usr/bin/env node
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { gzipSync } from "node:zlib";

const BUDGET_BYTES = 60 * 1024; // 60 kB gzip, per the repository's CI budget.
const bundlePath = fileURLToPath(
  new URL(
    "../../custom_components/notify_switchboard/www/notify-switchboard-cards.js",
    import.meta.url,
  ),
);

let raw;
try {
  raw = readFileSync(bundlePath);
} catch {
  console.error(`Bundle not found at ${bundlePath}. Run "npm run build" first.`);
  process.exit(1);
}

const gzipSize = gzipSync(raw).length;
const kb = (bytes) => (bytes / 1024).toFixed(2);

console.log(
  `Bundle: ${kb(raw.length)} kB raw, ${kb(gzipSize)} kB gzip (budget: ${kb(BUDGET_BYTES)} kB gzip)`,
);

if (gzipSize > BUDGET_BYTES) {
  console.error(`Bundle size budget exceeded by ${kb(gzipSize - BUDGET_BYTES)} kB.`);
  process.exit(1);
}
