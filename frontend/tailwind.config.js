/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    // G-4/WCAG 1.4.10 Reflow, fix round 1: Tailwind's default breakpoints are
    // viewport-px media queries, which a larger root font size never crosses
    // -- raising the root to 150% left `md:`/`lg:` switches (the table/card
    // layout, the sidebar drawer, the graph's stacked-vs-row panel) keyed off
    // the same 1280 raw CSS pixels regardless of font size, so content sized
    // in rem/ch kept demanding more room than the (unchanged) breakpoint
    // assumed and escaped as real page-level horizontal scroll. Em-based
    // breakpoints scale with the root font size instead, so they fire at the
    // same *effective* width users actually see. These values are identical
    // to Tailwind's px defaults at the default 16px root (40em = 640px,
    // 48em = 768px, 64em = 1024px, 80em = 1280px), so nothing changes for a
    // default-zoom user.
    screens: {
      sm: "40em",
      md: "48em",
      lg: "64em",
      xl: "80em",
      "2xl": "96em",
    },
    extend: {},
  },
  plugins: [],
};
