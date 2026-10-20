import { afterEach, describe, expect, it, vi } from "vitest";
import "../src/cards/alerts-card/switchboard-alerts-card";
import type { SwitchboardAlertsCard } from "../src/cards/alerts-card/switchboard-alerts-card";
import type { SwitchboardAlertsCardConfig } from "../src/types";
import { DELIVERY_EVENT_ENTITY, ROUTING_TABLE_ENTITY } from "../src/types";
import { createFakeHass, fakeEntity, withUpdatedStates } from "./fake-hass";

async function mountCard(
  config: SwitchboardAlertsCardConfig,
  hass: ReturnType<typeof createFakeHass>,
): Promise<SwitchboardAlertsCard> {
  const card = document.createElement("switchboard-alerts-card") as SwitchboardAlertsCard;
  card.setConfig(config);
  card.hass = hass;
  document.body.appendChild(card);
  await card.updateComplete;
  return card;
}

function buttonWithText(card: SwitchboardAlertsCard, text: string): HTMLButtonElement | undefined {
  const buttons = Array.from(card.shadowRoot?.querySelectorAll("button") ?? []);
  return buttons.find((b) => b.textContent?.trim() === text) as HTMLButtonElement | undefined;
}

describe("switchboard-alerts-card rendering", () => {
  let cards: SwitchboardAlertsCard[] = [];

  afterEach(() => {
    for (const card of cards) card.remove();
    cards = [];
  });

  it("shows the empty state when every alert is idle", async () => {
    const hass = createFakeHass({
      states: [fakeEntity("alert.leak", "idle")],
    });
    const card = await mountCard({ type: "custom:switchboard-alerts-card", mode: "full" }, hass);
    cards.push(card);

    const html = card.shadowRoot?.innerHTML ?? "";
    expect(html).toContain("No active alerts");
  });

  it("lists active and acknowledged alerts, hiding idle ones", async () => {
    const hass = createFakeHass({
      states: [
        fakeEntity("alert.leak", "on", { attributes: { friendly_name: "Leak" } }),
        fakeEntity("alert.door", "off", { attributes: { friendly_name: "Door" } }),
        fakeEntity("alert.calm", "idle", { attributes: { friendly_name: "Calm" } }),
      ],
    });
    const card = await mountCard(
      { type: "custom:switchboard-alerts-card", mode: "full", show_acknowledged: true },
      hass,
    );
    cards.push(card);

    const rows = card.shadowRoot?.querySelectorAll(".alert-row");
    expect(rows?.length).toBe(2);
    const html = card.shadowRoot?.innerHTML ?? "";
    expect(html).toContain("Leak");
    expect(html).toContain("Door");
    expect(html).not.toContain("Calm");
  });

  it("hides acknowledged alerts when show_acknowledged is false", async () => {
    const hass = createFakeHass({
      states: [
        fakeEntity("alert.leak", "on", { attributes: { friendly_name: "Leak" } }),
        fakeEntity("alert.door", "off", { attributes: { friendly_name: "Door" } }),
      ],
    });
    const card = await mountCard(
      { type: "custom:switchboard-alerts-card", mode: "full", show_acknowledged: false },
      hass,
    );
    cards.push(card);

    const rows = card.shadowRoot?.querySelectorAll(".alert-row");
    expect(rows?.length).toBe(1);
    expect(card.shadowRoot?.innerHTML).toContain("Leak");
  });

  it("shows active and acknowledged counts on the compact badge", async () => {
    const hass = createFakeHass({
      states: [
        fakeEntity("alert.leak", "on"),
        fakeEntity("alert.door", "on"),
        fakeEntity("alert.fountain", "off"),
      ],
    });
    const card = await mountCard({ type: "custom:switchboard-alerts-card", mode: "compact" }, hass);
    cards.push(card);

    const counts = Array.from(card.shadowRoot?.querySelectorAll(".badge-count") ?? []).map((el) =>
      el.textContent?.trim(),
    );
    expect(counts).toEqual(["2", "1"]);
  });

  it("hides the badge title by default in compact mode (chips only)", async () => {
    const hass = createFakeHass({ states: [fakeEntity("alert.leak", "on")] });
    const card = await mountCard({ type: "custom:switchboard-alerts-card", mode: "compact" }, hass);
    cards.push(card);

    expect(card.shadowRoot?.querySelector(".badge-title")).toBeNull();
    expect(card.shadowRoot?.querySelector(".badge-chips")).not.toBeNull();
  });

  it("shows the badge title, laid out to never wrap, when title is configured in compact mode", async () => {
    const hass = createFakeHass({ states: [fakeEntity("alert.leak", "on")] });
    const card = await mountCard(
      { type: "custom:switchboard-alerts-card", mode: "compact", title: "Alertes" },
      hass,
    );
    cards.push(card);

    const titleEl = card.shadowRoot?.querySelector(".badge-title");
    expect(titleEl?.textContent?.trim()).toBe("Alertes");

    // The title must be styled to never wrap mid-word: nowrap + ellipsis,
    // never `wrap-text` (white-space: normal), which is what let a narrow
    // sections column break it letter by letter ("Al / ert / es").
    expect(titleEl?.classList.contains("wrap-text")).toBe(false);
    const styleText = Array.from(card.shadowRoot?.querySelectorAll("style") ?? [])
      .map((style) => style.textContent ?? "")
      .join("\n");
    expect(styleText).toMatch(/\.badge-title\s*{[^}]*white-space:\s*nowrap/);
    expect(styleText).toMatch(/\.badge-title\s*{[^}]*text-overflow:\s*ellipsis/);
  });

  it("declares compact grid options wide enough that sections never give it a single column", async () => {
    const hass = createFakeHass({ states: [fakeEntity("alert.leak", "on")] });
    const card = await mountCard({ type: "custom:switchboard-alerts-card", mode: "compact" }, hass);
    cards.push(card);

    expect(card.getGridOptions()).toEqual({
      rows: 1,
      columns: 4,
      min_rows: 1,
      min_columns: 3,
    });
  });

  it("opens a dialog listing alerts when the compact badge is activated", async () => {
    const hass = createFakeHass({
      states: [fakeEntity("alert.leak", "on", { attributes: { friendly_name: "Leak" } })],
    });
    const card = await mountCard({ type: "custom:switchboard-alerts-card", mode: "compact" }, hass);
    cards.push(card);

    expect(card.shadowRoot?.querySelector('[role="dialog"]')).toBeNull();

    card.shadowRoot?.querySelector<HTMLButtonElement>(".badge")?.click();
    await card.updateComplete;

    const dialog = card.shadowRoot?.querySelector('[role="dialog"]');
    expect(dialog).not.toBeNull();
    expect(dialog?.textContent).toContain("Leak");
  });

  it("fires hass-more-info when the alert name is clicked", async () => {
    const hass = createFakeHass({
      states: [fakeEntity("alert.leak", "on", { attributes: { friendly_name: "Leak" } })],
    });
    const card = await mountCard({ type: "custom:switchboard-alerts-card", mode: "full" }, hass);
    cards.push(card);

    const listener = vi.fn();
    card.addEventListener("hass-more-info", listener);
    card.shadowRoot?.querySelector<HTMLButtonElement>(".alert-name")?.click();

    expect(listener).toHaveBeenCalledTimes(1);
    const event = listener.mock.calls[0]?.[0] as CustomEvent;
    expect(event.detail).toEqual({ entityId: "alert.leak" });
  });

  it("renders the router footer only when its entities are present", async () => {
    const without = createFakeHass({ states: [fakeEntity("alert.leak", "on")] });
    const cardWithout = await mountCard(
      { type: "custom:switchboard-alerts-card", mode: "full" },
      without,
    );
    cards.push(cardWithout);
    expect(cardWithout.shadowRoot?.querySelector(".card-footer")).toBeNull();

    const withFooter = createFakeHass({
      states: [fakeEntity("alert.leak", "on"), fakeEntity("sensor.switchboard_dropped_today", "4")],
    });
    const cardWith = await mountCard(
      { type: "custom:switchboard-alerts-card", mode: "full" },
      withFooter,
    );
    cards.push(cardWith);
    expect(cardWith.shadowRoot?.querySelector(".card-footer")?.textContent).toContain(
      "Dropped today: 4",
    );
  });
});

describe("switchboard-alerts-card unavailable alerts", () => {
  let cards: SwitchboardAlertsCard[] = [];

  afterEach(() => {
    for (const card of cards) card.remove();
    cards = [];
  });

  for (const state of ["unavailable", "unknown"] as const) {
    it(`renders a neutral "Unavailable" row for an ${state} alert, never as acknowledged`, async () => {
      const hass = createFakeHass({
        states: [fakeEntity("alert.leak", state, { attributes: { friendly_name: "Leak" } })],
      });
      const card = await mountCard({ type: "custom:switchboard-alerts-card", mode: "full" }, hass);
      cards.push(card);

      const row = card.shadowRoot?.querySelector(".alert-row");
      expect(row).not.toBeNull();
      expect(row?.textContent).toContain("Unavailable");
      expect(row?.textContent).not.toContain("Acknowledged");
      expect(row?.querySelector(".chip-unavailable")).not.toBeNull();
      expect(row?.querySelector(".chip-acknowledged")).toBeNull();
      // Its status icon carries the meaning too, not colour alone.
      expect(row?.querySelector('.chip ha-icon[icon="mdi:help-circle-outline"]')).not.toBeNull();
    });
  }

  it("offers no acknowledge / un-acknowledge / snooze action on an unavailable alert", async () => {
    const hass = createFakeHass({
      states: [fakeEntity("alert.leak", "unavailable", { attributes: { friendly_name: "Leak" } })],
      services: { notify_switchboard: { snooze: {} } },
    });
    const card = await mountCard(
      {
        type: "custom:switchboard-alerts-card",
        mode: "full",
        target_map: { "alert.leak": "leak" },
      },
      hass,
    );
    cards.push(card);

    expect(buttonWithText(card, "Acknowledge")).toBeUndefined();
    expect(buttonWithText(card, "Un-acknowledge")).toBeUndefined();
    expect(card.shadowRoot?.querySelector(".snooze-menu")).toBeNull();
  });

  it("keeps unavailable alerts listed even when acknowledged ones are hidden", async () => {
    const hass = createFakeHass({
      states: [
        fakeEntity("alert.leak", "unavailable"),
        fakeEntity("alert.door", "off"),
        fakeEntity("alert.calm", "idle"),
      ],
    });
    const card = await mountCard(
      { type: "custom:switchboard-alerts-card", mode: "full", show_acknowledged: false },
      hass,
    );
    cards.push(card);

    const rows = card.shadowRoot?.querySelectorAll(".alert-row");
    expect(rows?.length).toBe(1);
    expect(rows?.[0]?.textContent).toContain("Unavailable");
  });

  it("counts unavailable alerts separately on the compact badge, with text and an icon", async () => {
    const hass = createFakeHass({
      states: [
        fakeEntity("alert.leak", "on"),
        fakeEntity("alert.door", "off"),
        fakeEntity("alert.fountain", "unavailable"),
        fakeEntity("alert.pets", "unknown"),
      ],
    });
    const card = await mountCard({ type: "custom:switchboard-alerts-card", mode: "compact" }, hass);
    cards.push(card);

    const counts = Array.from(card.shadowRoot?.querySelectorAll(".badge-count") ?? []).map((el) =>
      el.textContent?.trim(),
    );
    expect(counts).toEqual(["1", "1", "2"]);

    const unavailableChip = card.shadowRoot?.querySelector(".badge-count.chip-unavailable");
    expect(unavailableChip?.getAttribute("aria-label")).toBe("2 unavailable");
    expect(
      unavailableChip?.querySelector('ha-icon[icon="mdi:help-circle-outline"]'),
    ).not.toBeNull();

    const badgeLabel = card.shadowRoot?.querySelector(".badge")?.getAttribute("aria-label");
    expect(badgeLabel).toContain("2 unavailable");
  });
});

describe("switchboard-alerts-card acknowledge routing", () => {
  let cards: SwitchboardAlertsCard[] = [];

  afterEach(() => {
    for (const card of cards) card.remove();
    cards = [];
  });

  it("falls back to alert.turn_off when the router service is absent", async () => {
    const hass = createFakeHass({
      states: [fakeEntity("alert.leak", "on", { attributes: { friendly_name: "Leak" } })],
      services: {},
    });
    const card = await mountCard(
      {
        type: "custom:switchboard-alerts-card",
        mode: "full",
        target_map: { "alert.leak": "leak" },
      },
      hass,
    );
    cards.push(card);

    buttonWithText(card, "Acknowledge")?.click();
    await card.updateComplete;

    expect(hass.callService).toHaveBeenCalledWith("alert", "turn_off", { entity_id: "alert.leak" });
  });

  it("calls notify_switchboard.acknowledge when the router service and slug are both available", async () => {
    const hass = createFakeHass({
      states: [fakeEntity("alert.leak", "on", { attributes: { friendly_name: "Leak" } })],
      services: { notify_switchboard: { acknowledge: {} } },
    });
    const card = await mountCard(
      {
        type: "custom:switchboard-alerts-card",
        mode: "full",
        target_map: { "alert.leak": "leak" },
      },
      hass,
    );
    cards.push(card);

    buttonWithText(card, "Acknowledge")?.click();
    await card.updateComplete;

    expect(hass.callService).toHaveBeenCalledWith("notify_switchboard", "acknowledge", {
      target: "leak",
    });
  });

  it("still falls back to alert.turn_off when the service exists but no slug is mapped", async () => {
    const hass = createFakeHass({
      states: [fakeEntity("alert.leak", "on", { attributes: { friendly_name: "Leak" } })],
      services: { notify_switchboard: { acknowledge: {} } },
    });
    const card = await mountCard({ type: "custom:switchboard-alerts-card", mode: "full" }, hass);
    cards.push(card);

    buttonWithText(card, "Acknowledge")?.click();
    await card.updateComplete;

    expect(hass.callService).toHaveBeenCalledWith("alert", "turn_off", { entity_id: "alert.leak" });
  });

  it("un-acknowledges via alert.turn_on regardless of router services", async () => {
    const hass = createFakeHass({
      states: [fakeEntity("alert.leak", "off", { attributes: { friendly_name: "Leak" } })],
    });
    const card = await mountCard({ type: "custom:switchboard-alerts-card", mode: "full" }, hass);
    cards.push(card);

    buttonWithText(card, "Un-acknowledge")?.click();
    await card.updateComplete;

    expect(hass.callService).toHaveBeenCalledWith("alert", "turn_on", { entity_id: "alert.leak" });
  });

  it("only renders the snooze menu once the router service exists and the slug is known", async () => {
    const hassNoSlug = createFakeHass({
      states: [fakeEntity("alert.leak", "on")],
      services: { notify_switchboard: { snooze: {} } },
    });
    const cardNoSlug = await mountCard(
      { type: "custom:switchboard-alerts-card", mode: "full" },
      hassNoSlug,
    );
    cards.push(cardNoSlug);
    expect(cardNoSlug.shadowRoot?.querySelector(".snooze-menu")).toBeNull();

    const hassNoService = createFakeHass({
      states: [fakeEntity("alert.leak", "on")],
      services: {},
    });
    const cardNoService = await mountCard(
      {
        type: "custom:switchboard-alerts-card",
        mode: "full",
        target_map: { "alert.leak": "leak" },
      },
      hassNoService,
    );
    cards.push(cardNoService);
    expect(cardNoService.shadowRoot?.querySelector(".snooze-menu")).toBeNull();

    const hassReady = createFakeHass({
      states: [fakeEntity("alert.leak", "on")],
      services: { notify_switchboard: { snooze: {} } },
    });
    const cardReady = await mountCard(
      {
        type: "custom:switchboard-alerts-card",
        mode: "full",
        target_map: { "alert.leak": "leak" },
      },
      hassReady,
    );
    cards.push(cardReady);
    expect(cardReady.shadowRoot?.querySelector(".snooze-menu")).not.toBeNull();
  });
});

describe("switchboard-alerts-card snooze audience", () => {
  let cards: SwitchboardAlertsCard[] = [];

  afterEach(() => {
    for (const card of cards) card.remove();
    cards = [];
  });

  const readyHass = () =>
    createFakeHass({
      states: [fakeEntity("alert.leak", "on")],
      services: { notify_switchboard: { snooze: {} } },
    });

  it("says the snooze applies to everyone when no person is configured", async () => {
    const hass = readyHass();
    const card = await mountCard(
      {
        type: "custom:switchboard-alerts-card",
        mode: "full",
        target_map: { "alert.leak": "leak" },
        snooze_minutes: [15],
      },
      hass,
    );
    cards.push(card);

    const option = buttonWithText(card, "Snooze for everyone · 15 min");
    expect(option).toBeDefined();

    option?.click();
    await card.updateComplete;
    expect(hass.callService).toHaveBeenCalledWith("notify_switchboard", "snooze", {
      target: "leak",
      minutes: 15,
    });
  });

  it("passes the configured person through to notify_switchboard.snooze", async () => {
    const hass = readyHass();
    const card = await mountCard(
      {
        type: "custom:switchboard-alerts-card",
        mode: "full",
        target_map: { "alert.leak": "leak" },
        snooze_minutes: [15],
        person: "person.alice",
      },
      hass,
    );
    cards.push(card);

    const option = buttonWithText(card, "Snooze 15 min");
    expect(option).toBeDefined();

    option?.click();
    await card.updateComplete;
    expect(hass.callService).toHaveBeenCalledWith("notify_switchboard", "snooze", {
      target: "leak",
      minutes: 15,
      person: "person.alice",
    });
  });
});

describe("switchboard-alerts-card snooze menu accessibility", () => {
  let cards: SwitchboardAlertsCard[] = [];

  afterEach(() => {
    for (const card of cards) card.remove();
    cards = [];
  });

  async function mountWithMenu(): Promise<SwitchboardAlertsCard> {
    const hass = createFakeHass({
      states: [fakeEntity("alert.leak", "on")],
      services: { notify_switchboard: { snooze: {} } },
    });
    const card = await mountCard(
      {
        type: "custom:switchboard-alerts-card",
        mode: "full",
        target_map: { "alert.leak": "leak" },
      },
      hass,
    );
    cards.push(card);
    return card;
  }

  it("leaves the summary's native role alone and exposes aria-expanded", async () => {
    const card = await mountWithMenu();
    const summary = card.shadowRoot?.querySelector("summary");

    expect(summary?.hasAttribute("role")).toBe(false);
    expect(summary?.getAttribute("aria-expanded")).toBe("false");

    const details = card.shadowRoot?.querySelector("details") as HTMLDetailsElement;
    details.open = true;
    details.dispatchEvent(new Event("toggle"));
    expect(summary?.getAttribute("aria-expanded")).toBe("true");
  });

  it("marks the option list as a menu", async () => {
    const card = await mountWithMenu();
    expect(card.shadowRoot?.querySelector(".snooze-options")?.getAttribute("role")).toBe("menu");
    const items = card.shadowRoot?.querySelectorAll('.snooze-options [role="menuitem"]');
    expect(items?.length).toBe(3);
  });

  it("closes on Escape and puts focus back on the summary", async () => {
    const card = await mountWithMenu();
    const details = card.shadowRoot?.querySelector("details") as HTMLDetailsElement;
    const summary = details.querySelector("summary") as HTMLElement;
    details.open = true;
    details.dispatchEvent(new Event("toggle"));

    const firstOption = details.querySelector<HTMLElement>('[role="menuitem"]');
    firstOption?.focus();
    firstOption?.dispatchEvent(
      new KeyboardEvent("keydown", { key: "Escape", bubbles: true, cancelable: true }),
    );

    expect(details.open).toBe(false);
    expect(summary.getAttribute("aria-expanded")).toBe("false");
    expect(card.shadowRoot?.activeElement).toBe(summary);
  });
});

describe("switchboard-alerts-card dialog keyboard behaviour", () => {
  let cards: SwitchboardAlertsCard[] = [];

  afterEach(() => {
    for (const card of cards) card.remove();
    cards = [];
  });

  async function openDialog(): Promise<SwitchboardAlertsCard> {
    const hass = createFakeHass({
      states: [
        fakeEntity("alert.leak", "on", { attributes: { friendly_name: "Leak" } }),
        fakeEntity("alert.door", "on", { attributes: { friendly_name: "Door" } }),
      ],
    });
    const card = await mountCard({ type: "custom:switchboard-alerts-card", mode: "compact" }, hass);
    cards.push(card);
    card.shadowRoot?.querySelector<HTMLButtonElement>(".badge")?.click();
    await card.updateComplete;
    return card;
  }

  function focusables(card: SwitchboardAlertsCard): HTMLElement[] {
    const dialog = card.shadowRoot?.querySelector(".dialog") as HTMLElement;
    return Array.from(dialog.querySelectorAll<HTMLElement>("button"));
  }

  function tab(target: HTMLElement, shiftKey = false): KeyboardEvent {
    const event = new KeyboardEvent("keydown", {
      key: "Tab",
      shiftKey,
      bubbles: true,
      composed: true,
      cancelable: true,
    });
    target.dispatchEvent(event);
    return event;
  }

  it("wraps Tab from the last control back to the first", async () => {
    const card = await openDialog();
    const controls = focusables(card);
    const first = controls[0] as HTMLElement;
    const last = controls[controls.length - 1] as HTMLElement;

    last.focus();
    expect(card.shadowRoot?.activeElement).toBe(last);

    const event = tab(last);
    expect(event.defaultPrevented).toBe(true);
    expect(card.shadowRoot?.activeElement).toBe(first);
  });

  it("wraps Shift+Tab from the first control back to the last", async () => {
    const card = await openDialog();
    const controls = focusables(card);
    const first = controls[0] as HTMLElement;
    const last = controls[controls.length - 1] as HTMLElement;

    first.focus();
    const event = tab(first, true);
    expect(event.defaultPrevented).toBe(true);
    expect(card.shadowRoot?.activeElement).toBe(last);
  });

  it("leaves Tab alone in the middle of the dialog", async () => {
    const card = await openDialog();
    const controls = focusables(card);
    expect(controls.length).toBeGreaterThan(2);
    const middle = controls[1] as HTMLElement;

    middle.focus();
    const event = tab(middle);
    expect(event.defaultPrevented).toBe(false);
    expect(card.shadowRoot?.activeElement).toBe(middle);
  });

  it("closes on Escape and returns focus to the badge button", async () => {
    const card = await openDialog();
    const badge = card.shadowRoot?.querySelector<HTMLElement>(".badge") as HTMLElement;
    const closeButton = focusables(card)[0] as HTMLElement;

    closeButton.dispatchEvent(
      new KeyboardEvent("keydown", { key: "Escape", bubbles: true, composed: true }),
    );
    await card.updateComplete;
    await card.updateComplete;

    expect(card.shadowRoot?.querySelector('[role="dialog"]')).toBeNull();
    expect(card.shadowRoot?.activeElement).toBe(badge);
  });
});

describe("switchboard-alerts-card shouldUpdate", () => {
  let cards: SwitchboardAlertsCard[] = [];

  afterEach(() => {
    for (const card of cards) card.remove();
    cards = [];
  });

  it("does not re-render when an unrelated entity changes", async () => {
    const hass = createFakeHass({
      states: [
        fakeEntity("alert.leak", "on", { attributes: { friendly_name: "Leak" } }),
        fakeEntity("sensor.living_room_temperature", "21.0"),
      ],
    });
    const card = await mountCard(
      { type: "custom:switchboard-alerts-card", mode: "full", entities: ["alert.leak"] },
      hass,
    );
    cards.push(card);

    const renderSpy = vi.spyOn(card as unknown as { render: () => unknown }, "render");

    card.hass = withUpdatedStates(hass, fakeEntity("sensor.living_room_temperature", "21.5"));
    await card.updateComplete;
    expect(renderSpy).not.toHaveBeenCalled();

    card.hass = withUpdatedStates(card.hass, fakeEntity("alert.leak", "off"));
    await card.updateComplete;
    expect(renderSpy).toHaveBeenCalled();
  });

  it("re-renders when a watched alert changes even without an explicit entity list", async () => {
    const hass = createFakeHass({
      states: [fakeEntity("alert.leak", "on"), fakeEntity("sensor.unrelated", "1")],
    });
    const card = await mountCard({ type: "custom:switchboard-alerts-card", mode: "full" }, hass);
    cards.push(card);

    const renderSpy = vi.spyOn(card as unknown as { render: () => unknown }, "render");

    card.hass = withUpdatedStates(hass, fakeEntity("sensor.unrelated", "2"));
    await card.updateComplete;
    expect(renderSpy).not.toHaveBeenCalled();

    card.hass = withUpdatedStates(card.hass, fakeEntity("alert.leak", "off"));
    await card.updateComplete;
    expect(renderSpy).toHaveBeenCalled();
  });
});

/**
 * Router 0.7.0's `sensor.switchboard_routing_table`, in the shape the
 * contract freezes (§"`sensor.switchboard_routing_table`").
 */
function routingTable(
  targets: Array<Record<string, unknown>>,
  persons: Array<Record<string, unknown>> = [],
) {
  return fakeEntity(ROUTING_TABLE_ENTITY, String(targets.length), {
    attributes: { targets, persons },
  });
}

const LEAK_TARGET = {
  slug: "leak",
  name: "Water leak",
  alert_entity: "alert.leak",
  snooze_minutes: [10, 30],
  allow_acknowledge: true,
  // The router only accepts a snooze for a person of this audience
  // (`person_not_in_audience`), so the picker may only ever offer these.
  audience: ["person.alice", "person.bob", "notify.hallway_speaker"],
};

describe("switchboard-alerts-card options derived from the routing table", () => {
  let cards: SwitchboardAlertsCard[] = [];

  afterEach(() => {
    for (const card of cards) card.remove();
    cards = [];
  });

  it("offers snooze with no target_map at all, deriving the slug from the router", async () => {
    const hass = createFakeHass({
      states: [fakeEntity("alert.leak", "on"), routingTable([LEAK_TARGET])],
      services: { notify_switchboard: { snooze: {} } },
    });
    const card = await mountCard({ type: "custom:switchboard-alerts-card", mode: "full" }, hass);
    cards.push(card);

    expect(card.shadowRoot?.querySelector(".snooze-menu")).not.toBeNull();
    // The target's own durations, not the card's built-in [15, 60, 480].
    buttonWithText(card, "Snooze for everyone · 30 min")?.click();
    await card.updateComplete;
    expect(hass.callService).toHaveBeenCalledWith("notify_switchboard", "snooze", {
      target: "leak",
      minutes: 30,
    });
    expect(buttonWithText(card, "Snooze for everyone · 15 min")).toBeUndefined();
  });

  it("acknowledges through the router service once the table names the target", async () => {
    const hass = createFakeHass({
      states: [fakeEntity("alert.leak", "on"), routingTable([LEAK_TARGET])],
      services: { notify_switchboard: { acknowledge: {} } },
    });
    const card = await mountCard({ type: "custom:switchboard-alerts-card", mode: "full" }, hass);
    cards.push(card);

    buttonWithText(card, "Acknowledge")?.click();
    await card.updateComplete;
    expect(hass.callService).toHaveBeenCalledWith("notify_switchboard", "acknowledge", {
      target: "leak",
    });
  });

  it("falls back to alert.turn_off for a target that refuses acknowledgement", async () => {
    const hass = createFakeHass({
      states: [
        fakeEntity("alert.leak", "on"),
        routingTable([{ ...LEAK_TARGET, allow_acknowledge: false }]),
      ],
      services: { notify_switchboard: { acknowledge: {} } },
    });
    const card = await mountCard({ type: "custom:switchboard-alerts-card", mode: "full" }, hass);
    cards.push(card);

    buttonWithText(card, "Acknowledge")?.click();
    await card.updateComplete;
    expect(hass.callService).toHaveBeenCalledWith("alert", "turn_off", {
      entity_id: "alert.leak",
    });
  });

  it("keeps the configured options winning over the routing table", async () => {
    const hass = createFakeHass({
      states: [fakeEntity("alert.leak", "on"), routingTable([LEAK_TARGET])],
      services: { notify_switchboard: { snooze: {} } },
    });
    const card = await mountCard(
      {
        type: "custom:switchboard-alerts-card",
        mode: "full",
        target_map: { "alert.leak": "leak_override" },
        snooze_minutes: [45],
      },
      hass,
    );
    cards.push(card);

    buttonWithText(card, "Snooze for everyone · 45 min")?.click();
    await card.updateComplete;
    expect(hass.callService).toHaveBeenCalledWith("notify_switchboard", "snooze", {
      target: "leak_override",
      minutes: 45,
    });
  });

  it("hides the snooze menu for a target whose router list is empty", async () => {
    // `snooze_minutes: []` is the router saying snooze is off for this
    // row: every duration the card could offer would be refused.
    const hass = createFakeHass({
      states: [
        fakeEntity("alert.leak", "on"),
        routingTable([{ ...LEAK_TARGET, snooze_minutes: [] }]),
      ],
      services: { notify_switchboard: { snooze: {} } },
    });
    const card = await mountCard({ type: "custom:switchboard-alerts-card", mode: "full" }, hass);
    cards.push(card);

    expect(card.shadowRoot?.querySelector(".snooze-menu")).toBeNull();
  });

  it("hides the menu when the card's durations meet an empty router list", async () => {
    // The card's own `snooze_minutes` cannot re-open a target the router
    // has closed: `notify_switchboard.snooze` refuses every duration that
    // is not in the row's list, so the intersection is empty and there is
    // nothing left to offer.
    const hass = createFakeHass({
      states: [
        fakeEntity("alert.leak", "on"),
        routingTable([{ ...LEAK_TARGET, snooze_minutes: [] }]),
      ],
      services: { notify_switchboard: { snooze: {} } },
    });
    const card = await mountCard(
      { type: "custom:switchboard-alerts-card", mode: "full", snooze_minutes: [45] },
      hass,
    );
    cards.push(card);

    expect(card.shadowRoot?.querySelector(".snooze-menu")).toBeNull();
  });

  it("narrows the card's durations to the ones the router would accept", async () => {
    const hass = createFakeHass({
      states: [fakeEntity("alert.leak", "on"), routingTable([LEAK_TARGET])],
      services: { notify_switchboard: { snooze: {} } },
    });
    const card = await mountCard(
      // 30 is in the target's [10, 30]; 45 is not and would be refused.
      { type: "custom:switchboard-alerts-card", mode: "full", snooze_minutes: [30, 45] },
      hass,
    );
    cards.push(card);

    expect(buttonWithText(card, "Snooze for everyone · 45 min")).toBeUndefined();
    buttonWithText(card, "Snooze for everyone · 30 min")?.click();
    await card.updateComplete;
    expect(hass.callService).toHaveBeenCalledWith("notify_switchboard", "snooze", {
      target: "leak",
      minutes: 30,
    });
  });

  it("re-renders when the routing table changes", async () => {
    const hass = createFakeHass({
      states: [fakeEntity("alert.leak", "on")],
      services: { notify_switchboard: { snooze: {} } },
    });
    const card = await mountCard({ type: "custom:switchboard-alerts-card", mode: "full" }, hass);
    cards.push(card);
    expect(card.shadowRoot?.querySelector(".snooze-menu")).toBeNull();

    card.hass = withUpdatedStates(hass, routingTable([LEAK_TARGET]));
    await card.updateComplete;
    expect(card.shadowRoot?.querySelector(".snooze-menu")).not.toBeNull();
  });
});

describe("switchboard-alerts-card acknowledged-by", () => {
  let cards: SwitchboardAlertsCard[] = [];

  afterEach(() => {
    for (const card of cards) card.remove();
    cards = [];
  });

  const deliveryEvent = (eventType: string, payload: Record<string, unknown>) =>
    fakeEntity(DELIVERY_EVENT_ENTITY, "2026-09-07T10:00:00+00:00", {
      attributes: { event_type: eventType, ...payload },
    });

  const acknowledged = () =>
    deliveryEvent("acknowledged", {
      target: "leak",
      alert_entity: "alert.leak",
      user_id: "0123456789abcdef",
      person: "person.alice",
    });

  const alice = () =>
    fakeEntity("person.alice", "home", { attributes: { friendly_name: "Alice" } });

  /** An alert whose last change predates the acknowledgement event above. */
  const alertBefore = (entityId: string, state: string) =>
    fakeEntity(entityId, state, { last_changed: "2026-09-07T09:00:00+00:00" });

  it("names who acknowledged an acknowledged alert", async () => {
    const hass = createFakeHass({
      states: [
        alertBefore("alert.leak", "off"),
        routingTable([LEAK_TARGET]),
        acknowledged(),
        alice(),
      ],
    });
    const card = await mountCard({ type: "custom:switchboard-alerts-card", mode: "full" }, hass);
    cards.push(card);

    expect(card.shadowRoot?.querySelector(".acknowledged-by")?.textContent?.trim()).toBe(
      "Acknowledged by Alice",
    );
  });

  it("says nothing on an alert that is still active", async () => {
    const hass = createFakeHass({
      states: [
        alertBefore("alert.leak", "on"),
        routingTable([LEAK_TARGET]),
        acknowledged(),
        alice(),
      ],
    });
    const card = await mountCard({ type: "custom:switchboard-alerts-card", mode: "full" }, hass);
    cards.push(card);

    expect(card.shadowRoot?.querySelector(".acknowledged-by")).toBeNull();
  });

  it("says nothing once a later event replaced the acknowledgement", async () => {
    const hass = createFakeHass({
      states: [
        alertBefore("alert.leak", "off"),
        routingTable([LEAK_TARGET]),
        deliveryEvent("routed", { target: "leak", person: "person.alice" }),
        alice(),
      ],
    });
    const card = await mountCard({ type: "custom:switchboard-alerts-card", mode: "full" }, hass);
    cards.push(card);

    expect(card.shadowRoot?.querySelector(".acknowledged-by")).toBeNull();
  });

  it("does not attribute one target's acknowledgement to another alert", async () => {
    const hass = createFakeHass({
      states: [
        alertBefore("alert.door", "off"),
        routingTable([LEAK_TARGET, { ...LEAK_TARGET, slug: "door", alert_entity: "alert.door" }]),
        acknowledged(),
        alice(),
      ],
    });
    const card = await mountCard({ type: "custom:switchboard-alerts-card", mode: "full" }, hass);
    cards.push(card);

    expect(card.shadowRoot?.querySelector(".acknowledged-by")).toBeNull();
  });

  it("says nothing once the alert itself changed after the acknowledgement", async () => {
    const hass = createFakeHass({
      states: [
        // The alert went off *after* the event entity's last acknowledgement:
        // whoever acknowledged did not acknowledge this one.
        fakeEntity("alert.leak", "off", { last_changed: "2026-09-07T11:00:00+00:00" }),
        routingTable([LEAK_TARGET]),
        acknowledged(),
        alice(),
      ],
    });
    const card = await mountCard({ type: "custom:switchboard-alerts-card", mode: "full" }, hass);
    cards.push(card);

    expect(card.shadowRoot?.querySelector(".acknowledged-by")).toBeNull();
  });

  it("says nothing at all against a router that publishes no authorship", async () => {
    const hass = createFakeHass({
      states: [
        alertBefore("alert.leak", "off"),
        routingTable([LEAK_TARGET]),
        deliveryEvent("acknowledged", { target: "leak", user_id: null }),
      ],
    });
    const card = await mountCard({ type: "custom:switchboard-alerts-card", mode: "full" }, hass);
    cards.push(card);

    expect(card.shadowRoot?.querySelector(".acknowledged-by")).toBeNull();
  });
});

describe("switchboard-alerts-card kiosk person picker", () => {
  let cards: SwitchboardAlertsCard[] = [];

  afterEach(() => {
    for (const card of cards) card.remove();
    cards = [];
  });

  const PERSONS = [
    { entity_id: "person.alice", wake_time: "07:00:00", summary: true },
    { entity_id: "person.bob", wake_time: null, summary: true },
  ];

  async function mountPicker(
    overrides: Partial<SwitchboardAlertsCardConfig> = {},
  ): Promise<{ card: SwitchboardAlertsCard; hass: ReturnType<typeof createFakeHass> }> {
    const hass = createFakeHass({
      states: [
        fakeEntity("alert.leak", "on", { attributes: { friendly_name: "Water leak" } }),
        routingTable([{ ...LEAK_TARGET, snooze_minutes: [15] }], PERSONS),
        fakeEntity("person.alice", "home", { attributes: { friendly_name: "Alice" } }),
        fakeEntity("person.bob", "home", { attributes: { friendly_name: "Bob" } }),
      ],
      services: { notify_switchboard: { snooze: {} } },
    });
    const card = await mountCard(
      {
        type: "custom:switchboard-alerts-card",
        mode: "full",
        person_picker: true,
        ...overrides,
      } as SwitchboardAlertsCardConfig,
      hass,
    );
    cards.push(card);
    return { card, hass };
  }

  it("is off by default: the durations show straight away", async () => {
    const hass = createFakeHass({
      states: [fakeEntity("alert.leak", "on"), routingTable([LEAK_TARGET], PERSONS)],
      services: { notify_switchboard: { snooze: {} } },
    });
    const card = await mountCard({ type: "custom:switchboard-alerts-card", mode: "full" }, hass);
    cards.push(card);

    expect(card.shadowRoot?.querySelector(".picker-step")).toBeNull();
    expect(card.shadowRoot?.querySelector(".snooze-options")).not.toBeNull();
  });

  it("asks who first, listing the routing table's persons plus everyone", async () => {
    const { card } = await mountPicker();

    expect(card.shadowRoot?.querySelector(".snooze-options")).toBeNull();
    const names = Array.from(card.shadowRoot?.querySelectorAll(".picker-step button") ?? []).map(
      (button) => button.textContent?.trim(),
    );
    expect(names).toEqual(["Alice", "Bob", "Everyone"]);
  });

  it("passes the chosen person to notify_switchboard.snooze", async () => {
    const { card, hass } = await mountPicker();

    buttonWithText(card, "Bob")?.click();
    await card.updateComplete;

    buttonWithText(card, "Snooze 15 min")?.click();
    await card.updateComplete;
    expect(hass.callService).toHaveBeenCalledWith("notify_switchboard", "snooze", {
      target: "leak",
      minutes: 15,
      person: "person.bob",
    });
  });

  it("sends no person when 'Everyone' is chosen, even with person configured", async () => {
    const { card, hass } = await mountPicker({ person: "person.alice" });

    buttonWithText(card, "Everyone")?.click();
    await card.updateComplete;

    buttonWithText(card, "Snooze for everyone · 15 min")?.click();
    await card.updateComplete;
    expect(hass.callService).toHaveBeenCalledWith("notify_switchboard", "snooze", {
      target: "leak",
      minutes: 15,
    });
  });

  it("lets the choice be changed before the duration is picked", async () => {
    const { card } = await mountPicker();

    buttonWithText(card, "Alice")?.click();
    await card.updateComplete;
    expect(card.shadowRoot?.querySelector(".picker-chosen")?.textContent).toContain("Alice");

    card.shadowRoot?.querySelector<HTMLButtonElement>(".picker-change")?.click();
    await card.updateComplete;
    expect(card.shadowRoot?.querySelector(".picker-step")).not.toBeNull();
  });

  it("moves focus into the step that replaced the one just used", async () => {
    const { card } = await mountPicker();

    buttonWithText(card, "Alice")?.click();
    await card.updateComplete;
    await card.updateComplete;
    expect(
      (card.shadowRoot?.activeElement as HTMLElement | null)?.classList.contains("action-button"),
    ).toBe(true);
    expect(card.shadowRoot?.activeElement?.textContent?.trim()).toBe("Snooze 15 min");

    card.shadowRoot?.querySelector<HTMLButtonElement>(".picker-change")?.click();
    await card.updateComplete;
    await card.updateComplete;
    expect(card.shadowRoot?.activeElement?.textContent?.trim()).toBe("Alice");
  });

  it("keeps every picker control at the 48px touch target", async () => {
    const { card } = await mountPicker();
    const buttons = Array.from(card.shadowRoot?.querySelectorAll(".picker-step button") ?? []);
    expect(buttons.length).toBeGreaterThan(0);
    for (const button of buttons) {
      expect(button.classList.contains("touch-target")).toBe(true);
      // Real <button>s: reachable by Tab without any tabindex juggling.
      expect(button.tagName).toBe("BUTTON");
    }
  });

  it("never appears when the routing table names nobody", async () => {
    const hass = createFakeHass({
      states: [fakeEntity("alert.leak", "on"), routingTable([LEAK_TARGET], [])],
      services: { notify_switchboard: { snooze: {} } },
    });
    const card = await mountCard(
      { type: "custom:switchboard-alerts-card", mode: "full", person_picker: true },
      hass,
    );
    cards.push(card);

    expect(card.shadowRoot?.querySelector(".picker-step")).toBeNull();
    expect(card.shadowRoot?.querySelector(".snooze-options")).not.toBeNull();
  });

  it("never offers a person outside the target's audience", async () => {
    const hass = createFakeHass({
      states: [
        fakeEntity("alert.leak", "on"),
        // Bob is a configured person, but not in this target's audience:
        // `notify_switchboard.snooze` would refuse him.
        routingTable([{ ...LEAK_TARGET, audience: ["person.alice"] }], PERSONS),
        fakeEntity("person.alice", "home", { attributes: { friendly_name: "Alice" } }),
        fakeEntity("person.bob", "home", { attributes: { friendly_name: "Bob" } }),
      ],
      services: { notify_switchboard: { snooze: {} } },
    });
    const card = await mountCard(
      { type: "custom:switchboard-alerts-card", mode: "full", person_picker: true },
      hass,
    );
    cards.push(card);

    const names = Array.from(card.shadowRoot?.querySelectorAll(".picker-step button") ?? []).map(
      (button) => button.textContent?.trim(),
    );
    expect(names).toEqual(["Alice", "Everyone"]);
  });

  it("shows no picker at all when the audience names nobody", async () => {
    const hass = createFakeHass({
      states: [
        fakeEntity("alert.leak", "on"),
        routingTable([{ ...LEAK_TARGET, audience: ["notify.hallway_speaker"] }], PERSONS),
      ],
      services: { notify_switchboard: { snooze: {} } },
    });
    const card = await mountCard(
      { type: "custom:switchboard-alerts-card", mode: "full", person_picker: true },
      hass,
    );
    cards.push(card);

    expect(card.shadowRoot?.querySelector(".picker-step")).toBeNull();
    expect(card.shadowRoot?.querySelector(".snooze-options")).not.toBeNull();
  });

  it("names the alert in the picker's group label", async () => {
    const { card } = await mountPicker();
    expect(card.shadowRoot?.querySelector(".picker-step")?.getAttribute("aria-label")).toBe(
      "Snooze Water leak for whom?",
    );
  });

  it("closes the menu and returns focus to Snooze once a duration is picked", async () => {
    const { card } = await mountPicker();

    buttonWithText(card, "Alice")?.click();
    await card.updateComplete;
    const details = card.shadowRoot?.querySelector("details") as HTMLDetailsElement;
    details.open = true;

    buttonWithText(card, "Snooze 15 min")?.click();
    await card.updateComplete;
    await card.updateComplete;

    expect(details.open).toBe(false);
    expect(details.querySelector("summary")?.getAttribute("aria-expanded")).toBe("false");
    expect(card.shadowRoot?.activeElement?.tagName).toBe("SUMMARY");
    // Back to step one: the next person to touch the tablet is asked again.
    expect(card.shadowRoot?.querySelector(".picker-step")).not.toBeNull();
  });

  it("forgets the choice when the menu is closed again", async () => {
    const { card } = await mountPicker();

    buttonWithText(card, "Alice")?.click();
    await card.updateComplete;
    expect(card.shadowRoot?.querySelector(".snooze-options")).not.toBeNull();

    const details = card.shadowRoot?.querySelector("details") as HTMLDetailsElement;
    details.open = true;
    details.dispatchEvent(new Event("toggle"));
    details.open = false;
    details.dispatchEvent(new Event("toggle"));
    await card.updateComplete;

    expect(card.shadowRoot?.querySelector(".picker-step")).not.toBeNull();
  });
});

describe("switchboard-alerts-card configured person against the audience", () => {
  let cards: SwitchboardAlertsCard[] = [];

  afterEach(() => {
    for (const card of cards) card.remove();
    cards = [];
  });

  /** The routing table's own audience for `leak`: Alice, Bob, a speaker. */
  const audienceHass = (audience?: string[]) =>
    createFakeHass({
      states: [
        fakeEntity("alert.leak", "on"),
        routingTable([{ ...LEAK_TARGET, snooze_minutes: [15], ...(audience ? { audience } : {}) }]),
      ],
      services: { notify_switchboard: { snooze: {} } },
    });

  it("sends the configured person when the target's audience holds them", async () => {
    const hass = audienceHass();
    const card = await mountCard(
      {
        type: "custom:switchboard-alerts-card",
        mode: "full",
        person: "person.alice",
      },
      hass,
    );
    cards.push(card);

    buttonWithText(card, "Snooze 15 min")?.click();
    await card.updateComplete;
    expect(hass.callService).toHaveBeenCalledWith("notify_switchboard", "snooze", {
      target: "leak",
      minutes: 15,
      person: "person.alice",
    });
  });

  it("snoozes for everyone instead of sending a person the router would refuse", async () => {
    // Carol is not in this target's audience: `notify_switchboard.snooze`
    // would refuse the call (`person_not_in_audience`) and raise a
    // repairs issue. The audience-wide snooze is the honest fallback —
    // and the menu stays, because it still does something.
    const hass = audienceHass(["person.alice"]);
    const card = await mountCard(
      {
        type: "custom:switchboard-alerts-card",
        mode: "full",
        person: "person.carol",
      },
      hass,
    );
    cards.push(card);

    expect(card.shadowRoot?.querySelector(".snooze-menu")).not.toBeNull();
    // The label says what will happen, not what the option asked for.
    const option = buttonWithText(card, "Snooze for everyone · 15 min");
    expect(option).toBeDefined();

    option?.click();
    await card.updateComplete;
    expect(hass.callService).toHaveBeenCalledWith("notify_switchboard", "snooze", {
      target: "leak",
      minutes: 15,
    });
  });

  it("keeps sending the configured person when no row was derived (0.1.x)", async () => {
    const hass = createFakeHass({
      states: [fakeEntity("alert.leak", "on")],
      services: { notify_switchboard: { snooze: {} } },
    });
    const card = await mountCard(
      {
        type: "custom:switchboard-alerts-card",
        mode: "full",
        target_map: { "alert.leak": "leak" },
        snooze_minutes: [15],
        person: "person.carol",
      },
      hass,
    );
    cards.push(card);

    buttonWithText(card, "Snooze 15 min")?.click();
    await card.updateComplete;
    expect(hass.callService).toHaveBeenCalledWith("notify_switchboard", "snooze", {
      target: "leak",
      minutes: 15,
      person: "person.carol",
    });
  });
});
