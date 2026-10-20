import { LitElement, css, html, nothing, type TemplateResult } from "lit";
import type {
  HaFormSchemaEntry,
  HaFormValueChangedDetail,
  HomeAssistant,
  LovelaceCardConfig,
  LovelaceCardEditor,
} from "../../ha-types";
import type { SwitchboardSilenceTileConfig } from "../../types";
import { sharedStyles } from "../../styles/shared-styles";
import { fireEvent } from "../../utils/fire-event";
import { t, type TranslationKey } from "../../i18n";
import { isHaFormAvailable, prune } from "../../utils/editor-form";

const SCHEMA: HaFormSchemaEntry[] = [
  { name: "person", required: true, selector: { entity: { domain: "person" } } },
  { name: "wake_time", selector: { time: {} } },
  { name: "title", selector: { text: {} } },
];

/** "07:00:00" (the HA time selector's shape) -> "07:00" (our config's). */
function toHhMm(value: unknown): unknown {
  if (typeof value !== "string") {
    return value;
  }
  const match = /^(\d{1,2}):(\d{2})/.exec(value.trim());
  return match ? `${match[1]?.padStart(2, "0")}:${match[2]}` : value;
}

export class SwitchboardSilenceTileEditor extends LitElement implements LovelaceCardEditor {
  static override styles = [
    sharedStyles,
    css`
      .fallback {
        padding: 16px;
        color: var(--secondary-text-color);
      }
    `,
  ];

  static override properties = {
    hass: { attribute: false },
    _config: { state: true },
  };

  hass?: HomeAssistant;
  private _config?: SwitchboardSilenceTileConfig;

  setConfig(config: LovelaceCardConfig): void {
    this._config = config as SwitchboardSilenceTileConfig;
  }

  private _computeLabel = (schema: { name: string }): string =>
    t(this.hass, `editor.${schema.name}` as TranslationKey);

  /**
   * `wake_time` became optional with router 0.7.0: left empty, the tile
   * reads this person's own wake time from
   * `sensor.switchboard_routing_table`.
   */
  private _computeHelper = (schema: { name: string }): string =>
    schema.name === "wake_time" ? t(this.hass, "editor.derived_since_0_7_0") : "";

  private _valueChanged = (event: CustomEvent<HaFormValueChangedDetail>): void => {
    event.stopPropagation();
    const value = { ...(event.detail?.value ?? {}) };
    if ("wake_time" in value) {
      value.wake_time = toHhMm(value.wake_time);
    }

    const config = prune({
      ...this._config,
      ...value,
      type: this._config?.type ?? "custom:switchboard-silence-tile",
    }) as SwitchboardSilenceTileConfig;

    this._config = config;
    fireEvent(this, "config-changed", { config });
  };

  protected override render(): TemplateResult | typeof nothing {
    if (!this._config) {
      return nothing;
    }
    if (!isHaFormAvailable()) {
      return html`<p class="fallback wrap-text">${t(this.hass, "editor.form_unavailable")}</p>`;
    }
    return html`
      <ha-form
        .hass=${this.hass}
        .data=${this._config}
        .schema=${SCHEMA}
        .computeLabel=${this._computeLabel}
        .computeHelper=${this._computeHelper}
        @value-changed=${this._valueChanged}
      ></ha-form>
    `;
  }
}

if (!customElements.get("switchboard-silence-tile-editor")) {
  customElements.define("switchboard-silence-tile-editor", SwitchboardSilenceTileEditor);
}
