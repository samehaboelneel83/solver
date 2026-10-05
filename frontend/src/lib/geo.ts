/**
 * Positions on the map for a site drawn in local metres (x east, y north) around an origin longitude and
 * latitude: a record's location, an imported drawing, a run's answer.
 *
 * Local metres to the map: metres per degree on the WGS84 ellipsoid at the origin's latitude. Over a site
 * (hundreds of metres) this agrees with an azimuthal equidistant projection to well under a centimetre.
 */
export type Pt = [number, number];
export type Ring = Pt[];

const RAD = Math.PI / 180;

/** Metres in one degree of latitude and of longitude at `lat`. */
export function metresPerDegree(lat: number): [number, number] {
  const φ = lat * RAD;
  const perLat = 111132.92 - 559.82 * Math.cos(2 * φ) + 1.175 * Math.cos(4 * φ) - 0.0023 * Math.cos(6 * φ);
  const perLon = 111412.84 * Math.cos(φ) - 93.5 * Math.cos(3 * φ) + 0.118 * Math.cos(5 * φ);
  return [perLat, perLon];
}

/** Local metres to longitude and latitude. `bearing`: how far the local +y axis is turned clockwise from north. */
export function toLonLat(p: Pt, origin: Pt, bearing = 0): Pt {
  const [perLat, perLon] = metresPerDegree(origin[1]);
  const c = Math.cos(bearing * RAD), s = Math.sin(bearing * RAD);
  const east = p[0] * c + p[1] * s, north = -p[0] * s + p[1] * c;
  return [origin[0] + east / perLon, origin[1] + north / perLat];
}

export function toLocal(lonlat: Pt, origin: Pt, bearing = 0): Pt {
  const [perLat, perLon] = metresPerDegree(origin[1]);
  const east = (lonlat[0] - origin[0]) * perLon, north = (lonlat[1] - origin[1]) * perLat;
  const c = Math.cos(bearing * RAD), s = Math.sin(bearing * RAD);
  return [east * c - north * s, east * s + north * c];
}

/** Whether `p` is inside the polygon `ring` (even-odd rule). */
export function inside(p: Pt, ring: Ring): boolean {
  let hit = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i, i += 1) {
    const [xi, yi] = ring[i];
    const [xj, yj] = ring[j];
    if (yi > p[1] !== yj > p[1] && p[0] < ((xj - xi) * (p[1] - yi)) / (yj - yi) + xi) hit = !hit;
  }
  return hit;
}

/** "30.1, 31.6" or "31.6 30.1"-style text as a longitude-latitude pair, or null. Latitude first is the
 * common way to write it (and what a map app copies), so two numbers are read lat, lon. */
export function parseLatLon(text: string): Pt | null {
  const nums = text.match(/-?\d+(?:\.\d+)?/g);
  if (!nums || nums.length !== 2) return null;
  const [lat, lon] = nums.map(Number);
  if (Math.abs(lat) > 90 || Math.abs(lon) > 180) return null;
  return [lon, lat];
}
