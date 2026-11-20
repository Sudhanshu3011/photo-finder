/**
 * ButtonPill — Accessible Solid Pill Button
 * Enforces WCAG 2.2 touch target (>= 44px), focus rings, and high contrast.
 */

export interface ButtonPillProps {
  label: string;
  onClick?: (event: MouseEvent) => void;
  variant?: "primary" | "secondary";
  iconHtml?: string;
  disabled?: boolean;
  type?: "button" | "submit" | "reset";
  ariaLabel?: string;
  className?: string;
}

export function renderButtonPill(props: ButtonPillProps): string {
  const {
    label,
    variant = "primary",
    iconHtml = "",
    disabled = false,
    type = "button",
    ariaLabel,
    className = "",
  } = props;

  const baseClass = variant === "primary" ? "btn-pill-black" : "btn-secondary";
  const ariaAttr = ariaLabel ? `aria-label="${ariaLabel}"` : "";
  const disabledAttr = disabled ? 'disabled="true" aria-disabled="true"' : "";

  return `
    <button
      type="${type}"
      class="${baseClass} ${className}"
      ${ariaAttr}
      ${disabledAttr}
      style="min-height: 44px; min-width: 44px;"
    >
      <span>${label}</span>
      ${iconHtml ? `<span aria-hidden="true">${iconHtml}</span>` : ""}
    </button>
  `;
}

