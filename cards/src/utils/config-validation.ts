/**
 * Config validation shared by both cards.
 *
 * Lovelace calls `setConfig()` before the first render and renders a
 * `hui-error-card` (with our message and the offending YAML) whenever it
 * throws. Every option is therefore validated *there*, so `render()` can
 * assume a well-formed config and never throws itself — a card that throws
 * during render takes the whole dashboard view down with it.
 */
import type { TargetMap } from "../types";

/** Home Assistant entity ids are always `<domain>.<object_id>`, lowercase. */
const ENTITY_ID_RE = /^[a-z][a-z0-9_]*\.[a-z0-9_]+$/;
/** 24h "HH:MM", tolerating a missing leading zero on the hour. */
const TIME_OF_DAY_RE = /^([01]?\d|2[0-3]):([0-5]\d)$/;

function fail(card: string, option: string, expected: string): never {
  throw new Error(`${card}: "${option}" ${expected}`);
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function validateOptionalString(
  card: string,
  option: string,
  value: unknown,
): string | undefined {
  if (value === undefined || value === null) {
    return undefined;
  }
  if (typeof value !== "string") {
    fail(card, option, "must be a string");
  }
  return value;
}

export function validateOptionalBoolean(
  card: string,
  option: string,
  value: unknown,
): boolean | undefined {
  if (value === undefined || value === null) {
    return undefined;
  }
  if (typeof value !== "boolean") {
    fail(card, option, "must be a boolean (true or false)");
  }
  return value;
}

/**
 * A list of entity ids in `domain`. A bare string (the most common YAML
 * slip, `entities: alert.leak`) is rejected explicitly rather than being
 * silently iterated character by character.
 */
export function validateEntityList(
  card: string,
  option: string,
  value: unknown,
  domain: string,
): string[] | undefined {
  if (value === undefined || value === null) {
    return undefined;
  }
  if (!Array.isArray(value)) {
    fail(card, option, `must be a list of ${domain}.* entity ids, not a ${typeof value}`);
  }
  for (const item of value) {
    if (typeof item !== "string" || !ENTITY_ID_RE.test(item) || !item.startsWith(`${domain}.`)) {
      fail(card, option, `must only contain ${domain}.* entity ids (got ${JSON.stringify(item)})`);
    }
  }
  return value as string[];
}

export function validateEntityId(
  card: string,
  option: string,
  value: unknown,
  domain: string,
): string | undefined {
  if (value === undefined || value === null || value === "") {
    return undefined;
  }
  if (typeof value !== "string" || !ENTITY_ID_RE.test(value) || !value.startsWith(`${domain}.`)) {
    fail(card, option, `must be a ${domain}.* entity id (got ${JSON.stringify(value)})`);
  }
  return value;
}

export function validateMode(
  card: string,
  option: string,
  value: unknown,
): "compact" | "full" | undefined {
  if (value === undefined || value === null) {
    return undefined;
  }
  if (value !== "compact" && value !== "full") {
    fail(card, option, `must be "compact" or "full" (got ${JSON.stringify(value)})`);
  }
  return value;
}

export function validatePositiveIntegerList(
  card: string,
  option: string,
  value: unknown,
): number[] | undefined {
  if (value === undefined || value === null) {
    return undefined;
  }
  if (!Array.isArray(value)) {
    fail(card, option, `must be a list of positive whole numbers, not a ${typeof value}`);
  }
  /*
   * An empty list is accepted and means "nothing set here": it is what the
   * editor emits once every duration is cleared, and since router 0.7.0
   * that reads as "derive each target's own durations from the routing
   * table" rather than as a mistake to reject with an error card.
   */
  for (const item of value) {
    if (typeof item !== "number" || !Number.isInteger(item) || item <= 0) {
      fail(card, option, `must only contain positive whole numbers (got ${JSON.stringify(item)})`);
    }
  }
  return value as number[];
}

export function validateStringMap(
  card: string,
  option: string,
  value: unknown,
): TargetMap | undefined {
  if (value === undefined || value === null) {
    return undefined;
  }
  if (!isPlainObject(value)) {
    fail(card, option, `must be a mapping of entity id to slug, not a ${typeof value}`);
  }
  for (const [key, slug] of Object.entries(value)) {
    if (typeof slug !== "string") {
      fail(card, option, `must map every key to a string (${key} is a ${typeof slug})`);
    }
  }
  return value as TargetMap;
}

export function validateTimeOfDay(
  card: string,
  option: string,
  value: unknown,
): string | undefined {
  if (value === undefined || value === null || value === "") {
    return undefined;
  }
  if (typeof value !== "string" || !TIME_OF_DAY_RE.test(value.trim())) {
    fail(card, option, `must be a 24h "HH:MM" time (got ${JSON.stringify(value)})`);
  }
  return value.trim();
}
