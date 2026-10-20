import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import "../src/cards/alerts-card/switchboard-alerts-card-editor";
import "../src/cards/silence-tile/switchboard-silence-tile-editor";
import type { SwitchboardAlertsCardEditor } from "../src/cards/alerts-card/switchboard-alerts-card-editor";
import type { SwitchboardSilenceTileEditor } from "../src/cards/silence-tile/switchboard-silence-tile-editor";
import type { LovelaceCardConfig } from "../src/ha-types";
import { createFakeHass } from "./fake-hass";

/**
 * `ha-form` is a runtime global of the Home Assistant frontend. Tests run
 * without it, so a minimal stand-in is registered here — that is what the
 * editors feature-detect with `customElements.get("ha-form")`.
 */
beforeAll(() => {
  if (!customElements.get("ha-form")) {
    customElements.define("ha-form", class extends HTMLElement {});
  }
});

const elements: HTMLElement[] = [];

afterEach(() => {
  for (const element of elements) element.remove();
  elements.length = 0;
});

async function mountEditor<T extends HTMLElement>(tag: string, config: LovelaceCardConfig) {
  const editor = document.createElement(tag) as T & {
    hass?: unknown;
    setConfig: (c: LovelaceCardConfig) => void;
    updateComplete: Promise<unknown>;
  };
  editor.setConfig(config);
  editor.hass = createFakeHass({});
  document.body.appendChild(editor);
  elements.push(editor);
  await editor.updateComplete;
  return editor;
}

/** Emits what `ha-form` emits when the user edits a field. */
function emitFormValue(editor: HTMLElement, value: Record<string, unknown>): void {
  const form = editor.shadowRoot?.querySelector("ha-form");
  expect(form, "ha-form should be rendered").not.toBeNull();
  form?.dispatchEvent(new CustomEvent("value-changed", { detail: { value }, bubbles: false }));
}

function captureConfig(editor: HTMLElement): () => Record<string, unknown> | undefined {
  let captured: Record<string, unknown> | undefined;
  editor.addEventListener("config-changed", (event) => {
    captured = (event as CustomEvent<{ config: Record<string, unknown> }>).detail.config;
  });
  return () => captured;
}

describe("switchboard-alerts-card-editor", () => {
  const base: LovelaceCardConfig = { type: "custom:switchboard-alerts-card" };

  it("renders an ha-form with the expected selectors", async () => {
    const editor = await mountEditor<SwitchboardAlertsCardEditor>(
      "switchboard-alerts-card-editor",
      base,
    );
    const form = editor.shadowRoot?.querySelector("ha-form") as HTMLElement & {
      schema?: Array<{ name: string; selector: Record<string, unknown> }>;
    };
    expect(form).not.toBeNull();

    const schema = form.schema ?? [];
    const byName = Object.fromEntries(schema.map((entry) => [entry.name, entry.selector]));
    expect(byName.entities).toEqual({ entity: { domain: "alert", multiple: true } });
    expect(byName.person).toEqual({ entity: { domain: "person" } });
    expect(byName.target_map).toEqual({ object: {} });
    expect(byName.show_acknowledged).toEqual({ boolean: {} });
    expect(byName.person_picker).toEqual({ boolean: {} });
    expect(Object.keys(byName.mode as Record<string, unknown>)).toEqual(["select"]);
  });

  it("translates the field labels via computeLabel", async () => {
    const editor = await mountEditor<SwitchboardAlertsCardEditor>(
      "switchboard-alerts-card-editor",
      base,
    );
    const form = editor.shadowRoot?.querySelector("ha-form") as HTMLElement & {
      computeLabel?: (schema: { name: string }) => string;
    };
    expect(form.computeLabel?.({ name: "person" })).toBe("Person entity");
    expect(form.computeLabel?.({ name: "mode" })).toBe("Mode");
    expect(form.computeLabel?.({ name: "person_picker" })).toBe("Ask who a snooze is for (kiosk)");
  });

  it("marks the options router 0.7.0 derives as optional, and only those", async () => {
    const editor = await mountEditor<SwitchboardAlertsCardEditor>(
      "switchboard-alerts-card-editor",
      base,
    );
    const form = editor.shadowRoot?.querySelector("ha-form") as HTMLElement & {
      computeHelper?: (schema: { name: string }) => string;
    };
    for (const name of ["target_map", "snooze_minutes"]) {
      expect(form.computeHelper?.({ name })).toMatch(/Optional since Notify Switchboard 0\.7\.0/);
      expect(form.computeHelper?.({ name })).toMatch(/sensor\.switchboard_routing_table/);
    }
    for (const name of ["title", "entities", "mode", "person", "person_picker"]) {
      expect(form.computeHelper?.({ name })).toBe("");
    }
  });

  it("leaves the snooze durations field empty rather than pre-filling the defaults", async () => {
    // A pre-filled field would be saved back as a permanent override of
    // every target's own `snooze_minutes`.
    const editor = await mountEditor<SwitchboardAlertsCardEditor>(
      "switchboard-alerts-card-editor",
      base,
    );
    const form = editor.shadowRoot?.querySelector("ha-form") as HTMLElement & {
      data?: Record<string, unknown>;
    };
    expect(form.data?.snooze_minutes).toEqual([]);
  });

  it("emits a config-changed payload without empty keys", async () => {
    const editor = await mountEditor<SwitchboardAlertsCardEditor>(
      "switchboard-alerts-card-editor",
      base,
    );
    const config = captureConfig(editor);

    emitFormValue(editor, {
      title: "",
      entities: [],
      target_map: {},
      person: "",
      mode: "compact",
      show_acknowledged: false,
      snooze_minutes: ["15", "60"],
    });

    expect(config()).toEqual({
      type: "custom:switchboard-alerts-card",
      mode: "compact",
      show_acknowledged: false,
      snooze_minutes: [15, 60],
    });
    expect(config()).not.toHaveProperty("title");
    expect(config()).not.toHaveProperty("entities");
    expect(config()).not.toHaveProperty("target_map");
    expect(config()).not.toHaveProperty("person");
  });

  it("keeps the values that were actually set, coercing snooze durations to numbers", async () => {
    const editor = await mountEditor<SwitchboardAlertsCardEditor>(
      "switchboard-alerts-card-editor",
      base,
    );
    const config = captureConfig(editor);

    emitFormValue(editor, {
      title: "Household alerts",
      entities: ["alert.leak"],
      target_map: { "alert.leak": "leak" },
      person: "person.alice",
      mode: "full",
      show_acknowledged: true,
      snooze_minutes: ["15", "not-a-number", "0", "480"],
    });

    expect(config()).toEqual({
      type: "custom:switchboard-alerts-card",
      title: "Household alerts",
      entities: ["alert.leak"],
      target_map: { "alert.leak": "leak" },
      person: "person.alice",
      mode: "full",
      show_acknowledged: true,
      snooze_minutes: [15, 480],
    });
  });

  it("emits a config the card itself accepts", async () => {
    const editor = await mountEditor<SwitchboardAlertsCardEditor>(
      "switchboard-alerts-card-editor",
      base,
    );
    const config = captureConfig(editor);
    emitFormValue(editor, {
      entities: ["alert.leak"],
      mode: "compact",
      snooze_minutes: ["15"],
    });

    const { SwitchboardAlertsCard } =
      await import("../src/cards/alerts-card/switchboard-alerts-card");
    const card = new SwitchboardAlertsCard();
    expect(() => card.setConfig(config() as LovelaceCardConfig)).not.toThrow();
  });

  it("does not leak the ha-form value-changed event out of the editor", async () => {
    const editor = await mountEditor<SwitchboardAlertsCardEditor>(
      "switchboard-alerts-card-editor",
      base,
    );
    const listener = vi.fn();
    editor.addEventListener("value-changed", listener);
    emitFormValue(editor, { mode: "compact" });
    expect(listener).not.toHaveBeenCalled();
  });
});

describe("switchboard-silence-tile-editor", () => {
  const base: LovelaceCardConfig = { type: "custom:switchboard-silence-tile" };

  it("renders an ha-form with a person and time selector", async () => {
    const editor = await mountEditor<SwitchboardSilenceTileEditor>(
      "switchboard-silence-tile-editor",
      base,
    );
    const form = editor.shadowRoot?.querySelector("ha-form") as HTMLElement & {
      schema?: Array<{ name: string; selector: Record<string, unknown> }>;
    };
    const byName = Object.fromEntries((form.schema ?? []).map((e) => [e.name, e.selector]));
    expect(byName.person).toEqual({ entity: { domain: "person" } });
    expect(byName.wake_time).toEqual({ time: {} });
  });

  it("normalises the time selector's HH:MM:SS down to HH:MM and drops empty keys", async () => {
    const editor = await mountEditor<SwitchboardSilenceTileEditor>(
      "switchboard-silence-tile-editor",
      base,
    );
    const config = captureConfig(editor);

    emitFormValue(editor, { person: "person.alice", wake_time: "07:30:00", title: "" });

    expect(config()).toEqual({
      type: "custom:switchboard-silence-tile",
      person: "person.alice",
      wake_time: "07:30",
    });
  });

  it("emits a config the tile itself accepts", async () => {
    const editor = await mountEditor<SwitchboardSilenceTileEditor>(
      "switchboard-silence-tile-editor",
      base,
    );
    const config = captureConfig(editor);
    emitFormValue(editor, { person: "person.alice", wake_time: "07:30:00" });

    const { SwitchboardSilenceTile } =
      await import("../src/cards/silence-tile/switchboard-silence-tile");
    const tile = new SwitchboardSilenceTile();
    expect(() => tile.setConfig(config() as LovelaceCardConfig)).not.toThrow();
  });
});

describe("switchboard-silence-tile-editor wake_time helper", () => {
  it("marks wake_time as optional since router 0.7.0, and nothing else", async () => {
    const editor = await mountEditor<SwitchboardSilenceTileEditor>(
      "switchboard-silence-tile-editor",
      { type: "custom:switchboard-silence-tile", person: "person.alice" },
    );
    const form = editor.shadowRoot?.querySelector("ha-form") as HTMLElement & {
      computeHelper?: (schema: { name: string }) => string;
    };
    expect(form.computeHelper?.({ name: "wake_time" })).toMatch(
      /Optional since Notify Switchboard 0\.7\.0/,
    );
    expect(form.computeHelper?.({ name: "person" })).toBe("");
    expect(form.computeHelper?.({ name: "title" })).toBe("");
  });
});
