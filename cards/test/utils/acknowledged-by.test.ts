import { describe, expect, it } from "vitest";
import {
  acknowledgedByForAlert,
  acknowledgedByName,
  lastAcknowledgement,
} from "../../src/utils/acknowledged-by";
import { DELIVERY_EVENT_ENTITY } from "../../src/types";
import { createFakeHass, fakeEntity } from "../fake-hass";

/**
 * `event.switchboard_delivery` as Home Assistant exposes it: the state is
 * the last event's timestamp, the attributes are `event_type` plus that
 * event's payload.
 */
function deliveryEvent(eventType: string, payload: Record<string, unknown>) {
  return fakeEntity(DELIVERY_EVENT_ENTITY, "2026-09-07T10:00:00+00:00", {
    attributes: { event_type: eventType, ...payload },
  });
}

const ACKNOWLEDGED = deliveryEvent("acknowledged", {
  target: "leak",
  alert_entity: "alert.leak_kitchen",
  user_id: "0123456789abcdef0123456789abcdef",
  person: "person.alice",
});

describe("lastAcknowledgement", () => {
  it("returns nothing when the router publishes no delivery event", () => {
    expect(lastAcknowledgement(createFakeHass())).toBeUndefined();
  });

  it("returns nothing when the last event is not an acknowledgement", () => {
    for (const eventType of ["routed", "dropped", "snoozed"]) {
      const hass = createFakeHass({
        states: [deliveryEvent(eventType, { target: "leak", person: "person.alice" })],
      });
      expect(lastAcknowledgement(hass)).toBeUndefined();
    }
  });

  it("returns nothing while the event entity is unavailable or unknown", () => {
    for (const state of ["unavailable", "unknown"]) {
      const hass = createFakeHass({
        states: [
          fakeEntity(DELIVERY_EVENT_ENTITY, state, {
            attributes: { event_type: "acknowledged", target: "leak" },
          }),
        ],
      });
      expect(lastAcknowledgement(hass)).toBeUndefined();
    }
  });

  it("reads the payload of an acknowledged event", () => {
    const hass = createFakeHass({ states: [ACKNOWLEDGED] });
    expect(lastAcknowledgement(hass)).toEqual({
      at: "2026-09-07T10:00:00+00:00",
      target: "leak",
      alertEntity: "alert.leak_kitchen",
      person: "person.alice",
      userId: "0123456789abcdef0123456789abcdef",
    });
  });

  it("tolerates a pre-0.7.0 payload with no person key", () => {
    const hass = createFakeHass({
      states: [deliveryEvent("acknowledged", { target: "leak", user_id: "abcdef0123456789" })],
    });
    expect(lastAcknowledgement(hass)?.person).toBeNull();
  });
});

describe("acknowledgedByName", () => {
  it("uses the person's friendly name when the state machine has one", () => {
    const hass = createFakeHass({
      states: [
        ACKNOWLEDGED,
        fakeEntity("person.alice", "home", { attributes: { friendly_name: "Alice" } }),
      ],
    });
    expect(acknowledgedByName(hass, lastAcknowledgement(hass))).toBe("Alice");
  });

  it("falls back to the person entity id when it has no friendly name", () => {
    const hass = createFakeHass({ states: [ACKNOWLEDGED] });
    expect(acknowledgedByName(hass, lastAcknowledgement(hass))).toBe("person.alice");
  });

  it("shows a shortened user id only when the router resolved no person", () => {
    const hass = createFakeHass({
      states: [
        deliveryEvent("acknowledged", {
          target: "leak",
          person: null,
          user_id: "0123456789abcdef0123456789abcdef",
        }),
      ],
    });
    expect(acknowledgedByName(hass, lastAcknowledgement(hass))).toBe("01234567");
  });

  it("shows nothing at all when neither a person nor a user id is known", () => {
    const hass = createFakeHass({
      states: [deliveryEvent("acknowledged", { target: "leak", person: null, user_id: null })],
    });
    expect(acknowledgedByName(hass, lastAcknowledgement(hass))).toBeUndefined();
    expect(acknowledgedByName(hass, undefined)).toBeUndefined();
  });
});

describe("acknowledgedByForAlert", () => {
  const hass = createFakeHass({
    states: [
      ACKNOWLEDGED,
      fakeEntity("person.alice", "home", { attributes: { friendly_name: "Alice" } }),
    ],
  });

  it("matches on the slug when the card knows it", () => {
    expect(acknowledgedByForAlert(hass, "alert.leak_kitchen", "leak")).toBe("Alice");
  });

  it("does not attribute another target's acknowledgement", () => {
    expect(acknowledgedByForAlert(hass, "alert.door_left_open", "door")).toBeUndefined();
  });

  it("matches on the event's alert_entity when no slug is known", () => {
    expect(acknowledgedByForAlert(hass, "alert.leak_kitchen", undefined)).toBe("Alice");
    expect(acknowledgedByForAlert(hass, "alert.door_left_open", undefined)).toBeUndefined();
  });

  /**
   * The event entity keeps only the *last* event. An alert that has since
   * fired again is not the one that acknowledgement was about, so naming
   * somebody under it would credit them with an alert they never saw.
   */
  it("says nothing when the alert changed after the acknowledgement", () => {
    const stale = createFakeHass({
      states: [
        ACKNOWLEDGED,
        fakeEntity("person.alice", "home", { attributes: { friendly_name: "Alice" } }),
        fakeEntity("alert.leak_kitchen", "off", {
          last_changed: "2026-09-07T10:30:00+00:00",
        }),
      ],
    });
    expect(acknowledgedByForAlert(stale, "alert.leak_kitchen", "leak")).toBeUndefined();
  });

  it("still names the acknowledger when the alert has not changed since", () => {
    const fresh = createFakeHass({
      states: [
        ACKNOWLEDGED,
        fakeEntity("person.alice", "home", { attributes: { friendly_name: "Alice" } }),
        fakeEntity("alert.leak_kitchen", "off", {
          last_changed: "2026-09-07T10:00:00+00:00",
        }),
      ],
    });
    expect(acknowledgedByForAlert(fresh, "alert.leak_kitchen", "leak")).toBe("Alice");
  });

  it("does not suppress the line when either timestamp is unreadable", () => {
    const odd = createFakeHass({
      states: [
        ACKNOWLEDGED,
        fakeEntity("person.alice", "home", { attributes: { friendly_name: "Alice" } }),
        fakeEntity("alert.leak_kitchen", "off", { last_changed: "not a date" }),
      ],
    });
    expect(acknowledgedByForAlert(odd, "alert.leak_kitchen", "leak")).toBe("Alice");
  });
});
