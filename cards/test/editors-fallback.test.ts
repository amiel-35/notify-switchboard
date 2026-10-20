import { describe, expect, it } from "vitest";
import "../src/cards/alerts-card/switchboard-alerts-card-editor";
import "../src/cards/silence-tile/switchboard-silence-tile-editor";
import type { LovelaceCardConfig } from "../src/ha-types";
import { createFakeHass } from "./fake-hass";

/**
 * This file deliberately never registers a stub `ha-form`: it asserts what
 * the editors do when the Home Assistant frontend's runtime globals are
 * absent. Custom element registrations cannot be undone, so it must stay a
 * separate file from `editors.test.ts`.
 */
async function mountEditor(tag: string, config: LovelaceCardConfig) {
  const editor = document.createElement(tag) as HTMLElement & {
    hass?: unknown;
    setConfig: (c: LovelaceCardConfig) => void;
    updateComplete: Promise<unknown>;
  };
  editor.setConfig(config);
  editor.hass = createFakeHass({});
  document.body.appendChild(editor);
  await editor.updateComplete;
  return editor;
}

describe("editors without the ha-form runtime global", () => {
  it("is a precondition that ha-form is not registered here", () => {
    expect(customElements.get("ha-form")).toBeUndefined();
  });

  for (const [tag, type] of [
    ["switchboard-alerts-card-editor", "custom:switchboard-alerts-card"],
    ["switchboard-silence-tile-editor", "custom:switchboard-silence-tile"],
  ] as const) {
    it(`${tag} explains how to edit the card instead of rendering an empty box`, async () => {
      const editor = await mountEditor(tag, { type });

      expect(editor.shadowRoot?.querySelector("ha-form")).toBeNull();
      const fallback = editor.shadowRoot?.querySelector(".fallback");
      expect(fallback?.textContent).toContain("ha-form");
      expect(fallback?.textContent).toContain("YAML");

      editor.remove();
    });
  }
});
