export function renderButtonPill(props) {
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

