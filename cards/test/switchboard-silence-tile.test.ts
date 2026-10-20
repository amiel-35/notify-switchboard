import { afterEach, describe, expect, it, vi } from "vitest";
import "../src/cards/silence-tile/switchboard-silence-tile";
import type { SwitchboardSilenceTile } from "../src/cards/silence-tile/switchboard-silence-tile";
import type { SwitchboardSilenceTileConfig } from "../src/types";
import { ROUTING_TABLE_ENTITY } from "../src/types";
import { createFakeHass, fakeEntity, withUpdatedStates } from "./fake-hass";

async function mountTile(
  config: SwitchboardSilenceTileConfig,
  hass: ReturnType<typeof createFakeHass>,
): Promise<SwitchboardSilenceTile> {
  const tile = document.createElement("switchboard-silence-tile") as SwitchboardSilenceTile;
  tile.setConfig(config);
  tile.hass = hass;
  document.body.appendChild(tile);
  await tile.updateComplete;
  return tile;
}

function buttonWithText(tile: SwitchboardSilenceTile, text: string): HTMLButtonElement | undefined {
  const buttons = Array.from(tile.shadowRoot?.querySelectorAll("button") ?? []);
  return buttons.find((b) => b.textContent?.trim() === text) as HTMLButtonElement | undefined;
}

describe("switchboard-silence-tile states", () => {
  let tiles: SwitchboardSilenceTile[] = [];

  afterEach(() => {
    for (const tile of tiles) tile.remove();
    tiles = [];
  });

  it("prompts for configuration when no person is set", async () => {
    const hass = createFakeHass({});
    const tile = await mountTile({ type: "custom:switchboard-silence-tile", person: "" }, hass);
    tiles.push(tile);

    expect(tile.shadowRoot?.textContent).toContain("Select a person in the card configuration");
  });

  it("shows the silenced chip and snooze count for a configured person", async () => {
    const hass = createFakeHass({
      states: [
        fakeEntity("person.alice", "home", { attributes: { friendly_name: "Alice" } }),
        fakeEntity("binary_sensor.alice_silenced", "on"),
        fakeEntity("sensor.alice_active_snoozes", "2"),
        fakeEntity("sensor.alice_last_notification", "unknown"),
      ],
    });
    const tile = await mountTile(
      { type: "custom:switchboard-silence-tile", person: "person.alice" },
      hass,
    );
    tiles.push(tile);

    const text = tile.shadowRoot?.textContent ?? "";
    expect(text).toContain("Silenced");
    expect(text).toContain("2 active snoozes");
    expect(text).toContain("No notifications yet");
  });

  it("shows 'not silenced' and no active snoozes when the router entities say so", async () => {
    const hass = createFakeHass({
      states: [
        fakeEntity("person.alice", "home", { attributes: { friendly_name: "Alice" } }),
        fakeEntity("binary_sensor.alice_silenced", "off"),
        fakeEntity("sensor.alice_active_snoozes", "0"),
      ],
    });
    const tile = await mountTile(
      { type: "custom:switchboard-silence-tile", person: "person.alice" },
      hass,
    );
    tiles.push(tile);

    const text = tile.shadowRoot?.textContent ?? "";
    expect(text).toContain("Not silenced");
    expect(text).toContain("No active snoozes");
  });

  for (const state of ["unavailable", "unknown"] as const) {
    it(`reports an ${state} snooze sensor as unknown, not as "no snoozes"`, async () => {
      const hass = createFakeHass({
        states: [
          fakeEntity("person.alice", "home"),
          fakeEntity("sensor.alice_active_snoozes", state),
        ],
      });
      const tile = await mountTile(
        { type: "custom:switchboard-silence-tile", person: "person.alice" },
        hass,
      );
      tiles.push(tile);

      const text = tile.shadowRoot?.textContent ?? "";
      expect(text).toContain("Active snoozes: —");
      expect(text).not.toContain("No active snoozes");
    });
  }

  it("reports a missing snooze sensor as unknown too", async () => {
    const hass = createFakeHass({ states: [fakeEntity("person.alice", "home")] });
    const tile = await mountTile(
      { type: "custom:switchboard-silence-tile", person: "person.alice" },
      hass,
    );
    tiles.push(tile);

    expect(tile.shadowRoot?.textContent).toContain("Active snoozes: —");
  });
});

describe("switchboard-silence-tile router service availability", () => {
  let tiles: SwitchboardSilenceTile[] = [];

  afterEach(() => {
    for (const tile of tiles) tile.remove();
    tiles = [];
  });

  it("marks actions aria-disabled (still focusable) and explains why on 0.1.x", async () => {
    const hass = createFakeHass({
      states: [fakeEntity("person.alice", "home")],
      services: {},
    });
    const tile = await mountTile(
      { type: "custom:switchboard-silence-tile", person: "person.alice" },
      hass,
    );
    tiles.push(tile);

    for (const label of ["Silence 1 h", "Until wake", "Clear snoozes", "Lift silence"]) {
      const button = buttonWithText(tile, label);
      expect(button, label).toBeDefined();
      expect(button?.getAttribute("aria-disabled"), label).toBe("true");
      // aria-disabled, not disabled: the control stays reachable.
      expect(button?.disabled, label).toBe(false);
    }

    const hint = tile.shadowRoot?.querySelector(".hint");
    expect(hint?.textContent).toContain("Requires Notify Switchboard ≥ 0.2.0");
    expect(buttonWithText(tile, "Silence 1 h")?.getAttribute("aria-describedby")).toBe(hint?.id);
  });

  it("does nothing when an aria-disabled action is clicked", async () => {
    const hass = createFakeHass({
      states: [fakeEntity("person.alice", "home")],
      services: {},
    });
    const tile = await mountTile(
      { type: "custom:switchboard-silence-tile", person: "person.alice" },
      hass,
    );
    tiles.push(tile);

    buttonWithText(tile, "Silence 1 h")?.click();
    buttonWithText(tile, "Lift silence")?.click();
    await tile.updateComplete;

    expect(hass.callService).not.toHaveBeenCalled();
  });

  it("enables silence actions and calls notify_switchboard.silence once available (0.2.0+)", async () => {
    const hass = createFakeHass({
      states: [fakeEntity("person.alice", "home")],
      services: { notify_switchboard: { silence: {}, unsnooze: {}, unsilence: {} } },
    });
    const tile = await mountTile(
      { type: "custom:switchboard-silence-tile", person: "person.alice", wake_time: "07:00" },
      hass,
    );
    tiles.push(tile);

    const silenceButton = buttonWithText(tile, "Silence 1 h");
    expect(silenceButton?.getAttribute("aria-disabled")).toBe("false");
    silenceButton?.click();
    await tile.updateComplete;

    expect(hass.callService).toHaveBeenCalledWith("notify_switchboard", "silence", {
      person: "person.alice",
      minutes: 60,
    });
    // Every service is present: no "requires 0.2.0" hint.
    expect(tile.shadowRoot?.querySelector(".hint")).toBeNull();
  });

  it("clears snoozes with unsnooze and never invents silence(minutes: 0)", async () => {
    const hass = createFakeHass({
      states: [fakeEntity("person.alice", "home")],
      services: { notify_switchboard: { silence: {}, unsnooze: {}, unsilence: {} } },
    });
    const tile = await mountTile(
      { type: "custom:switchboard-silence-tile", person: "person.alice" },
      hass,
    );
    tiles.push(tile);

    buttonWithText(tile, "Clear snoozes")?.click();
    await tile.updateComplete;

    expect(hass.callService).toHaveBeenCalledWith("notify_switchboard", "unsnooze", {
      person: "person.alice",
    });
    expect(hass.callService).toHaveBeenCalledTimes(1);
    expect(hass.callService).not.toHaveBeenCalledWith("notify_switchboard", "silence", {
      person: "person.alice",
      minutes: 0,
    });
  });

  it("lifts a silence with the dedicated unsilence service", async () => {
    const hass = createFakeHass({
      states: [fakeEntity("person.alice", "home")],
      services: { notify_switchboard: { silence: {}, unsnooze: {}, unsilence: {} } },
    });
    const tile = await mountTile(
      { type: "custom:switchboard-silence-tile", person: "person.alice" },
      hass,
    );
    tiles.push(tile);

    buttonWithText(tile, "Lift silence")?.click();
    await tile.updateComplete;

    expect(hass.callService).toHaveBeenCalledWith("notify_switchboard", "unsilence", {
      person: "person.alice",
    });
  });

  it("keeps 'Lift silence' aria-disabled on a router that only has unsnooze", async () => {
    const hass = createFakeHass({
      states: [fakeEntity("person.alice", "home")],
      services: { notify_switchboard: { unsnooze: {} } },
    });
    const tile = await mountTile(
      { type: "custom:switchboard-silence-tile", person: "person.alice" },
      hass,
    );
    tiles.push(tile);

    expect(buttonWithText(tile, "Clear snoozes")?.getAttribute("aria-disabled")).toBe("false");
    expect(buttonWithText(tile, "Lift silence")?.getAttribute("aria-disabled")).toBe("true");
  });
});

describe("switchboard-silence-tile shouldUpdate", () => {
  let tiles: SwitchboardSilenceTile[] = [];

  afterEach(() => {
    for (const tile of tiles) tile.remove();
    tiles = [];
  });

  it("does not re-render when an unrelated entity changes", async () => {
    const hass = createFakeHass({
      states: [
        fakeEntity("person.alice", "home"),
        fakeEntity("binary_sensor.alice_silenced", "off"),
        fakeEntity("sensor.kitchen_humidity", "44"),
      ],
    });
    const tile = await mountTile(
      { type: "custom:switchboard-silence-tile", person: "person.alice" },
      hass,
    );
    tiles.push(tile);

    const renderSpy = vi.spyOn(tile as unknown as { render: () => unknown }, "render");

    tile.hass = withUpdatedStates(hass, fakeEntity("sensor.kitchen_humidity", "45"));
    await tile.updateComplete;
    expect(renderSpy).not.toHaveBeenCalled();

    tile.hass = withUpdatedStates(tile.hass, fakeEntity("binary_sensor.alice_silenced", "on"));
    await tile.updateComplete;
    expect(renderSpy).toHaveBeenCalled();
  });
});

describe("switchboard-silence-tile wake time derived from the routing table", () => {
  let tiles: SwitchboardSilenceTile[] = [];

  afterEach(() => {
    for (const tile of tiles) tile.remove();
    tiles = [];
    vi.useRealTimers();
  });

  function routingTable(persons: Array<Record<string, unknown>>) {
    return fakeEntity(ROUTING_TABLE_ENTITY, "0", { attributes: { targets: [], persons } });
  }

  /** "Until wake" silences for exactly this many minutes. */
  async function untilWakeMinutes(
    config: SwitchboardSilenceTileConfig,
    states: ReturnType<typeof fakeEntity>[],
  ): Promise<number | undefined> {
    const hass = createFakeHass({
      states,
      services: { notify_switchboard: { silence: {}, unsnooze: {}, unsilence: {} } },
      timeZone: "UTC",
    });
    const tile = await mountTile(config, hass);
    tiles.push(tile);

    buttonWithText(tile, "Until wake")?.click();
    await tile.updateComplete;

    const call = vi.mocked(hass.callService).mock.calls.at(-1);
    return (call?.[2] as { minutes?: number } | undefined)?.minutes;
  }

  it("uses this person's wake_time from the router, converted from HH:MM:SS", async () => {
    // 00:00 UTC -> 06:45 is 405 minutes away; the built-in 07:00 would be 420.
    vi.useFakeTimers().setSystemTime(new Date("2026-09-07T00:00:00Z"));
    const minutes = await untilWakeMinutes(
      { type: "custom:switchboard-silence-tile", person: "person.alice" },
      [
        fakeEntity("person.alice", "home"),
        routingTable([{ entity_id: "person.alice", wake_time: "06:45:00", summary: true }]),
      ],
    );
    expect(minutes).toBe(405);
  });

  it("lets the card's own wake_time override the router", async () => {
    vi.useFakeTimers().setSystemTime(new Date("2026-09-07T00:00:00Z"));
    const minutes = await untilWakeMinutes(
      { type: "custom:switchboard-silence-tile", person: "person.alice", wake_time: "08:00" },
      [
        fakeEntity("person.alice", "home"),
        routingTable([{ entity_id: "person.alice", wake_time: "06:45:00", summary: true }]),
      ],
    );
    expect(minutes).toBe(480);
  });

  it("falls back to 07:00 for a person the router gives no wake time", async () => {
    vi.useFakeTimers().setSystemTime(new Date("2026-09-07T00:00:00Z"));
    const minutes = await untilWakeMinutes(
      { type: "custom:switchboard-silence-tile", person: "person.alice" },
      [
        fakeEntity("person.alice", "home"),
        routingTable([{ entity_id: "person.alice", wake_time: null, summary: true }]),
      ],
    );
    expect(minutes).toBe(420);
  });

  it("falls back to 07:00 with no routing table at all (router < 0.7.0)", async () => {
    vi.useFakeTimers().setSystemTime(new Date("2026-09-07T00:00:00Z"));
    const minutes = await untilWakeMinutes(
      { type: "custom:switchboard-silence-tile", person: "person.alice" },
      [fakeEntity("person.alice", "home")],
    );
    expect(minutes).toBe(420);
  });

  it("re-renders when the routing table changes", async () => {
    const hass = createFakeHass({
      states: [fakeEntity("person.alice", "home")],
      services: { notify_switchboard: { silence: {}, unsnooze: {}, unsilence: {} } },
      timeZone: "UTC",
    });
    const tile = await mountTile(
      { type: "custom:switchboard-silence-tile", person: "person.alice" },
      hass,
    );
    tiles.push(tile);

    vi.useFakeTimers().setSystemTime(new Date("2026-09-07T00:00:00Z"));
    tile.hass = withUpdatedStates(
      hass,
      routingTable([{ entity_id: "person.alice", wake_time: "06:45:00", summary: true }]),
    );
    await tile.updateComplete;

    buttonWithText(tile, "Until wake")?.click();
    await tile.updateComplete;
    expect(hass.callService).toHaveBeenCalledWith("notify_switchboard", "silence", {
      person: "person.alice",
      minutes: 405,
    });
  });
});
