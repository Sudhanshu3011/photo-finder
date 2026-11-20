/**
 * Utility helper for merging Tailwind / CSS class names.
 * Compatible with shadcn/ui.
 */
export function cn(...inputs: any[]): string {
  return inputs
    .flat()
    .filter(Boolean)
    .join(" ");
}

