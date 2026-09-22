import { describe, expect, it } from "vitest";
import { contrastRatio, LABEL_DARK } from "./colour";
import {
  captionColour,
  defaultIconKey,
  GENERIC_ICON,
  humaniseTypeName,
  ICONS,
  iconSrc,
  nodeImage,
  resolveIcon,
  uploadProblem,
} from "./entityIcons";

const PNG = "data:image/png;base64,iVBORw0KGgo=";

describe("defaultIconKey", () => {
  it.each([
    ["hotel", "hotel"],
    ["bus_stop", "bus_stop"],
    ["city", "city"],
    ["restaurant", "restaurant"],
    ["cable_car", "cable_car"], // the first word wins: not a car
    ["ski_slope", "mountain"],
    ["province", "province"],
    ["employees", "person"], // plural
    ["night_shift", "calendar"],
    ["depot", "warehouse"],
  ])("%s -> %s", (name, key) => {
    expect(defaultIconKey(name)).toBe(key);
  });

  it("falls back to the role when no word matches", () => {
    expect(defaultIconKey("widget_x", "agent")).toBe("person");
    expect(defaultIconKey("widget_x", "location")).toBe("pin");
    expect(defaultIconKey("widget_x", "time")).toBe("clock");
  });

  it("falls back to the generic disc for role other", () => {
    expect(defaultIconKey("widget_x", "other")).toBe(GENERIC_ICON);
    expect(defaultIconKey("widget_x")).toBe(GENERIC_ICON);
  });

  it("does not turn 'bus' into 'bu' by stripping the s", () => {
    expect(defaultIconKey("bus")).toBe("bus_stop");
  });

  it("only ever names a key that exists in the gallery", () => {
    for (const name of ["hotel", "nurse", "gondola", "store", "course", "invoice"]) {
      expect(ICONS[defaultIconKey(name)]).toBeDefined();
    }
  });
});

describe("resolveIcon", () => {
  it("uses a chosen gallery key over the default", () => {
    expect(resolveIcon({ name: "hotel", icon: "restaurant" })).toBe("restaurant");
  });
  it("uses an upload as is", () => {
    expect(resolveIcon({ name: "hotel", icon: PNG })).toBe(PNG);
  });
  it("treats null, and a key this build does not know, as the default", () => {
    expect(resolveIcon({ name: "hotel", icon: null })).toBe("hotel");
    expect(resolveIcon({ name: "hotel", icon: "no_such_icon" })).toBe("hotel");
  });
});

describe("nodeImage", () => {
  it("is one SVG with the icon and the humanised type name", () => {
    const drawn = nodeImage({ name: "bus_stop", colour: "#1f77b4", icon: null });
    expect(drawn.image.startsWith("data:image/svg+xml")).toBe(true);
    const svg = decodeURIComponent(drawn.image.split(",")[1]);
    expect(svg).toContain(">Bus stop</text>");
    expect(svg).toContain(ICONS.bus_stop.svg);
  });

  it("embeds an upload as an <image>", () => {
    const svg = decodeURIComponent(nodeImage({ name: "hotel", colour: "#1f77b4", icon: PNG }).image.split(",")[1]);
    expect(svg).toContain(`<image href="${PNG}"`);
  });

  it("widens for a long type name and never shrinks below the icon", () => {
    const short = nodeImage({ name: "a", colour: "#1f77b4" });
    const long = nodeImage({ name: "a_very_long_entity_type_name", colour: "#1f77b4" });
    expect(short.w).toBeGreaterThanOrEqual(56);
    expect(long.w).toBeGreaterThan(short.w);
  });

  it("escapes the caption", () => {
    const svg = decodeURIComponent(nodeImage({ name: "a<b", colour: "#1f77b4" }).image.split(",")[1]);
    expect(svg).not.toContain("a<b");
  });

  it("is cached per type, so a big graph builds each image once", () => {
    const type = { name: "hotel", colour: "#2e7d32", icon: "hotel" };
    expect(nodeImage(type)).toBe(nodeImage({ ...type }));
  });

  it("draws the generic disc in the type's own colour", () => {
    expect(decodeURIComponent(iconSrc(GENERIC_ICON, "#c2185b"))).toContain('fill="#c2185b"');
  });
});

describe("captionColour", () => {
  it("keeps a colour that reads on white and replaces one that does not", () => {
    expect(captionColour("#1f77b4")).toBe("#1f77b4");
    expect(captionColour("#fde68a")).toBe(LABEL_DARK);
  });
  it("always reaches 4.5:1 on white", () => {
    for (const colour of ["#ffffff", "#facc15", "#22c55e", "#0f172a", "#b8860b"]) {
      expect(contrastRatio(captionColour(colour), "#ffffff")).toBeGreaterThanOrEqual(4.5);
    }
  });
});

describe("humaniseTypeName", () => {
  it("reads as prose", () => {
    expect(humaniseTypeName("bus_stop")).toBe("Bus stop");
    expect(humaniseTypeName("hotel")).toBe("Hotel");
  });
});

describe("uploadProblem", () => {
  it("accepts a small PNG", () => {
    expect(uploadProblem({ type: "image/png", size: 1000 })).toBeNull();
  });
  it("refuses other types and big files", () => {
    expect(uploadProblem({ type: "image/gif", size: 10 })).toMatch(/PNG, SVG or WebP/);
    expect(uploadProblem({ type: "image/png", size: 300 * 1024 })).toMatch(/200 KB/);
  });
  it("refuses an SVG with script, like the server does", () => {
    expect(uploadProblem({ type: "image/svg+xml", size: 50 }, "<svg><script>x</script></svg>")).toMatch(/script/);
    expect(uploadProblem({ type: "image/svg+xml", size: 50 }, '<svg xmlns="http://www.w3.org/2000/svg"><rect/></svg>')).toBeNull();
  });
});
