import { describe, expect, it } from "vitest";
import { basemapsOf, fitView, mercator, repairText, tileUrl } from "./tiles";

/** The user's tile server index (2026-09-24), trimmed; its text as the server sends it. */
const INDEX = [
  { tiles: ["http://localhost:8080/data/egypt_topo/{z}/{x}/{y}.jpg"], name: "Egypt Topo (hillshade + contours)", id: "egypt_topo", minzoom: 1, maxzoom: 12, attribution: "Copernicus DEM GLO-30 (ESA)" },
  { tiles: ["http://localhost:8080/data/egypt_satellite/{z}/{x}/{y}.jpg"], name: "Egypt Satellite Imagery", id: "egypt_satellite", minzoom: 1, maxzoom: 11,
    description: "Esri World Imagery â€“ Egypt, Z1-Z11",
    attribution: "Tiles Â© Esri â€” Source: Esri, Earthstar Geographics, and the GIS User Community" },
  { tiles: ["http://localhost:8080/data/egypt_terrain/{z}/{x}/{y}.png"], name: "Egypt Terrain RGB", id: "egypt_terrain", encoding: "mapbox", minzoom: 0, maxzoom: 12 },
  // Added to the server later the same day: vector tiles, not a picture.
  { tiles: ["http://localhost:8080/data/egypt_osm/{z}/{x}/{y}.pbf"], name: "OSM Egypt (OpenMapTiles)", id: "egypt_osm", format: "pbf", minzoom: 0, maxzoom: 12 },
];

describe("the tile index", () => {
  it("offers the pictures as backgrounds and leaves terrain data and vector tiles out", () => {
    expect(basemapsOf(INDEX).map((b) => b.id)).toEqual(["egypt_topo", "egypt_satellite"]);
    // With no `format`, the tile address's extension says what it is.
    expect(basemapsOf([{ tiles: ["http://t/{z}/{x}/{y}.png?key=1"], id: "a" }, { tiles: ["http://t/{z}/{x}/{y}.mvt"], id: "b" }]).map((b) => b.id)).toEqual(["a"]);
    expect(basemapsOf({ not: "a list" })).toEqual([]);
  });

  it("shows the Esri credit as it was written, not as the server mangled it", () => {
    expect(basemapsOf(INDEX)[1].attribution).toBe("Tiles © Esri — Source: Esri, Earthstar Geographics, and the GIS User Community");
    expect(repairText("Esri World Imagery â€“ Egypt")).toBe("Esri World Imagery – Egypt");
  });

  it("leaves text alone that is not mangled, even with the same letters", () => {
    for (const text of ["Copernicus DEM GLO-30 (ESA)", "Âge", "â la carte", "Café — 5 €"]) expect(repairText(text)).toBe(text);
  });
});

describe("Web Mercator", () => {
  it("puts the equator and the prime meridian at the middle of the world", () => {
    expect(mercator(0, 0, 0)).toEqual([128, 128]);
    const [x, y] = mercator(31.25, 30.05, 10);
    expect(Math.floor(x / 256)).toBe(600);
    // The slippy-map formula by hand: floor((1 - asinh(tan 30.05°)/π) / 2 * 1024) = floor(0.41253 * 1024) = 422.
    expect(Math.floor(y / 256)).toBe(422);
  });

  it("fits a box inside the frame, centred, north up, with tiles covering it", () => {
    const box = { west: 31.2, south: 30.0, east: 31.304, north: 30.072 };
    const view = fitView(box, 640, 420, { minzoom: 1, maxzoom: 11 });
    const [x0, y0] = view.project(box.west, box.north);
    const [x1, y1] = view.project(box.east, box.south);
    for (const v of [x0, x1]) {
      expect(v).toBeGreaterThanOrEqual(-1e-6);
      expect(v).toBeLessThanOrEqual(640 + 1e-6);
    }
    for (const v of [y0, y1]) {
      expect(v).toBeGreaterThanOrEqual(-1e-6);
      expect(v).toBeLessThanOrEqual(420 + 1e-6);
    }
    expect(y0).toBeLessThan(y1); // north is up
    expect(Math.abs((x0 + x1) / 2 - 320)).toBeLessThan(1e-6);
    expect(view.zoom).toBeLessThanOrEqual(11);
    // Every screen pixel has a tile under it.
    const covers = (px: number, py: number) => view.tiles.some((t) => px >= t.left && px < t.left + t.size && py >= t.top && py < t.top + t.size);
    for (const [px, py] of [[0, 0], [639, 0], [0, 419], [639, 419], [320, 210]]) expect(covers(px, py), `${px},${py}`).toBe(true);
    expect(tileUrl(INDEX[1].tiles[0], view.tiles[0])).toMatch(/^http:\/\/localhost:8080\/data\/egypt_satellite\/\d+\/\d+\/\d+\.jpg$/);
  });

  it("goes no deeper than the basemap has tiles for", () => {
    const tiny = { west: 31.2, south: 30.0, east: 31.2001, north: 30.0001 };
    expect(fitView(tiny, 640, 420, { minzoom: 1, maxzoom: 11 }).zoom).toBe(11);
  });
});
