/**
 * Type colours: the stored `#rrggbb`, the fallback for a type that has
 * none, and the label foreground that keeps a node readable on either.
 *
 * Nothing here touches the DOM. That is deliberate: the canvas is a
 * `<canvas>` bitmap, so axe sees no text and no colours on it at all --
 * neither an accessibility scan nor a screenshot can tell you whether a
 * label is legible on a fill the user chose. The only thing that can is an
 * assertion on the computed foreground, which is why the choice is a pure
 * function with its own tests rather than a branch inside a stylesheet.
 */

/** Migration 0009's `CHECK (colour ~ '^#[0-9a-f]{6}$')`, restated. The
 * backend normalises case for us, but a value can also come from a text
 * box in this app before it has been anywhere near the server. */
const HEX_RE = /^#[0-9a-fA-F]{6}$/;

/**
 * `#RRGGBB` in either case to the lowercase form the database stores, or
 * `null` for anything else (including `""`, which the colour field uses to
 * mean "no colour"). The three-digit CSS shorthand is not expanded -- the
 * stored form is six digits, and expanding would be guessing.
 */
export function normaliseColour(input: string | null | undefined): string | null {
  if (typeof input !== "string") return null;
  const trimmed = input.trim();
  if (!HEX_RE.test(trimmed)) return null;
  return trimmed.toLowerCase();
}

/** True for anything `normaliseColour` would accept. Used by the editor to
 * tell "empty, i.e. no colour" from "typed something wrong". */
export function isColour(input: string): boolean {
  return normaliseColour(input) !== null;
}

/**
 * The fallback palette, used when a type has no colour of its own.
 *
 * Every entry reaches at least 4.5:1 against whichever of the two label
 * foregrounds is chosen for it (asserted in `colour.test.ts`), so a type
 * nobody has coloured is still readable. They are also distinguishable
 * under the common forms of colour blindness -- adjacent entries never
 * differ only in the red/green channel.
 */
export const FALLBACK_PALETTE = [
  "#1f77b4",
  "#d62728",
  "#2e7d32",
  "#8c564b",
  "#7b3fa0",
  "#b8860b",
  "#0f766e",
  "#c2185b",
  "#4054b2",
  "#a0522d",
] as const;

/**
 * A stable colour for a type that has none.
 *
 * Keyed by the type's **id**, hashed -- never by its position in a list.
 * A palette indexed by array position changes the moment a type is added,
 * deleted, renamed (the lists are ordered by name) or filtered out, so
 * every other type would silently change colour; `colour.test.ts` pins
 * that against reordered and filtered inputs rather than against one
 * list. The hash is FNV-1a, chosen only because it is short, pure and has
 * no platform-dependent behaviour: the same id must give the same colour
 * in a later session and in a different browser.
 */
export function fallbackColour(id: string): string {
  let hash = 0x811c9dc5;
  for (let i = 0; i < id.length; i += 1) {
    hash ^= id.charCodeAt(i);
    // `Math.imul` keeps the multiply in 32-bit space; a plain `*` would
    // lose the low bits to float64 rounding and collapse the spread.
    hash = Math.imul(hash, 0x01000193);
  }
  return FALLBACK_PALETTE[Math.abs(hash) % FALLBACK_PALETTE.length];
}

/** The colour a type is drawn in: its own, or its deterministic fallback. */
export function typeColour(type: { id: string; colour?: string | null }): string {
  return normaliseColour(type.colour) ?? fallbackColour(type.id);
}

// --- contrast --------------------------------------------------------------

/** The two label foregrounds. Near-black and near-white rather than pure
 * ones, so a label sits in the same visual family as the rest of the UI. */
export const LABEL_DARK = "#0f172a";
export const LABEL_LIGHT = "#f8fafc";

function toRgb(hex: string): [number, number, number] {
  const value = normaliseColour(hex);
  // An unparseable fill is treated as black, which gets the light
  // foreground -- the same answer as the canvas's old fixed styling.
  if (value === null) return [0, 0, 0];
  return [
    parseInt(value.slice(1, 3), 16),
    parseInt(value.slice(3, 5), 16),
    parseInt(value.slice(5, 7), 16),
  ];
}

/** WCAG 2.x relative luminance (sRGB), 0 for black and 1 for white. */
export function relativeLuminance(hex: string): number {
  const [r, g, b] = toRgb(hex);
  const linear = [r, g, b].map((raw) => {
    const channel = raw / 255;
    return channel <= 0.03928 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4;
  });
  // The three coefficients are what make this luminance rather than
  // brightness: green carries most of the perceived light, blue almost
  // none. A plain (r+g+b)/3 would call #00ff00 dark and #0000ff light,
  // which is backwards for both.
  return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2];
}

/** WCAG contrast ratio between two colours, 1 (identical) to 21. */
export function contrastRatio(a: string, b: string): number {
  const la = relativeLuminance(a);
  const lb = relativeLuminance(b);
  const lighter = Math.max(la, lb);
  const darker = Math.min(la, lb);
  return (lighter + 0.05) / (darker + 0.05);
}

/**
 * The label colour to draw on `fill`: whichever of the two foregrounds
 * contrasts with it more.
 *
 * Deliberately not a luminance threshold constant. A threshold has to be
 * re-derived whenever either foreground changes, and getting it slightly
 * wrong is invisible -- the label stays *present*, just harder to read.
 * Comparing the two ratios cannot drift out of step with the constants it
 * compares.
 */
export function labelForeground(fill: string): string {
  return contrastRatio(LABEL_DARK, fill) >= contrastRatio(LABEL_LIGHT, fill)
    ? LABEL_DARK
    : LABEL_LIGHT;
}

/** The contrast the chosen foreground actually achieves on `fill`. Exposed
 * so tests can assert a floor over a sweep of fills rather than over the
 * handful anybody thought to list. */
export function labelContrast(fill: string): number {
  return contrastRatio(labelForeground(fill), fill);
}
