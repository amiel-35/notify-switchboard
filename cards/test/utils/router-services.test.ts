import { describe, expect, it } from "vitest";
import {
  hasRouterService,
  resolveAlertTarget,
  resolveTargetSlug,
} from "../../src/utils/router-services";
import { readRoutingTable } from "../../src/utils/routing-table";
import { DEFAULT_SNOOZE_MINUTES, ROUTING_TABLE_ENTITY } from "../../src/types";
import { createFakeHass, fakeEntity } from "../fake-hass";

describe("hasRouterService", () => {
  it("returns false when the notify_switchboard domain is absent", () => {
    const hass = createFakeHass({ services: {} });
    expect(hasRouterService(hass, "acknowledge")).toBe(false);
  });

  it("returns false when the domain exists but the service does not (0.1.x)", () => {
    const hass = createFakeHass({ services: { notify_switchboard: {} } });
    expect(hasRouterService(hass, "snooze")).toBe(false);
  });

  it("returns true once the router registers the service (0.2.0+)", () => {
    const hass = createFakeHass({ services: { notify_switchboard: { snooze: {} } } });
    expect(hasRouterService(hass, "snooze")).toBe(true);
  });
});

describe("resolveTargetSlug", () => {
  it("returns the mapped slug", () => {
    expect(resolveTargetSlug("alert.leak", { "alert.leak": "leak" })).toBe("leak");
  });

  it("returns undefined when unmapped", () => {
    expect(resolveTargetSlug("alert.leak", {})).toBeUndefined();
    expect(resolveTargetSlug("alert.leak", undefined)).toBeUndefined();
  });
});

describe("resolveAlertTarget", () => {
  const table = readRoutingTable(
    createFakeHass({
      states: [
        fakeEntity(ROUTING_TABLE_ENTITY, "4", {
          attributes: {
            targets: [
              {
                slug: "leak",
                alert_entity: "alert.leak_kitchen",
                snooze_minutes: [10, 30],
                allow_acknowledge: true,
                audience: ["person.alice"],
              },
              {
                slug: "doorbell",
                alert_entity: "alert.doorbell",
                snooze_minutes: [5],
                allow_acknowledge: false,
                audience: ["person.bob"],
              },
              {
                // Snooze is off for this target: the router refuses every
                // duration, because its list holds none.
                slug: "silent",
                alert_entity: "alert.silent",
                snooze_minutes: [],
                allow_acknowledge: true,
                audience: [],
              },
              {
                // `allow_acknowledge: true` but no alert to turn off: the
                // router's own test is `bool(alert_entity) and allow_acknowledge`.
                slug: "no_alert",
                alert_entity: null,
                snooze_minutes: [20],
                allow_acknowledge: true,
                audience: [],
              },
            ],
            persons: [],
          },
        }),
      ],
    }),
  );

  it("derives the slug from the routing table when no target_map is configured", () => {
    const resolved = resolveAlertTarget("alert.leak_kitchen", {}, table);
    expect(resolved.slug).toBe("leak");
    expect(resolved.source).toBe("routing_table");
  });

  it("derives that target's own snooze durations", () => {
    expect(resolveAlertTarget("alert.leak_kitchen", {}, table).snoozeMinutes).toEqual([10, 30]);
    expect(resolveAlertTarget("alert.doorbell", {}, table).snoozeMinutes).toEqual([5]);
  });

  it("derives allow_acknowledge, defaulting to allowed when unstated", () => {
    expect(resolveAlertTarget("alert.leak_kitchen", {}, table).allowAcknowledge).toBe(true);
    expect(resolveAlertTarget("alert.doorbell", {}, table).allowAcknowledge).toBe(false);
    expect(resolveAlertTarget("alert.unmapped", {}, table).allowAcknowledge).toBe(true);
  });

  it("lets the card's own options override the routing table", () => {
    const resolved = resolveAlertTarget(
      "alert.leak_kitchen",
      { targetMap: { "alert.leak_kitchen": "doorbell" }, snoozeMinutes: [5, 45] },
      table,
    );
    expect(resolved.slug).toBe("doorbell");
    expect(resolved.source).toBe("config");
    // Narrowed to what that target actually offers: 45 is not in its list.
    expect(resolved.snoozeMinutes).toEqual([5]);
    // The overridden slug still carries that target's own permission.
    expect(resolved.allowAcknowledge).toBe(false);
  });

  it("narrows the card's durations to the row's own list, keeping the card's order", () => {
    // `notify_switchboard.snooze` refuses any duration outside the row's
    // `snooze_minutes` (`snooze_minutes_not_offered`), so an override can
    // only ever narrow that list — never add to it.
    expect(
      resolveAlertTarget("alert.leak_kitchen", { snoozeMinutes: [30, 45, 10] }, table)
        .snoozeMinutes,
    ).toEqual([30, 10]);
  });

  it("offers nothing when the card's durations and the row's list do not meet", () => {
    expect(
      resolveAlertTarget("alert.leak_kitchen", { snoozeMinutes: [45] }, table).snoozeMinutes,
    ).toEqual([]);
  });

  it("keeps the card's durations whole for a slug the table does not publish", () => {
    // A `target_map` naming a target the router does not describe is the
    // 0.1.x path: the card's options are the only source of durations,
    // and the row derived from the alert entity says nothing about the
    // slug that will actually be called.
    const resolved = resolveAlertTarget(
      "alert.leak_kitchen",
      { targetMap: { "alert.leak_kitchen": "leak_override" }, snoozeMinutes: [45] },
      table,
    );
    expect(resolved.slug).toBe("leak_override");
    expect(resolved.snoozeMinutes).toEqual([45]);
  });

  it("behaves exactly like 0.1.x with no routing table", () => {
    expect(resolveAlertTarget("alert.leak_kitchen", {}, undefined)).toEqual({
      slug: undefined,
      source: "none",
      allowAcknowledge: true,
      snoozeMinutes: DEFAULT_SNOOZE_MINUTES,
      audience: undefined,
    });
    expect(
      resolveAlertTarget(
        "alert.leak_kitchen",
        { targetMap: { "alert.leak_kitchen": "leak" } },
        undefined,
      ),
    ).toEqual({
      slug: "leak",
      source: "config",
      allowAcknowledge: true,
      snoozeMinutes: DEFAULT_SNOOZE_MINUTES,
      audience: undefined,
    });
  });

  it("falls back to the built-in durations for a target the table does not name", () => {
    expect(resolveAlertTarget("alert.unmapped", {}, table).snoozeMinutes).toEqual(
      DEFAULT_SNOOZE_MINUTES,
    );
  });

  it("takes an empty snooze_minutes as 'snooze is off', not as 'use the default'", () => {
    // The router rejects any duration that is not in the row's own list
    // (`snooze_minutes_not_offered`), so an empty list offers nothing.
    expect(resolveAlertTarget("alert.silent", {}, table).snoozeMinutes).toEqual([]);
  });

  it("offers nothing on an empty router list, whatever the card asks for", () => {
    // "Snooze is off for this target" is the router's answer, not a gap
    // the card may fill: every duration it offered would be refused.
    expect(
      resolveAlertTarget("alert.silent", { snoozeMinutes: [45] }, table).snoozeMinutes,
    ).toEqual([]);
  });

  it("refuses acknowledgement for a row with no alert entity, whatever it allows", () => {
    expect(
      resolveAlertTarget("alert.no_alert", { targetMap: { "alert.no_alert": "no_alert" } }, table)
        .allowAcknowledge,
    ).toBe(false);
  });

  it("reports the row's audience, and nothing when no row was derived", () => {
    expect(resolveAlertTarget("alert.leak_kitchen", {}, table).audience).toEqual(["person.alice"]);
    expect(resolveAlertTarget("alert.unmapped", {}, table).audience).toBeUndefined();
    expect(resolveAlertTarget("alert.leak_kitchen", {}, undefined).audience).toBeUndefined();
  });
});
