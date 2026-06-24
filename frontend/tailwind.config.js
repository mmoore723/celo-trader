/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  darkMode: "class",          // toggle via <html class="dark">
  theme: {
    extend: {
      fontFamily: {
        sans: ["Inter", "system-ui", "sans-serif"],
        mono: ["JetBrains Mono", "Fira Code", "monospace"],
      },
      colors: {
        // Semantic surface tokens — overridden per theme via CSS vars
        surface:  "var(--surface)",
        panel:    "var(--panel)",
        border:   "var(--border)",
        muted:    "var(--muted)",
        accent:   { DEFAULT: "var(--accent)", hover: "var(--accent-hover)" },
        positive: "var(--positive)",
        negative: "var(--negative)",
        warning:  "var(--warning)",
        ink:      "var(--ink)",
        "ink-muted": "var(--ink-muted)",
      },
      boxShadow: {
        card: "var(--shadow-card)",
        panel: "var(--shadow-panel)",
      },
    },
  },
  plugins: [],
};
