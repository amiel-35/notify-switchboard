import { describe, expect, it } from "vitest";
import { formatRelativeDuration } from "../../src/utils/format-duration";

describe("formatRelativeDuration", () => {
  const now = new Date("2026-09-06T12:00:00.000Z");

  it("formats minutes ago in English", () => {
    const since = new Date("2026-09-06T11:55:00.000Z").toISOString();
    expect(formatRelativeDuration(since, "en", now)).toBe("5 minutes ago");
  });

  it("formats hours ago in French", () => {
    const since = new Date("2026-09-06T09:00:00.000Z").toISOString();
    expect(formatRelativeDuration(since, "fr", now)).toContain("heures");
  });

  it("formats days ago in Spanish", () => {
    const since = new Date("2026-09-03T12:00:00.000Z").toISOString();
    expect(formatRelativeDuration(since, "es", now)).toContain("día");
  });

  it("falls back to seconds for very recent timestamps", () => {
    const since = new Date("2026-09-06T11:59:58.000Z").toISOString();
    expect(formatRelativeDuration(since, "en", now)).toBe("2 seconds ago");
  });

  it("returns an empty string for an invalid timestamp", () => {
    expect(formatRelativeDuration("not-a-date", "en", now)).toBe("");
  });
});
