/**
 * UnderlineText — Hand-drawn Ochre Underline
 * Renders an organic curved accent underline beneath text.
 */

export interface UnderlineTextProps {
  text: string;
  className?: string;
}

export function renderUnderlineText(props: UnderlineTextProps): string {
  const { text, className = "" } = props;
  return `<span class="hl-underline ${className}">${text}</span>`;
}

