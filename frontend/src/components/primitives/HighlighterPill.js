export function renderHighlighterPill(props) {
  const { text, variant = "mint", className = "" } = props;
  return `<span class="hl-pill ${variant} ${className}">${text}</span>`;
}

