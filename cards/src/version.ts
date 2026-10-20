/**
 * Build-time constant injected by Vite (`define` in `vite.config.ts`) from
 * `package.json`. Declared locally rather than in a global `.d.ts` so the
 * fallback keeps working in any context where the define is not applied.
 */
declare const __CARD_VERSION__: string;

export const CARD_VERSION: string =
  typeof __CARD_VERSION__ === "string" ? __CARD_VERSION__ : "0.0.0-dev";
