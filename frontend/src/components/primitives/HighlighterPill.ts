/**
 * HighlighterPill — Elementum Pastel Capsule
 * Wraps text in high-contrast pastel pills (mint, rose, butter).
 */

export type PillVariant = "mint" | "rose" | "butter";

export interface HighlighterPillProps {
  text: string;
  variant?: PillVariant;
  className?: string;
}

export function renderHighlighterPill(props: HighlighterPillProps): string {
  const { text, variant = "mint", className = "" } = props;
  return `<span class="hl-pill ${variant} ${className}">${text}</span>`;
}

