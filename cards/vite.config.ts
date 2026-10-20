/// <reference types="vitest/config" />
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { defineConfig } from "vite";

const entry = fileURLToPath(new URL("./src/index.ts", import.meta.url));

// The bundle ships inside the integration: Home Assistant serves this
// directory and registers the file as a dashboard resource (ADR-0024).
const outDir = fileURLToPath(
  new URL("../custom_components/notify_switchboard/www", import.meta.url),
);

const pkg = JSON.parse(
  readFileSync(fileURLToPath(new URL("./package.json", import.meta.url)), "utf8"),
) as { version: string };

export default defineConfig({
  define: {
    // Consumed by src/version.ts for the load banner.
    __CARD_VERSION__: JSON.stringify(pkg.version),
  },
  build: {
    target: "es2021",
    sourcemap: true,
    minify: "esbuild",
    outDir,
    // The directory holds nothing but this build; outside the Vite root it
    // is only emptied when asked.
    emptyOutDir: true,
    lib: {
      entry,
      formats: ["es"],
      fileName: () => "notify-switchboard-cards.js",
    },
    rollupOptions: {
      output: {
        inlineDynamicImports: true,
      },
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    include: ["test/**/*.test.ts"],
    setupFiles: ["test/setup.ts"],
  },
});
