import { describe, expect, it } from "vitest";
import {
  FALLBACK_PALETTE,
  LABEL_DARK,
  LABEL_LIGHT,
  contrastRatio,
  fallbackColour,
  isColour,
  labelContrast,
  labelForeground,
  normaliseColour,
  relativeLuminance,
  typeColour,
} from "./colour";

/**
 * The two things on this page that neither axe nor a screenshot can check.
 *
 * The canvas is a `<canvas>` bitmap: axe finds no text on it, so a label
 * drawn in white on white would pass every accessibility scan this project
 * runs and be invisible to a human. And a fallback colour that is wrong
 * only *later* -- because it was derived from a list position and the list
 * changed -- looks perfectly correct in any single screenshot.
 *
 * So both get real assertions here: a sweep rather than a handful of
 * fills, and reordered/filtered inputs rather than one list.
 */

/** Every colour with each channel in {0, 51, ..., 255} -- 216 fills,
 * including both extremes, the greys and the fully saturated corners. */
function sweep(): string[] {
  const steps = [0, 51, 102, 153, 204, 255];
  const out: string[] = [];
  for (const r of steps) {
    for (const g of steps) {
      for (const b of steps) {
        out.push(`#${[r, g, b].map((v) => v.toString(16).padStart(2, "0")).join("")}`);
      }
    }
  }
  return out;
}

describe("normaliseColour", () => {
  it("accepts either case and returns the lowercase form the database stores", () => {
    expect(normaliseColour("#AABBCC")).toBe("#aabbcc");
    expect(normaliseColour("#AaBbCc")).toBe("#aabbcc");
    expect(normaliseColour("#1f77b4")).toBe("#1f77b4");
    expect(normaliseColour("  #FF8800  ")).toBe("#ff8800");
  });

  it("rejects everything the server's CHECK rejects", () => {
    // The three-digit shorthand is deliberately NOT expanded: the stored
    // form is six digits and expanding would be guessing.
    for (const bad of ["#abc", "aabbcc", "#gggggg", "#aabbccdd", "#aabbc", "", "red", "rgb(1,2,3)"]) {
      expect(normaliseColour(bad), bad).toBeNull();
    }
    expect(normaliseColour(null)).toBeNull();
    expect(normaliseColour(undefined)).toBeNull();
  });

  it("isColour agrees with it", () => {
    expect(isColour("#AABBCC")).toBe(true);
    expect(isColour("#abc")).toBe(false);
  });
});

describe("relativeLuminance", () => {
  it("is 0 for black and 1 for white", () => {
    expect(relativeLuminance("#000000")).toBeCloseTo(0, 6);
    expect(relativeLuminance("#ffffff")).toBeCloseTo(1, 6);
  });

  it("weights the channels by perceived light, not equally", () => {
    // The whole point of luminance over brightness. Under a plain
    // (r+g+b)/3 these three would be identical; they are nowhere near.
    expect(relativeLuminance("#00ff00")).toBeCloseTo(0.7152, 4);
    expect(relativeLuminance("#ff0000")).toBeCloseTo(0.2126, 4);
    expect(relativeLuminance("#0000ff")).toBeCloseTo(0.0722, 4);
  });
});

describe("contrastRatio", () => {
  it("is 21 for black on white and 1 for a colour on itself", () => {
    expect(contrastRatio("#000000", "#ffffff")).toBeCloseTo(21, 4);
    expect(contrastRatio("#1f77b4", "#1f77b4")).toBeCloseTo(1, 6);
  });

  it("is symmetric", () => {
    expect(contrastRatio("#1f77b4", "#ffffff")).toBeCloseTo(
      contrastRatio("#ffffff", "#1f77b4"),
      10
    );
  });
});

describe("labelForeground", () => {
  it("picks the dark label on a white fill and the light label on a black one", () => {
    expect(labelForeground("#ffffff")).toBe(LABEL_DARK);
    expect(labelForeground("#000000")).toBe(LABEL_LIGHT);
  });

  it("switches between two adjacent mid greys, either side of the crossover", () => {
    // #808080 and #6b6b6b are 21 steps apart and look almost alike, but
    // their luminances straddle the point where the two foregrounds swap.
    // A rule with a threshold that is merely close would get one of these
    // wrong; a rule that always answers the same thing gets one wrong too.
    expect(labelForeground("#808080")).toBe(LABEL_DARK);
    expect(labelForeground("#6b6b6b")).toBe(LABEL_LIGHT);
  });

  it("answers by luminance, not by average brightness", () => {
    // All three have the same channel average (85). Under (r+g+b)/3 they
    // would get the same label; under luminance green is light and the
    // other two are dark.
    expect(labelForeground("#00ff00")).toBe(LABEL_DARK);
    expect(labelForeground("#0000ff")).toBe(LABEL_LIGHT);
    expect(labelForeground("#ff0000")).toBe(LABEL_DARK);
  });

  it("is the better of the two foregrounds for every fill in a 216-colour sweep", () => {
    for (const fill of sweep()) {
      const chosen = labelForeground(fill);
      const other = chosen === LABEL_DARK ? LABEL_LIGHT : LABEL_DARK;
      expect(contrastRatio(chosen, fill), fill).toBeGreaterThanOrEqual(
        contrastRatio(other, fill)
      );
    }
  });

  it("never drops below 4.1:1 on any fill a user could choose", () => {
    // 4.131 is the true worst case for this pair of foregrounds (a mid
    // purple around #876cb7). It is below WCAG's 4.5 for small text, which
    // is why the only place this appears as DOM text -- the colour
    // preview -- is large bold text, whose threshold is 3:1.
    let worst = Infinity;
    let worstFill = "";
    for (const fill of sweep()) {
      const ratio = labelContrast(fill);
      if (ratio < worst) {
        worst = ratio;
        worstFill = fill;
      }
    }
    expect(worst, `worst fill ${worstFill}`).toBeGreaterThanOrEqual(4.1);
  });

  it("clears 4.5:1 on every colour in the fallback palette", () => {
    for (const fill of FALLBACK_PALETTE) {
      expect(labelContrast(fill), fill).toBeGreaterThanOrEqual(4.5);
    }
  });

  it("the palette exercises both foregrounds", () => {
    // Without this, a mutant that always answers LABEL_LIGHT would survive
    // every palette assertion above.
    const chosen = FALLBACK_PALETTE.map(labelForeground);
    expect(chosen).toContain(LABEL_DARK);
    expect(chosen).toContain(LABEL_LIGHT);
  });

  it("treats an unparseable fill as black rather than throwing", () => {
    expect(labelForeground("not a colour")).toBe(LABEL_LIGHT);
  });
});

describe("fallbackColour", () => {
  it("always returns a palette colour", () => {
    for (let id = 1; id <= 200; id += 1) {
      expect(FALLBACK_PALETTE).toContain(fallbackColour(String(id)));
    }
  });

  it("is stable for the same id", () => {
    expect(fallbackColour("17")).toBe(fallbackColour("17"));
    expect(fallbackColour("17")).not.toBe(fallbackColour("17 "));
  });

  it("spreads ids across the palette", () => {
    // A hash that collapsed (every id to palette[0], or the low bits lost
    // to float rounding) would still pass every other test here.
    const used = new Set(Array.from({ length: 40 }, (_, i) => fallbackColour(String(i + 1))));
    expect(used.size).toBeGreaterThanOrEqual(5);
  });

  it("does not depend on a list's order", () => {
    const ids = ["3", "7", "11", "2", "19", "104"];
    const forward = Object.fromEntries(ids.map((id) => [id, fallbackColour(id)]));
    const reversed = Object.fromEntries([...ids].reverse().map((id) => [id, fallbackColour(id)]));
    expect(reversed).toEqual(forward);
  });

  it("does not change when a type is added, deleted or filtered out", () => {
    // The failure this exists to prevent: a palette indexed by array
    // position gives every OTHER type a new colour the moment one type is
    // added or removed, silently, with nothing on screen to explain it.
    const ids = ["3", "7", "11", "2", "19", "104"];
    const before = Object.fromEntries(ids.map((id) => [id, fallbackColour(id)]));

    const afterDelete = ids.filter((id) => id !== "3");
    for (const id of afterDelete) {
      expect(fallbackColour(id), `${id} after deleting 3`).toBe(before[id]);
    }

    const afterInsert = ["1", ...ids, "500"];
    for (const id of ids) {
      expect(fallbackColour(id), `${id} after inserting around it`).toBe(before[id]);
    }
    expect(afterInsert).toHaveLength(ids.length + 2);

    // ... and the same through `typeColour`, which is what the graph calls.
    const filtered = ids.slice(2, 4).map((id) => typeColour({ id, colour: null }));
    expect(filtered).toEqual([before["11"], before["2"]]);
  });
});

describe("typeColour", () => {
  it("prefers the type's own colour and normalises it", () => {
    expect(typeColour({ id: "3", colour: "#FF8800" })).toBe("#ff8800");
  });

  it("falls back for null, and for a stored value that is somehow malformed", () => {
    expect(typeColour({ id: "3", colour: null })).toBe(fallbackColour("3"));
    expect(typeColour({ id: "3" })).toBe(fallbackColour("3"));
    expect(typeColour({ id: "3", colour: "nonsense" })).toBe(fallbackColour("3"));
  });

  it("keys the fallback on the id, not on anything renameable", () => {
    expect(typeColour({ id: "42", colour: null })).toBe(typeColour({ id: "42", colour: null }));
    expect(typeColour({ id: "42", colour: null })).not.toBe(
      // A different id must be free to differ; with only 10 palette entries
      // some pairs collide, so this picks one that does not.
      typeColour({ id: "43", colour: null })
    );
  });
});
