export interface FireEventOptions {
  bubbles?: boolean;
  cancelable?: boolean;
  composed?: boolean;
}

/**
 * Dispatches a `CustomEvent`, following the same convention as the Home
 * Assistant frontend's own `fireEvent` helper (bubbling + composed by
 * default so it crosses shadow DOM boundaries, e.g. `hass-more-info` or
 * `config-changed`).
 */
export function fireEvent<T>(
  node: HTMLElement,
  type: string,
  detail?: T,
  options: FireEventOptions = {},
): CustomEvent<T> {
  const event = new CustomEvent<T>(type, {
    bubbles: options.bubbles ?? true,
    cancelable: options.cancelable ?? false,
    composed: options.composed ?? true,
    detail,
  });
  node.dispatchEvent(event);
  return event;
}
