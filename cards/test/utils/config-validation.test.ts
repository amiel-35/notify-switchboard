import { describe, expect, it } from "vitest";
import "../../src/cards/alerts-card/switchboard-alerts-card";
import "../../src/cards/silence-tile/switchboard-silence-tile";
import type { SwitchboardAlertsCard } from "../../src/cards/alerts-card/switchboard-alerts-card";
import type { SwitchboardSilenceTile } from "../../src/cards/silence-tile/switchboard-silence-tile";
import type { LovelaceCardConfig } from "../../src/ha-types";

function alertsCard(): SwitchboardAlertsCard {
  return document.createElement("switchboard-alerts-card") as SwitchboardAlertsCard;
}

function silenceTile(): SwitchboardSilenceTile {
  return document.createElement("switchboard-silence-tile") as SwitchboardSilenceTile;
}

function setAlerts(config: Record<string, unknown>): void {
  alertsCard().setConfig({
    type: "custom:switchboard-alerts-card",
    ...config,
  } as LovelaceCardConfig);
}

function setTile(config: Record<string, unknown>): void {
  silenceTile().setConfig({
    type: "custom:switchboard-silence-tile",
    ...config,
  } as LovelaceCardConfig);
}

describe("switchboard-alerts-card setConfig validation", () => {
  it("rejects a non-mapping config", () => {
    expect(() => alertsCard().setConfig([] as unknown as LovelaceCardConfig)).toThrow(
      /must be a mapping/,
    );
    expect(() => alertsCard().setConfig("nope" as unknown as LovelaceCardConfig)).toThrow(
      /must be a mapping/,
    );
  });

  it("rejects `entities` given as a bare string, naming the option", () => {
    expect(() => setAlerts({ entities: "alert.leak" })).toThrow(/"entities"/);
    expect(() => setAlerts({ entities: "alert.leak" })).toThrow(/list of alert\.\* entity ids/);
  });

  it("rejects `entities` containing a non-alert entity id", () => {
    expect(() => setAlerts({ entities: ["alert.leak", "sensor.temperature"] })).toThrow(
      /"entities"/,
    );
    expect(() => setAlerts({ entities: ["alert.leak", 42] })).toThrow(/"entities"/);
  });

  it("accepts a well-formed `entities` list", () => {
    expect(() => setAlerts({ entities: ["alert.leak", "alert.door_left_open"] })).not.toThrow();
    expect(() => setAlerts({})).not.toThrow();
  });

  /**
   * An empty list is not a mistake: it is the editor's way of saying
   * "nothing set here", which since router 0.7.0 means "derive each
   * target's own durations from the routing table".
   */
  it("accepts an empty `snooze_minutes` as 'derive from the router'", () => {
    expect(() => setAlerts({ snooze_minutes: [] })).not.toThrow();
  });

  it("rejects a `snooze_minutes` that is not a list of positive whole numbers", () => {
    expect(() => setAlerts({ snooze_minutes: 15 })).toThrow(/"snooze_minutes"/);
    expect(() => setAlerts({ snooze_minutes: [15, 0] })).toThrow(/"snooze_minutes"/);
    expect(() => setAlerts({ snooze_minutes: [15, -60] })).toThrow(/"snooze_minutes"/);
    expect(() => setAlerts({ snooze_minutes: [15, 2.5] })).toThrow(/"snooze_minutes"/);
    expect(() => setAlerts({ snooze_minutes: ["15"] })).toThrow(/"snooze_minutes"/);
    expect(() => setAlerts({ snooze_minutes: [15, 60, 480] })).not.toThrow();
  });

  it("rejects a `person_picker` that is not a boolean", () => {
    expect(() => setAlerts({ person_picker: "yes" })).toThrow(/"person_picker"/);
    expect(() => setAlerts({ person_picker: 1 })).toThrow(/"person_picker"/);
    expect(() => setAlerts({ person_picker: true })).not.toThrow();
    expect(() => setAlerts({ person_picker: false })).not.toThrow();
  });

  it("rejects a `mode` outside {compact, full}", () => {
    expect(() => setAlerts({ mode: "tiny" })).toThrow(/"mode"/);
    expect(() => setAlerts({ mode: 1 })).toThrow(/"mode"/);
    expect(() => setAlerts({ mode: "compact" })).not.toThrow();
    expect(() => setAlerts({ mode: "full" })).not.toThrow();
  });

  it("rejects a `target_map` that is not an object of strings", () => {
    expect(() => setAlerts({ target_map: "alert.leak: leak" })).toThrow(/"target_map"/);
    expect(() => setAlerts({ target_map: ["alert.leak"] })).toThrow(/"target_map"/);
    expect(() => setAlerts({ target_map: { "alert.leak": 3 } })).toThrow(/"target_map"/);
    expect(() => setAlerts({ target_map: { "alert.leak": "leak" } })).not.toThrow();
  });

  it("rejects a non-boolean `show_acknowledged`", () => {
    expect(() => setAlerts({ show_acknowledged: "true" })).toThrow(/"show_acknowledged"/);
    expect(() => setAlerts({ show_acknowledged: 1 })).toThrow(/"show_acknowledged"/);
    expect(() => setAlerts({ show_acknowledged: false })).not.toThrow();
  });

  it("rejects a `person` that is not a person.* entity id", () => {
    expect(() => setAlerts({ person: "alice" })).toThrow(/"person"/);
    expect(() => setAlerts({ person: "sensor.alice" })).toThrow(/"person"/);
    expect(() => setAlerts({ person: 7 })).toThrow(/"person"/);
    expect(() => setAlerts({ person: "person.alice" })).not.toThrow();
  });

  it("rejects a non-string `title`", () => {
    expect(() => setAlerts({ title: 42 })).toThrow(/"title"/);
  });

  it("applies defaults for the options it validates", () => {
    const card = alertsCard();
    card.setConfig({ type: "custom:switchboard-alerts-card" } as LovelaceCardConfig);
    expect(card.getGridOptions()).toEqual({
      rows: "auto",
      columns: 12,
      min_rows: 2,
      min_columns: 6,
    });
  });
});

describe("switchboard-silence-tile setConfig validation", () => {
  it("rejects a non-mapping config", () => {
    expect(() => silenceTile().setConfig([] as unknown as LovelaceCardConfig)).toThrow(
      /must be a mapping/,
    );
  });

  it("rejects a `person` that is not a person.* entity id", () => {
    expect(() => setTile({ person: "alice" })).toThrow(/"person"/);
    expect(() => setTile({ person: "binary_sensor.alice" })).toThrow(/"person"/);
    expect(() => setTile({ person: ["person.alice"] })).toThrow(/"person"/);
    expect(() => setTile({ person: "person.alice" })).not.toThrow();
    // An empty string is how the stub config starts out; treated as unset.
    expect(() => setTile({ person: "" })).not.toThrow();
  });

  it("rejects a `wake_time` that is not HH:MM", () => {
    expect(() => setTile({ person: "person.alice", wake_time: "not-a-time" })).toThrow(
      /"wake_time"/,
    );
    expect(() => setTile({ person: "person.alice", wake_time: "25:00" })).toThrow(/"wake_time"/);
    expect(() => setTile({ person: "person.alice", wake_time: "07:60" })).toThrow(/"wake_time"/);
    expect(() => setTile({ person: "person.alice", wake_time: 700 })).toThrow(/"wake_time"/);
    expect(() => setTile({ person: "person.alice", wake_time: "07:00" })).not.toThrow();
  });

  it("rejects a non-string `title`", () => {
    expect(() => setTile({ person: "person.alice", title: {} })).toThrow(/"title"/);
  });

  it("exposes grid options for the sections layout", () => {
    const tile = silenceTile();
    tile.setConfig({
      type: "custom:switchboard-silence-tile",
      person: "person.alice",
    } as LovelaceCardConfig);
    expect(tile.getGridOptions()).toEqual({
      rows: "auto",
      columns: 6,
      min_rows: 2,
      min_columns: 3,
    });
  });
});
