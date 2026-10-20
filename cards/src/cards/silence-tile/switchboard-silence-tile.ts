import { LitElement, css, html, nothing, type PropertyValues, type TemplateResult } from "lit";
import type {
  HassEntity,
  HomeAssistant,
  LovelaceCard,
  LovelaceCardConfig,
  LovelaceGridOptions,
} from "../../ha-types";
import type { SwitchboardSilenceTileConfig } from "../../types";
import { DEFAULT_WAKE_TIME, ROUTING_TABLE_ENTITY } from "../../types";
import { sharedStyles } from "../../styles/shared-styles";
import { t } from "../../i18n";
import { formatRelativeDuration } from "../../utils/format-duration";
import { minutesUntilWakeTime } from "../../utils/wake-time";
import { hasRouterService, SWITCHBOARD_DOMAIN } from "../../utils/router-services";
import { readRoutingTable, wakeTimeForPerson } from "../../utils/routing-table";
import {
  validateEntityId,
  validateOptionalString,
  validateTimeOfDay,
} from "../../utils/config-validation";

const TICK_INTERVAL_MS = 30_000;
const CARD_NAME = "switchboard-silence-tile";

/**
 * `switchboard-silence-tile` shows one person's Notify Switchboard silence
 * state (`binary_sensor.<person>_silenced`, `sensor.<person>_active_snoozes`,
 * `sensor.<person>_last_notification`) with silence / clear controls. The
 * router services those controls call (`notify_switchboard.silence` /
 * `unsnooze` / `unsilence`) only exist from 0.2.0 onward, so every button
 * marks itself `aria-disabled` (staying focusable, so a screen-reader user
 * can find out *why*) and the tile shows a one-line explanation.
 */
export class SwitchboardSilenceTile extends LitElement implements LovelaceCard {
  static override styles = [
    sharedStyles,
    css`
      .header {
        display: flex;
        align-items: center;
        gap: 8px;
        padding: 16px 16px 0;
        font-weight: 500;
      }

      .body {
        padding: 16px;
        display: flex;
        flex-direction: column;
        gap: 12px;
      }

      .status-row {
        display: flex;
        align-items: center;
        gap: 8px;
        flex-wrap: wrap;
      }

      .detail {
        color: var(--secondary-text-color);
        font-size: 0.9rem;
      }

      .actions {
        display: flex;
        flex-wrap: wrap;
        gap: 8px;
      }
    `,
  ];

  static override properties = {
    hass: { attribute: false },
    _config: { state: true },
    _now: { state: true },
  };

  hass?: HomeAssistant;
  private _config?: SwitchboardSilenceTileConfig;
  private _now = Date.now();
  private _tickHandle?: ReturnType<typeof setInterval>;

  static getConfigElement(): HTMLElement {
    return document.createElement("switchboard-silence-tile-editor");
  }

  static getStubConfig(hass?: HomeAssistant): SwitchboardSilenceTileConfig {
    const person = Object.keys(hass?.states ?? {}).find((id) => id.startsWith("person."));
    const stub: SwitchboardSilenceTileConfig = {
      type: "custom:switchboard-silence-tile",
      wake_time: DEFAULT_WAKE_TIME,
    };
    if (person) {
      stub.person = person;
    }
    return stub;
  }

  setConfig(config: LovelaceCardConfig): void {
    if (!config || typeof config !== "object" || Array.isArray(config)) {
      throw new Error(`${CARD_NAME}: configuration must be a mapping`);
    }
    const raw = config as Record<string, unknown>;

    const validated: SwitchboardSilenceTileConfig = {
      ...(config as SwitchboardSilenceTileConfig),
    };

    /*
     * `wake_time` is deliberately not defaulted here. Router 0.7.0
     * publishes each person's own wake time in the routing table, and a
     * config silently carrying "07:00" would shadow it for every
     * household whose morning is not seven o'clock. The fallback chain —
     * option, then routing table, then 07:00 — is resolved at render
     * time, where both sources are known.
     */
    const wakeTime = validateTimeOfDay(CARD_NAME, "wake_time", raw.wake_time);
    if (wakeTime === undefined) {
      delete validated.wake_time;
    } else {
      validated.wake_time = wakeTime;
    }

    const person = validateEntityId(CARD_NAME, "person", raw.person, "person");
    if (person === undefined) {
      delete validated.person;
    } else {
      validated.person = person;
    }

    const title = validateOptionalString(CARD_NAME, "title", raw.title);
    if (title === undefined) {
      delete validated.title;
    } else {
      validated.title = title;
    }

    this._config = validated;
  }

  getCardSize(): number {
    return 3;
  }

  getGridOptions(): LovelaceGridOptions {
    return { rows: "auto", columns: 6, min_rows: 2, min_columns: 3 };
  }

  override connectedCallback(): void {
    super.connectedCallback();
    this._tickHandle = setInterval(() => {
      // Only the "last notification" line ages; skip the tick otherwise.
      if (this._hasLiveDuration()) {
        this._now = Date.now();
      }
    }, TICK_INTERVAL_MS);
  }

  override disconnectedCallback(): void {
    super.disconnectedCallback();
    if (this._tickHandle) {
      clearInterval(this._tickHandle);
      this._tickHandle = undefined;
    }
  }

  protected override shouldUpdate(changed: PropertyValues): boolean {
    if (changed.size !== 1 || !changed.has("hass")) {
      return true;
    }
    const oldHass = changed.get("hass") as HomeAssistant | undefined;
    const hass = this.hass;
    if (!oldHass || !hass) {
      return true;
    }
    if (oldHass.services !== hass.services || oldHass.locale !== hass.locale) {
      return true;
    }
    for (const entityId of this._watchedEntityIds()) {
      if (oldHass.states[entityId] !== hass.states[entityId]) {
        return true;
      }
    }
    return false;
  }

  /** The person plus the three entities derived from its object id. */
  private _watchedEntityIds(): string[] {
    const person = this._config?.person;
    const objectId = this._objectId();
    if (!person || !objectId) {
      return person ? [person, ROUTING_TABLE_ENTITY] : [ROUTING_TABLE_ENTITY];
    }
    return [
      person,
      `binary_sensor.${objectId}_silenced`,
      `sensor.${objectId}_active_snoozes`,
      `sensor.${objectId}_last_notification`,
      ROUTING_TABLE_ENTITY,
    ];
  }

  private _objectId(): string | undefined {
    const person = this._config?.person;
    if (!person || !person.includes(".")) {
      return undefined;
    }
    return person.split(".")[1];
  }

  private _hasLiveDuration(): boolean {
    const objectId = this._objectId();
    if (!objectId) {
      return false;
    }
    const state = this.hass?.states[`sensor.${objectId}_last_notification`]?.state;
    return Boolean(state) && state !== "unknown" && state !== "unavailable" && state !== "none";
  }

  protected override render(): TemplateResult | typeof nothing {
    const hass = this.hass;
    const config = this._config;
    if (!hass || !config) {
      return nothing;
    }

    const title = config.title ?? t(hass, "silence.title");
    const objectId = this._objectId();

    if (!config.person || !objectId) {
      return html`
        <ha-card .header=${title}>
          <div class="body"><p class="empty-state">${t(hass, "silence.not_configured")}</p></div>
        </ha-card>
      `;
    }

    const personState = hass.states[config.person];
    const silencedState = hass.states[`binary_sensor.${objectId}_silenced`];
    const snoozesState = hass.states[`sensor.${objectId}_active_snoozes`];
    const lastNotificationState = hass.states[`sensor.${objectId}_last_notification`];

    const headerName = personState?.attributes.friendly_name ?? config.person;
    const headerIcon = personState?.attributes.icon ?? "mdi:account";

    return html`
      <ha-card>
        <div class="header">
          <ha-icon icon=${headerIcon}></ha-icon>
          <span class="wrap-text"
            >${title !== headerName ? `${title} — ${headerName}` : title}</span
          >
        </div>
        <div class="body">
          ${
            !personState
              ? html`<p class="empty-state">${t(hass, "silence.person_missing")}</p>`
              : nothing
          }
          ${this._renderSilencedStatus(silencedState)} ${this._renderSnoozes(snoozesState)}
          ${this._renderLastNotification(lastNotificationState)} ${this._renderActions()}
        </div>
      </ha-card>
    `;
  }

  private _renderSilencedStatus(silencedState: HassEntity | undefined): TemplateResult {
    const hass = this.hass;
    let text: string;
    let chipClass: string;
    let icon: string;
    if (
      !silencedState ||
      silencedState.state === "unknown" ||
      silencedState.state === "unavailable"
    ) {
      text = t(hass, "silence.state.unknown");
      chipClass = "chip-neutral";
      icon = "mdi:help-circle-outline";
    } else if (silencedState.state === "on") {
      text = t(hass, "silence.state.silenced");
      chipClass = "chip-active";
      icon = "mdi:bell-off";
    } else {
      text = t(hass, "silence.state.not_silenced");
      chipClass = "chip-acknowledged";
      icon = "mdi:bell-ring";
    }
    return html`
      <div class="status-row">
        <span class="chip ${chipClass}">
          <ha-icon icon=${icon} aria-hidden="true"></ha-icon>${text}
        </span>
      </div>
    `;
  }

  /**
   * `unavailable` / `unknown` (and a missing sensor) mean "we do not know",
   * which is not the same claim as "no snoozes" — `Number("unknown")` is
   * `NaN`, and reporting that as zero would be a lie.
   */
  private _renderSnoozes(snoozesState: HassEntity | undefined): TemplateResult {
    const hass = this.hass;
    const raw = snoozesState?.state;
    if (raw === undefined || raw === "unknown" || raw === "unavailable") {
      return html`<div class="detail wrap-text">${t(hass, "silence.snoozes.unknown")}</div>`;
    }
    const count = Number(raw);
    if (!Number.isFinite(count)) {
      return html`<div class="detail wrap-text">${t(hass, "silence.snoozes.unknown")}</div>`;
    }
    const text =
      count > 0 ? t(hass, "silence.snoozes.count", { count }) : t(hass, "silence.snoozes.none");
    return html`<div class="detail wrap-text">${text}</div>`;
  }

  private _renderLastNotification(lastNotificationState: HassEntity | undefined): TemplateResult {
    const hass = this.hass;
    const state = lastNotificationState?.state;
    if (!state || state === "unknown" || state === "unavailable" || state === "none") {
      return html`<div class="detail wrap-text">${t(hass, "silence.last_notification.none")}</div>`;
    }
    const asDate = new Date(state);
    const value = Number.isNaN(asDate.getTime())
      ? state
      : formatRelativeDuration(
          state,
          hass?.locale?.language ?? hass?.language ?? "en",
          new Date(this._now),
        );
    return html`
      <div class="detail wrap-text">${t(hass, "silence.last_notification.label", { value })}</div>
    `;
  }

  /**
   * The wake time "Until wake" silences until: the card's own option
   * first, then this person's `wake_time` from
   * `sensor.switchboard_routing_table` (router 0.7.0), then 07:00. With
   * an older router the middle step simply is not there and the
   * behaviour is the 0.1.x one.
   */
  private _wakeTime(): string {
    const configured = this._config?.wake_time;
    if (configured) {
      return configured;
    }
    const derived = wakeTimeForPerson(readRoutingTable(this.hass), this._config?.person);
    return derived ?? DEFAULT_WAKE_TIME;
  }

  private _renderActions(): TemplateResult {
    const hass = this.hass;
    if (!hass) return html``;

    const canSilence = hasRouterService(hass, "silence");
    const canUnsnooze = hasRouterService(hass, "unsnooze");
    const canUnsilence = hasRouterService(hass, "unsilence");
    const wakeTime = this._wakeTime();
    const wakeMinutes = minutesUntilWakeTime(wakeTime, new Date(), hass.config?.time_zone);
    const explanation = t(hass, "silence.service_unavailable");
    const anyMissing = !canSilence || !canUnsnooze || !canUnsilence;

    return html`
      <div class="actions">
        ${this._renderAction(t(hass, "silence.action.silence_1h"), canSilence, explanation, () =>
          this._silence(60),
        )}
        ${this._renderAction(
          t(hass, "silence.action.until_wake"),
          canSilence && wakeMinutes !== null,
          explanation,
          () => wakeMinutes !== null && this._silence(wakeMinutes),
        )}
        ${this._renderAction(
          t(hass, "silence.action.clear_snoozes"),
          canUnsnooze,
          explanation,
          () => this._clearSnoozes(),
        )}
        ${this._renderAction(t(hass, "silence.action.clear"), canUnsilence, explanation, () =>
          this._unsilence(),
        )}
      </div>
      ${
        anyMissing
          ? html`<p id="switchboard-service-hint" class="hint wrap-text">${explanation}</p>`
          : nothing
      }
    `;
  }

  /**
   * `aria-disabled` rather than `disabled`: the control keeps its place in
   * the tab order so a keyboard or screen-reader user can reach it and
   * hear the reason, and the click handler simply does nothing.
   */
  private _renderAction(
    label: string,
    enabled: boolean,
    explanation: string,
    action: () => void,
  ): TemplateResult {
    return html`
      <button
        class="action-button touch-target"
        type="button"
        aria-disabled=${enabled ? "false" : "true"}
        aria-describedby=${enabled ? nothing : "switchboard-service-hint"}
        title=${enabled ? nothing : explanation}
        @click=${() => {
          if (enabled) action();
        }}
      >
        ${label}
      </button>
    `;
  }

  private async _silence(minutes: number): Promise<void> {
    const hass = this.hass;
    const person = this._config?.person;
    if (!hass || !person || !hasRouterService(hass, "silence")) return;
    await hass.callService(SWITCHBOARD_DOMAIN, "silence", { person, minutes });
  }

  private async _clearSnoozes(): Promise<void> {
    const hass = this.hass;
    const person = this._config?.person;
    if (!hass || !person || !hasRouterService(hass, "unsnooze")) return;
    await hass.callService(SWITCHBOARD_DOMAIN, "unsnooze", { person });
  }

  /**
   * Lifting a silence is its own 0.2.0 service. It is *not* expressible as
   * `silence(minutes: 0)` — that call is not in the router's contract and
   * was previously being invented by this card.
   */
  private async _unsilence(): Promise<void> {
    const hass = this.hass;
    const person = this._config?.person;
    if (!hass || !person || !hasRouterService(hass, "unsilence")) return;
    await hass.callService(SWITCHBOARD_DOMAIN, "unsilence", { person });
  }
}

if (!customElements.get("switchboard-silence-tile")) {
  customElements.define("switchboard-silence-tile", SwitchboardSilenceTile);
}
