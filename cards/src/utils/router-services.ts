import type { HomeAssistant } from "../ha-types";
import type { TargetMap } from "../types";
import { DEFAULT_SNOOZE_MINUTES } from "../types";
import { targetBySlug, targetForAlert, type RoutingTable } from "./routing-table";

export const SWITCHBOARD_DOMAIN = "notify_switchboard";

export type RouterServiceName = "acknowledge" | "snooze" | "silence" | "unsnooze" | "unsilence";

/**
 * The router services (`notify_switchboard.acknowledge` / `snooze` /
 * `silence` / `unsnooze` / `unsilence`) only land in Notify Switchboard
 * 0.2.0. Cards must
 * keep working against 0.1.x by checking `hass.services` before calling
 * them and degrading to the native `alert.*` actions instead.
 */
export function hasRouterService(hass: HomeAssistant, service: RouterServiceName): boolean {
  return Boolean(hass.services?.[SWITCHBOARD_DOMAIN]?.[service]);
}

/**
 * Resolves the Notify Switchboard target slug for an `alert.*` entity from
 * the card's configured `target_map` (e.g. `{ "alert.leak": "leak" }`).
 * Returns `undefined` when the entity is not mapped, in which case only
 * the native `alert.turn_off` / `alert.turn_on` actions are safe to use.
 */
export function resolveTargetSlug(
  entityId: string,
  targetMap: TargetMap | undefined,
): string | undefined {
  return targetMap?.[entityId];
}

/**
 * What the alerts card needs to know about one alert row's target, from
 * both sources at once: the card's own `target_map` / `snooze_minutes`
 * options and, since router 0.7.0, `sensor.switchboard_routing_table`.
 *
 * The user's options always win — they are overrides, not a fallback —
 * and everything they leave unset is derived from the table. With no
 * table (router below 0.7.0, or the entity `unavailable`) this collapses
 * to exactly the 0.1.x behaviour: the slug comes from `target_map` or
 * nowhere.
 */
export interface ResolvedAlertTarget {
  slug: string | undefined;
  /** Where the slug came from — reported in the UI, not just diagnostics. */
  source: "config" | "routing_table" | "none";
  /**
   * `false` when the routing table says this target refuses
   * acknowledgement — either because it opts out or because it has no
   * `alert.*` to turn off, which is the router's own test
   * (`bool(alert_entity) and allow_acknowledge`). In both cases
   * `notify_switchboard.acknowledge` would refuse the call and the card
   * uses `alert.turn_off` instead.
   */
  allowAcknowledge: boolean;
  /**
   * The durations to offer: the target's own list — **empty included**,
   * which is the router saying snooze is off for this target — narrowed
   * by the card's options when it sets any; the card's options alone when
   * the table describes no row for this slug; and the built-in default
   * when neither says anything.
   */
  snoozeMinutes: number[];
  /**
   * The row's audience, verbatim (bare `notify.*` outputs included), or
   * `undefined` when no row was derived. Scopes the person picker.
   */
  audience: string[] | undefined;
}

export function resolveAlertTarget(
  entityId: string,
  options: {
    targetMap?: TargetMap;
    snoozeMinutes?: number[];
  },
  table: RoutingTable | undefined,
): ResolvedAlertTarget {
  const configured = resolveTargetSlug(entityId, options.targetMap);
  const derived = targetForAlert(table, entityId);
  const slug = configured ?? derived?.slug;
  const row = configured ? (targetBySlug(table, configured) ?? derived) : derived;

  /*
   * An empty `snooze_minutes` on a row is not "say nothing": the router
   * refuses any duration that is not in the row's own list
   * (`snooze_minutes_not_offered`, dispatcher `async_service_snooze`), so
   * an empty list means snooze is off for that target and the card must
   * offer none. The built-in default therefore applies only when no row
   * was derived at all — the 0.1.x path, where the card is the only
   * source of durations.
   *
   * For the same reason the card's own `snooze_minutes` is a filter, not
   * an escape hatch: where the table describes the very slug the card
   * will call, an override can only narrow that row's list, and an empty
   * intersection is a snooze menu with nothing left to offer — the card
   * hides it rather than showing buttons the router would refuse.
   */
  const rowForSlug = row && row.slug === slug ? row : undefined;
  const overrides =
    options.snoozeMinutes && options.snoozeMinutes.length > 0 ? options.snoozeMinutes : undefined;
  const snoozeMinutes = overrides
    ? // Without a row for this slug — an older router, or a `target_map`
      // naming a target it does not publish — the override is the sole
      // source, exactly as in 0.1.x.
      rowForSlug
      ? overrides.filter((minutes) => rowForSlug.snoozeMinutes.includes(minutes))
      : overrides
    : row
      ? row.snoozeMinutes
      : DEFAULT_SNOOZE_MINUTES;

  return {
    slug,
    source: configured ? "config" : derived ? "routing_table" : "none",
    // The router's own condition: a row with no `alert.*` has nothing to
    // turn off, whatever `allow_acknowledge` says.
    allowAcknowledge: row ? row.allowAcknowledge !== false && row.alertEntity !== null : true,
    snoozeMinutes,
    audience: row?.audience,
  };
}
