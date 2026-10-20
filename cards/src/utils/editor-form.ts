/**
 * Helpers shared by both `ha-form`-based editors.
 */

/**
 * `ha-form` / `ha-selector` are runtime globals registered by the Home
 * Assistant frontend, so they are never imported — only feature-detected.
 * Outside HA (unit tests, a bare page) the editor renders a YAML hint
 * instead of an empty box.
 */
export function isHaFormAvailable(): boolean {
  return typeof customElements !== "undefined" && Boolean(customElements.get("ha-form"));
}

function isEmptyValue(value: unknown): boolean {
  if (value === undefined || value === null || value === "") {
    return true;
  }
  if (Array.isArray(value)) {
    return value.length === 0;
  }
  if (typeof value === "object") {
    return Object.keys(value as Record<string, unknown>).length === 0;
  }
  return false;
}

/**
 * Drops keys whose value is empty so the emitted config never contains
 * noise like `title: ""` or `target_map: {}`. `false` and `0` are values,
 * not emptiness, and survive.
 */
export function prune<T extends Record<string, unknown>>(config: T): T {
  const out: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(config)) {
    if (!isEmptyValue(value)) {
      out[key] = value;
    }
  }
  return out as T;
}
