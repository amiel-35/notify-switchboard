import { describe, expect, it } from "vitest";
import { minutesUntilWakeTime } from "../../src/utils/wake-time";

describe("minutesUntilWakeTime", () => {
  it("computes minutes until later today", () => {
    const now = new Date("2026-09-06T05:00:00");
    expect(minutesUntilWakeTime("07:00", now)).toBe(120);
  });

  it("rolls over to tomorrow when the wake time already passed", () => {
    const now = new Date("2026-09-06T08:00:00");
    expect(minutesUntilWakeTime("07:00", now)).toBe(23 * 60);
  });

  it("rolls over to tomorrow when the wake time is exactly now", () => {
    const now = new Date("2026-09-06T07:00:00");
    expect(minutesUntilWakeTime("07:00", now)).toBe(24 * 60);
  });

  it("returns null for a malformed wake time", () => {
    expect(minutesUntilWakeTime("not-a-time")).toBeNull();
    expect(minutesUntilWakeTime("25:00")).toBeNull();
    expect(minutesUntilWakeTime("07:60")).toBeNull();
  });

  describe("time zones", () => {
    // 04:00 UTC on a September morning is 04:00 in London (BST -> 05:00),
    // 06:00 in Paris, and 13:00 the same day in Tokyo. The answer must
    // follow Home Assistant's own clock, not the browser's.
    const now = new Date("2026-09-06T04:00:00.000Z");

    it("counts from the wall clock of the given IANA zone", () => {
      expect(minutesUntilWakeTime("07:00", now, "UTC")).toBe(180);
      expect(minutesUntilWakeTime("07:00", now, "Europe/Paris")).toBe(60);
      // Already 13:00 in Tokyo: rolls over to 07:00 tomorrow.
      expect(minutesUntilWakeTime("07:00", now, "Asia/Tokyo")).toBe(18 * 60);
    });

    it("handles a midnight wake time across zones", () => {
      expect(minutesUntilWakeTime("00:00", now, "UTC")).toBe(20 * 60);
      expect(minutesUntilWakeTime("00:00", now, "Asia/Tokyo")).toBe(11 * 60);
    });

    it("falls back to the local zone for an unknown zone name", () => {
      expect(minutesUntilWakeTime("07:00", now, "Not/AZone")).toBe(
        minutesUntilWakeTime("07:00", now),
      );
    });
  });
});
