/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        ground: "var(--ground)",
        card: "var(--card)",
        muted: {
          DEFAULT: "var(--surface-muted)",
          foreground: "var(--ink-muted)",
        },
        "mint-field": "var(--mint-field)",
        ink: {
          DEFAULT: "var(--ink-primary)",
          secondary: "var(--ink-secondary)",
          muted: "var(--ink-muted)",
        },
        ochre: "var(--accent-ochre)",
        pill: {
          mint: "var(--pill-mint-bg)",
          "mint-text": "var(--pill-mint-fg)",
          rose: "var(--pill-rose-bg)",
          "rose-text": "var(--pill-rose-fg)",
          butter: "var(--pill-butter-bg)",
          "butter-text": "var(--pill-butter-fg)",
        },
        border: "var(--border-subtle)",
        ring: "var(--border-focus)",
      },
      fontFamily: {
        display: ["var(--font-display)"],
        sans: ["var(--font-body)"],
        mono: ["var(--font-mono)"],
      },
      minHeight: {
        touch: "var(--min-touch-target)", // 44px touch target (WCAG 2.2 AA)
      },
      minWidth: {
        touch: "var(--min-touch-target)",
      },
      maxWidth: {
        mobile: "var(--max-width-mobile)", // 430px for ui-page mobile patterns
        desktop: "var(--max-width-desktop)",
      },
      borderRadius: {
        pill: "var(--radius-pill)",
        card: "var(--radius-lg)",
      },
    },
  },
  plugins: [],
};

