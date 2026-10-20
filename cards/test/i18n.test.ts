import { describe, expect, it } from "vitest";
import { en } from "../src/i18n/en";
import { fr } from "../src/i18n/fr";
import { es } from "../src/i18n/es";
import { t } from "../src/i18n";
import { createFakeHass } from "./fake-hass";

describe("translation tables", () => {
  it("share exactly the same key set", () => {
    const keys = Object.keys(en).sort();
    expect(Object.keys(fr).sort()).toEqual(keys);
    expect(Object.keys(es).sort()).toEqual(keys);
  });

  it("has no empty translation", () => {
    for (const table of [en, fr, es]) {
      for (const [key, value] of Object.entries(table)) {
        expect(value.trim(), key).not.toBe("");
      }
    }
  });

  it("uses the reviewed French wording", () => {
    expect(fr["alerts.action.snooze"]).toBe("Reporter");
    expect(fr["silence.action.clear"]).toBe("Lever le silence");
    expect(fr["silence.action.clear_snoozes"]).toBe("Effacer les reports");
    expect(fr["silence.state.silenced"]).toBe("En silence");
  });

  it("falls back to English for an unsupported language", () => {
    const hass = createFakeHass({ language: "de" });
    expect(t(hass, "alerts.title")).toBe(en["alerts.title"]);
  });

  it("substitutes placeholders", () => {
    const hass = createFakeHass({ language: "fr" });
    expect(t(hass, "alerts.action.snooze_minutes", { minutes: 15 })).toBe("Reporter 15 min");
  });
});
