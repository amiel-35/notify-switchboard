import type { LovelaceCardConfig } from "./ha-types";

/** Maps an `alert.*` entity id to the Notify Switchboard target slug that owns it. */
export type TargetMap = Record<string, string>;

export interface SwitchboardAlertsCardConfig extends LovelaceCardConfig {
  type: "custom:switchboard-alerts-card";
  entities?: string[];
  mode?: "compact" | "full";
  show_acknowledged?: boolean;
  title?: string;
  /**
   * Optional since router 0.7.0: `sensor.switchboard_routing_table` names
   * the `alert.*` of every target. Set it to override the router, or to
   * map an alert the router does not own.
   */
  target_map?: TargetMap;
  /**
   * Optional since router 0.7.0: each target carries its own
   * `snooze_minutes`. Set it to offer the same durations everywhere.
   */
  snooze_minutes?: number[];
  /**
   * Optional `person.*` entity the snooze applies to. Notify Switchboard's
   * `snooze` service silences a target for the whole audience when no
   * person is given, so the menu says so explicitly when this is unset.
   */
  person?: string;
  /**
   * Kiosk mode: ask *who* the snooze is for before offering durations,
   * choosing among the persons the routing table publishes. Acknowledge
   * never asks — the router reads the acting user from the call itself.
   */
  person_picker?: boolean;
}

export interface SwitchboardSilenceTileConfig extends LovelaceCardConfig {
  type: "custom:switchboard-silence-tile";
  person?: string;
  /**
   * Optional since router 0.7.0: the routing table carries each person's
   * own wake time. Set it to override the router for this tile.
   */
  wake_time?: string;
  title?: string;
}

export const DEFAULT_SNOOZE_MINUTES: number[] = [15, 60, 480];
export const DEFAULT_WAKE_TIME = "07:00";

/** Entity ids published by the router, read for the card footer when present. */
export const DROPPED_TODAY_ENTITY = "sensor.switchboard_dropped_today";
export const DELIVERY_EVENT_ENTITY = "event.switchboard_delivery";
/** Router 0.7.0's routing table: the source of every derived option. */
export const ROUTING_TABLE_ENTITY = "sensor.switchboard_routing_table";

/**
 * The states a core `alert.*` entity can be in, plus the two states every
 * Home Assistant entity can fall into when its integration is not
 * providing data. `unavailable` / `unknown` are a distinct fourth case:
 * they are emphatically *not* "acknowledged".
 */
export type AlertState = "idle" | "on" | "off" | "unavailable" | "unknown";

/** How the card classifies one configured row for display. */
export type AlertRowKind = "active" | "acknowledged" | "unavailable" | "missing";
