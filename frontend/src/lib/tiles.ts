/**
 * Tile basemaps for the maps (GIS 9): what a TileJSON index offers, and the
 * Web Mercator arithmetic that puts cells on the imagery.
 *
 * The index is the list a tile server publishes (`/index.json`: one
 * TileJSON per tileset). A tileset with an `encoding` (terrain-RGB) is data,
 * not a picture, and is not offered as a background.
 */

export type Basemap = {
  id: string;
  name: string;
  /** `{z}/{x}/{y}` template. */
  url: string;
  attribution: string;
  minzoom: number;
  maxzoom: number;
};

// Windows-1252's characters for bytes 0x80..0x9F (undefined bytes left out):
// text that was UTF-8, read as 1252 and saved again, shows these.
const CP1252: Record<string, number> = {
  "€": 0x80, "‚": 0x82, "ƒ": 0x83, "„": 0x84, "…": 0x85, "†": 0x86, "‡": 0x87, "ˆ": 0x88, "‰": 0x89, "Š": 0x8a,
  "‹": 0x8b, "Œ": 0x8c, "Ž": 0x8e, "‘": 0x91, "’": 0x92, "“": 0x93, "”": 0x94, "•": 0x95, "–": 0x96, "—": 0x97,
  "˜": 0x98, "™": 0x99, "š": 0x9a, "›": 0x9b, "œ": 0x9c, "ž": 0x9e, "Ÿ": 0x9f,
};

/**
 * Undo text that was UTF-8, decoded as Windows-1252 (or Latin-1) and stored
 * again -- "Â©" for "©", "â€”" for "—". Text that is not such mojibake is
 * returned unchanged: every character must map back to one byte and the
 * bytes must be valid UTF-8, or nothing is touched.
 */
export function repairText(text: string): string {
  if (!/[ÂÃâ]/.test(text)) return text;
  const bytes: number[] = [];
  for (const ch of text) {
    const code = ch.codePointAt(0)!;
    if (code < 0x100) bytes.push(code);
    else if (ch in CP1252) bytes.push(CP1252[ch]);
    else return text;
  }
  try {
    return new TextDecoder("utf-8", { fatal: true }).decode(new Uint8Array(bytes));
  } catch {
    return text;
  }
}

/** The pictures an index offers as backgrounds, names and credits repaired. */
export function basemapsOf(index: unknown): Basemap[] {
  if (!Array.isArray(index)) return [];
  return index
    .filter((t): t is Record<string, unknown> => !!t && typeof t === "object")
    .filter((t) => !t.encoding && Array.isArray(t.tiles) && typeof t.tiles[0] === "string")
    .map((t) => ({
      id: String(t.id ?? t.name ?? (t.tiles as string[])[0]),
      name: repairText(String(t.name ?? t.id ?? "Basemap")),
      url: (t.tiles as string[])[0],
      attribution: repairText(String(t.attribution ?? "")),
      minzoom: Number.isFinite(Number(t.minzoom)) ? Number(t.minzoom) : 0,
      maxzoom: Number.isFinite(Number(t.maxzoom)) ? Number(t.maxzoom) : 18,
    }));
}

const TILE = 256;

/** Web Mercator world pixels at zoom `z`. */
export function mercator(lon: number, lat: number, z: number): [number, number] {
  const size = TILE * 2 ** z;
  const clamped = Math.max(-85.05112878, Math.min(85.05112878, lat));
  const s = Math.sin((clamped * Math.PI) / 180);
  return [((lon + 180) / 360) * size, (0.5 - Math.log((1 + s) / (1 - s)) / (4 * Math.PI)) * size];
}

export type View = {
  zoom: number;
  /** Screen pixels per world pixel at `zoom` (fits the box exactly). */
  scale: number;
  /** Lon/lat to screen. */
  project: (lon: number, lat: number) => [number, number];
  /** The tiles covering the view, where each is drawn. */
  tiles: { x: number; y: number; z: number; left: number; top: number; size: number }[];
};

/**
 * The view that fits a lon/lat box in `width` x `height`, centred, with the
 * tiles to draw under it: the deepest zoom the basemap has (within its
 * range) at which the box still fits, then scaled to fill.
 */
export function fitView(
  box: { west: number; south: number; east: number; north: number },
  width: number,
  height: number,
  range: { minzoom: number; maxzoom: number } = { minzoom: 0, maxzoom: 18 }
): View {
  let zoom = range.minzoom;
  for (let z = range.maxzoom; z >= range.minzoom; z -= 1) {
    const [x0, y1] = mercator(box.west, box.south, z);
    const [x1, y0] = mercator(box.east, box.north, z);
    if (x1 - x0 <= width && y1 - y0 <= height) {
      zoom = z;
      break;
    }
  }
  const [x0, y1] = mercator(box.west, box.south, zoom);
  const [x1, y0] = mercator(box.east, box.north, zoom);
  const scale = Math.min(width / Math.max(x1 - x0, 1e-9), height / Math.max(y1 - y0, 1e-9));
  // Centre the box: the screen's origin in world pixels.
  const originX = (x0 + x1) / 2 - width / 2 / scale;
  const originY = (y0 + y1) / 2 - height / 2 / scale;
  const project = (lon: number, lat: number): [number, number] => {
    const [x, y] = mercator(lon, lat, zoom);
    return [(x - originX) * scale, (y - originY) * scale];
  };
  const tiles: View["tiles"] = [];
  const count = 2 ** zoom;
  const first = [Math.floor(originX / TILE), Math.floor(originY / TILE)];
  const last = [Math.floor((originX + width / scale) / TILE), Math.floor((originY + height / scale) / TILE)];
  for (let ty = Math.max(0, first[1]); ty <= Math.min(count - 1, last[1]); ty += 1) {
    for (let tx = first[0]; tx <= last[0]; tx += 1) {
      tiles.push({
        x: ((tx % count) + count) % count,
        y: ty,
        z: zoom,
        left: (tx * TILE - originX) * scale,
        top: (ty * TILE - originY) * scale,
        size: TILE * scale,
      });
    }
  }
  return { zoom, scale, project, tiles };
}

export function tileUrl(template: string, tile: { x: number; y: number; z: number }): string {
  return template.replace("{z}", String(tile.z)).replace("{x}", String(tile.x)).replace("{y}", String(tile.y));
}
