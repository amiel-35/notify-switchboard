/**
 * Reading `sensor.switchboard_routing_table`.
 *
 * Notify Switchboard 0.7.0 publishes the routing table the cards used to
 * ask the user to restate in YAML: which `alert.*` belongs to which
 * target, that target's snooze durations and whether it accepts an
 * acknowledgement, plus each configured person's wake time.
 *
 * The router's contract (docs/contract.md, §"`sensor.switchboard_routing_table`")
 * freezes the shape: the state is the number of targets, and there are
 * exactly two attributes, `targets` and `persons`, both **closed** lists.
 * `alert_entity` and `wake_time` are `null` when the row has none — never
 * absent — and `wake_time` is the `"HH:MM:SS"` string the options carry.
 *
 * Everything below is defensive anyway: a card must survive a router that
 * is older, newer, mid-reload (`unavailable`) or simply wrong, so a
 * malformed row is dropped rather than trusted, and a missing entity means
 * "derive nothing", which is exactly the 0.1.x behaviour.
 */
import type { HomeAssistant } from "../ha-types";
import { ROUTING_TABLE_ENTITY } from "../types";

export interface RoutingTableTarget {
  slug: string;
  name?: string;
  /** `null` when the target has no alert entity. */
  alertEntity: string | null;
  /** The target's own snooze durations, in minutes. Empty when unusable. */
  snoozeMinutes: number[];
  /** `false` only when the router says so; `undefined` when it does not say. */
  allowAcknowledge: boolean | undefined;
  audience: string[];
}

export interface RoutingTablePerson {
  entityId: string;
  /** `"HH:MM"`, normalised from the router's `"HH:MM:SS"`. `null` when none. */
  wakeTime: string | null;
  summary: boolean | undefined;
}

export interface RoutingTable {
  targets: RoutingTableTarget[];
  persons: RoutingTablePerson[];
}

const HH_MM_SS_RE = /^(\d{1,2}):([0-5]\d)(?::([0-5]\d))?$/;

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function asStringList(value: unknown): string[] {
  return Array.isArray(value)
    ? value.filter((item): item is string => typeof item === "string")
    : [];
}

function asMinutes(value: unknown): number[] {
  return Array.isArray(value)
    ? value.filter(
        (item): item is number => typeof item === "number" && Number.isInteger(item) && item > 0,
      )
    : [];
}

/** `"07:00:00"` / `"7:00"` -> `"07:00"`; anything else -> `null`. */
export function normaliseWakeTime(value: unknown): string | null {
  if (typeof value !== "string") {
    return null;
  }
  const match = HH_MM_SS_RE.exec(value.trim());
  if (!match) {
    return null;
  }
  const hours = Number(match[1]);
  if (hours > 23) {
    return null;
  }
  return `${String(hours).padStart(2, "0")}:${match[2]}`;
}

function parseTarget(raw: unknown): RoutingTableTarget | undefined {
  if (!isPlainObject(raw) || typeof raw.slug !== "string" || raw.slug === "") {
    return undefined;
  }
  return {
    slug: raw.slug,
    ...(typeof raw.name === "string" ? { name: raw.name } : {}),
    alertEntity: typeof raw.alert_entity === "string" ? raw.alert_entity : null,
    snoozeMinutes: asMinutes(raw.snooze_minutes),
    allowAcknowledge:
      typeof raw.allow_acknowledge === "boolean" ? raw.allow_acknowledge : undefined,
    audience: asStringList(raw.audience),
  };
}

/** A person is a `person.*` and nothing else — the picker sends this id to the router. */
const PERSON_ENTITY_RE = /^person\.[a-z0-9_]+$/;

function parsePerson(raw: unknown): RoutingTablePerson | undefined {
  if (
    !isPlainObject(raw) ||
    typeof raw.entity_id !== "string" ||
    !PERSON_ENTITY_RE.test(raw.entity_id)
  ) {
    return undefined;
  }
  return {
    entityId: raw.entity_id,
    wakeTime: normaliseWakeTime(raw.wake_time),
    summary: typeof raw.summary === "boolean" ? raw.summary : undefined,
  };
}

/**
 * Reads the routing table entity, or returns `undefined` when the router
 * does not publish it (below 0.7.0), when it is `unavailable` / `unknown`
 * (a reload in flight), or when `targets` is not a list. The caller
 * then falls back to the card's own options, unchanged.
 */
export function readRoutingTable(hass: HomeAssistant | undefined): RoutingTable | undefined {
  const stateObj = hass?.states?.[ROUTING_TABLE_ENTITY];
  if (!stateObj || stateObj.state === "unavailable" || stateObj.state === "unknown") {
    return undefined;
  }
  const rawTargets = stateObj.attributes.targets;
  const rawPersons = stateObj.attributes.persons;
  // `targets` is the half every derivation rests on, so it is what makes
  // a payload a routing table: persons alone would have the cards report
  // an empty target list as if the router had published one.
  if (!Array.isArray(rawTargets)) {
    return undefined;
  }
  const targets = rawTargets
    .map(parseTarget)
    .filter((target): target is RoutingTableTarget => target !== undefined);
  const persons = (Array.isArray(rawPersons) ? rawPersons : [])
    .map(parsePerson)
    .filter((person): person is RoutingTablePerson => person !== undefined);
  return { targets, persons };
}

/** The target that owns `alertEntityId`, if the table names one. */
export function targetForAlert(
  table: RoutingTable | undefined,
  alertEntityId: string,
): RoutingTableTarget | undefined {
  return table?.targets.find((target) => target.alertEntity === alertEntityId);
}

/** The target with this slug — used when a `target_map` override named it. */
export function targetBySlug(
  table: RoutingTable | undefined,
  slug: string,
): RoutingTableTarget | undefined {
  return table?.targets.find((target) => target.slug === slug);
}

/** The wake time (`"HH:MM"`) the router holds for this person, if any. */
export function wakeTimeForPerson(
  table: RoutingTable | undefined,
  personEntityId: string | undefined,
): string | undefined {
  if (!personEntityId) {
    return undefined;
  }
  return table?.persons.find((person) => person.entityId === personEntityId)?.wakeTime ?? undefined;
}

/**
 * The persons the picker may offer for one target, named from their
 * `person.*` state when the state machine has one. A person the router
 * knows but the frontend does not is still offered — under its entity id —
 * rather than silently dropped, because the router will happily snooze
 * for it.
 *
 * `audience` is that target's own audience, and the list is its
 * intersection with the configured persons: `notify_switchboard.snooze`
 * refuses a person who is not in the row's audience
 * (`person_not_in_audience`) and raises a `repairs` issue when a card
 * keeps asking, so offering one is offering a button that cannot work.
 * The intersection also drops the audience's bare `notify.*` outputs,
 * which are not persons and have no snooze at all (contract §"Bare
 * outputs").
 *
 * `undefined` means "no audience is known" — no routing-table row was
 * derived for this alert — and the whole list is offered, exactly as
 * before: narrowing on an audience nobody published would hide the picker
 * rather than protect it.
 */
export function personChoices(
  table: RoutingTable | undefined,
  hass: HomeAssistant | undefined,
  audience?: string[] | undefined,
): Array<{ entityId: string; name: string }> {
  const persons =
    audience === undefined
      ? (table?.persons ?? [])
      : (table?.persons ?? []).filter((person) => audience.includes(person.entityId));
  return persons.map((person) => {
    const stateObj = hass?.states?.[person.entityId];
    const friendlyName = stateObj?.attributes.friendly_name;
    return {
      entityId: person.entityId,
      name:
        typeof friendlyName === "string" && friendlyName !== "" ? friendlyName : person.entityId,
    };
  });
}
