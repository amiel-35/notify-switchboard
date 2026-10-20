import { vi } from "vitest";
import type { HassEntity, HassServices, HomeAssistant } from "../src/ha-types";

export function fakeEntity(
  entityId: string,
  state: string,
  overrides: Partial<HassEntity> = {},
): HassEntity {
  return {
    entity_id: entityId,
    state,
    attributes: {},
    last_changed: overrides.last_changed ?? new Date().toISOString(),
    last_updated: overrides.last_updated ?? new Date().toISOString(),
    ...overrides,
  };
}

export interface FakeHassOptions {
  states?: HassEntity[];
  services?: HassServices;
  language?: string;
  timeZone?: string;
}

export function createFakeHass(options: FakeHassOptions = {}): HomeAssistant {
  const states: Record<string, HassEntity> = {};
  for (const entity of options.states ?? []) {
    states[entity.entity_id] = entity;
  }
  return {
    states,
    services: options.services ?? {},
    config: { time_zone: options.timeZone ?? "UTC" },
    locale: { language: options.language ?? "en" },
    callService: vi.fn().mockResolvedValue(undefined),
  };
}

/**
 * Produces the *new* `hass` object Home Assistant hands a card after a
 * state change: a fresh top-level object and a fresh `states` map, with
 * only the touched entities replaced. Everything else keeps its identity,
 * which is exactly what `shouldUpdate` relies on.
 */
export function withUpdatedStates(hass: HomeAssistant, ...entities: HassEntity[]): HomeAssistant {
  const states = { ...hass.states };
  for (const entity of entities) {
    states[entity.entity_id] = entity;
  }
  return { ...hass, states };
}
