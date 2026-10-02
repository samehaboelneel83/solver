import { describe, expect, it } from "vitest";
import { placeLabels, rampColour, type GeoMark } from "./GeoMap";
import { areaFields, colourAreas, type AnswerMap } from "../RunOutputs";

const point = (id: string, x: number, y: number, label: string, size = 5): GeoMark => ({
  id, geometry: { type: "Point", coordinates: [x, y] }, colour: "#000", title: label, label, layer: "l", size,
});
const at = (p: number[]) => p;

describe("names on the map", () => {
  it("draws no name over another, the bigger mark's first", () => {
    const kept = placeLabels([point("a", 0, 0, "Imbaba Youth Centre", 4), point("b", 2, 1, "Warraq Hall", 6), point("c", 0, 200, "Haram")], at);
    expect([...kept].sort()).toEqual(["b", "c"]);
  });

  it("names a place chosen by two decisions once", () => {
    expect(placeLabels([point("open:S1", 10, 10, "Faisal Hall"), point("assign:S1", 10, 10, "Faisal Hall")], at).size).toBe(1);
  });
});

describe("areas coloured by a number", () => {
  const square = (x: number) => ({ type: "Polygon" as const, coordinates: [[[x, 0], [x + 1, 0], [x + 1, 1], [x, 0]]] });
  const map = {
    layers: [{ id: "covered", kind: "places", title: "covered" }],
    features: [
      { geometry: square(0), properties: { layer: "covered", key: "Z1", status: "chosen" as const, title: "Z1", value: 1, data: { population: 100, vulnerability: 5 } } },
      { geometry: square(2), properties: { layer: "covered", key: "Z2", status: "not_chosen" as const, title: "Z2", value: 0, data: { population: 300 } } },
    ],
  } as unknown as AnswerMap;
  const marks: GeoMark[] = map.features.map((f, i) => ({ id: String(i), geometry: f.geometry, colour: "#2563eb", title: f.properties.title, layer: "covered" }));

  it("offers the number fields the areas carry", () => {
    expect(areaFields(map)).toEqual(["population", "vulnerability"]);
  });

  it("fills each area on a scale from the least to the most, a chosen one deeper", () => {
    const { marks: out, ramp } = colourAreas(map, marks, "population");
    expect(ramp).toEqual({ title: "population", min: 100, max: 300 });
    expect(out[0].colour).toBe(rampColour(0));
    expect(out[1].colour).toBe(rampColour(1));
    expect(out[0].fill).toBeGreaterThan(out[1].fill!);
    expect(out[1].title).toContain("population 300");
  });
});
