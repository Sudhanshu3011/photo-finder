export function renderUnderlineText(props) {
  const { text, className = "" } = props;
  return `<span class="hl-underline ${className}">${text}</span>`;
}

