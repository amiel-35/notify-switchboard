import { css } from "lit";

/**
 * Shared visual rules for both cards and their editors:
 * - only theme CSS variables are used for color, never hardcoded hex;
 * - the host is transparent: `ha-card` paints the surface, so the card
 *   inherits whatever background the active theme gives it;
 * - every interactive control keeps a >=48px touch target;
 * - focus is always visible (never `outline: none` without a replacement);
 * - text wraps instead of truncating, even at 200% zoom;
 * - a control that cannot act is `aria-disabled`, not `disabled`, so it
 *   stays reachable by keyboard and screen readers can announce why;
 * - motion is skipped for users who asked for it.
 */
export const sharedStyles = css`
  :host {
    display: block;
    color: var(--primary-text-color);
  }

  * {
    box-sizing: border-box;
  }

  button {
    font-family: inherit;
    font-size: inherit;
    color: inherit;
  }

  .touch-target {
    min-height: 48px;
    min-width: 48px;
  }

  button:focus-visible,
  [tabindex]:focus-visible,
  summary:focus-visible,
  a:focus-visible {
    outline: 2px solid var(--primary-color, #03a9f4);
    outline-offset: 2px;
  }

  .wrap-text {
    white-space: normal;
    overflow-wrap: anywhere;
    word-break: break-word;
  }

  .chip {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    padding: 2px 10px;
    border-radius: 12px;
    font-size: 0.8125rem;
    font-weight: 500;
    border: 1px solid currentColor;
  }

  .chip ha-icon {
    --mdc-icon-size: 16px;
    width: 16px;
    height: 16px;
  }

  .chip.chip-active {
    color: var(--error-color, #db4437);
  }

  .chip.chip-acknowledged {
    color: var(--success-color, var(--state-icon-active-color, #43a047));
  }

  .chip.chip-neutral {
    color: var(--secondary-text-color);
  }

  .chip.chip-unavailable {
    color: var(--warning-color, var(--secondary-text-color));
  }

  .empty-state {
    padding: 16px;
    text-align: center;
    color: var(--secondary-text-color);
  }

  .hint {
    margin: 0;
    color: var(--secondary-text-color);
    font-size: 0.8125rem;
  }

  .action-button {
    min-height: 48px;
    padding: 0 16px;
    border-radius: 8px;
    border: 1px solid var(--divider-color, rgba(127, 127, 127, 0.3));
    background: var(--secondary-background-color, transparent);
    color: var(--primary-color, inherit);
    cursor: pointer;
    white-space: normal;
    overflow-wrap: anywhere;
  }

  .action-button[aria-disabled="true"],
  .action-button:disabled {
    cursor: not-allowed;
    opacity: 0.5;
  }

  .action-button:hover:not(:disabled):not([aria-disabled="true"]) {
    background: var(--primary-color, rgba(3, 169, 244, 0.1));
    color: var(--text-primary-color, #fff);
  }

  @media (prefers-reduced-motion: reduce) {
    * {
      transition: none !important;
      animation: none !important;
    }
  }
`;
