import type { HomeAssistant } from "../ha-types";
import { en, type TranslationKey } from "./en";
import { fr } from "./fr";
import { es } from "./es";

const LANGUAGES: Record<string, Record<TranslationKey, string>> = {
  en,
  fr,
  es,
};

function pickLanguage(hass: HomeAssistant | undefined): string {
  const language = hass?.locale?.language ?? hass?.language ?? "en";
  return language.toLowerCase().split("-")[0] ?? "en";
}

/**
 * Translates `key` for the current `hass.locale.language`, falling back to
 * English for unsupported languages and substituting any `{placeholder}`
 * tokens found in `vars`.
 */
export function t(
  hass: HomeAssistant | undefined,
  key: TranslationKey,
  vars?: Record<string, string | number>,
): string {
  const language = pickLanguage(hass);
  const table = LANGUAGES[language] ?? en;
  let text = table[key] ?? en[key] ?? key;

  if (vars) {
    for (const [name, value] of Object.entries(vars)) {
      text = text.replaceAll(`{${name}}`, String(value));
    }
  }
  return text;
}

export type { TranslationKey };
