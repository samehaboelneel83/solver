/**
 * Entity type pictures for the Graph View (migration 0033).
 *
 * `entity_type.icon` is a gallery key from `ICONS`, an uploaded image's
 * `data:` URI, or null. Null -- and a key this build does not know -- means
 * "the default": chosen from the type's name first (`bus_stop` looks like a
 * bus stop), then from its role (an `agent` is a person), and finally a plain
 * disc in the type's colour, which is what the canvas drew before pictures.
 * The default is computed here rather than stored so a type keeps following
 * its name until somebody picks a picture deliberately.
 *
 * Nothing here touches the DOM, for the same reason as `lib/colour.ts`:
 * everything cytoscape paints is inside a `<canvas>`, so the pure functions
 * are the last point a test can observe.
 */
import { contrastRatio, LABEL_DARK, normaliseColour } from "./colour";

export type IconDef = { label: string; svg: string };

/** The bundled gallery. Each `svg` is the inside of a `viewBox="0 0 64 64"`
 * drawing; `iconSvg` wraps it. Drawn for this app, so there is no licence
 * to carry. */
export const ICONS: Record<string, IconDef> = {
  hotel: {
    label: "Hotel",
    svg: '<rect x="8" y="8" width="48" height="6" rx="2" fill="#f59e0b"/><rect x="11" y="14" width="42" height="44" fill="#fcd34d"/><rect x="14" y="18" width="6" height="30" rx="1" fill="#f97316"/><g fill="#bfdbfe"><rect x="25" y="19" width="7" height="7"/><rect x="37" y="19" width="7" height="7"/><rect x="25" y="31" width="7" height="7"/><rect x="37" y="31" width="7" height="7"/></g><path d="M28 58V48a5 5 0 0 1 10 0v10z" fill="#92400e"/>',
  },
  bus_stop: {
    label: "Bus stop",
    svg: '<rect x="6" y="10" width="52" height="7" rx="2" fill="#475569"/><rect x="9" y="17" width="3" height="41" fill="#64748b"/><rect x="52" y="17" width="3" height="41" fill="#64748b"/><rect x="13" y="19" width="38" height="24" fill="#bae6fd"/><rect x="18" y="47" width="28" height="4" rx="1" fill="#b45309"/><rect x="20" y="22" width="24" height="16" rx="3" fill="#facc15"/><rect x="23" y="25" width="18" height="6" fill="#1e293b"/>',
  },
  city: {
    label: "City",
    svg: '<rect x="4" y="28" width="18" height="30" fill="#94a3b8"/><rect x="22" y="8" width="20" height="50" fill="#60a5fa"/><rect x="42" y="22" width="18" height="36" fill="#34d399"/><path d="M8 34h10M8 40h10M8 46h10M26 14h12M26 20h12M26 26h12M26 32h12M26 38h12M26 44h12M46 28h10M46 34h10M46 40h10M46 46h10" stroke="#f1f5f9" stroke-width="2.5"/>',
  },
  restaurant: {
    label: "Restaurant",
    svg: '<circle cx="32" cy="32" r="27" fill="#fef3c7"/><circle cx="32" cy="34" r="15" fill="#fff" stroke="#fcd34d" stroke-width="2"/><path d="M17 12v14a4 4 0 0 0 8 0V12M21 12v12M21 30v22M47 12c-6 4-6 16 0 20v20" stroke="#334155" stroke-width="3" fill="none" stroke-linecap="round"/>',
  },
  cable_car: {
    label: "Cable car",
    svg: '<path d="M2 14L62 4" stroke="#334155" stroke-width="2.5"/><path d="M32 9v11" stroke="#334155" stroke-width="2.5"/><rect x="15" y="20" width="34" height="32" rx="6" fill="#0e7490"/><rect x="19" y="25" width="11" height="11" rx="1" fill="#cffafe"/><rect x="34" y="25" width="11" height="11" rx="1" fill="#cffafe"/><rect x="15" y="43" width="34" height="4" fill="#155e75"/>',
  },
  mountain: {
    label: "Mountain / ski slope",
    svg: '<path d="M2 56L24 16l11 18 8-10 19 32z" fill="#4ade80"/><path d="M24 16L2 56h20l12-20z" fill="#16a34a"/><path d="M24 16l-6 11 6-3 5 4zM43 24l-4 6 4-2 3 3z" fill="#fff"/>',
  },
  province: {
    label: "Province / region",
    svg: '<path d="M6 14l16-6 20 6 16-6v42l-16 6-20-6-16 6z" fill="#86efac"/><path d="M22 8v42M42 14v42" stroke="#16a34a" stroke-width="2"/><path d="M32 16a8 8 0 0 0-8 8c0 7 8 15 8 15s8-8 8-15a8 8 0 0 0-8-8z" fill="#dc2626"/><circle cx="32" cy="24" r="3" fill="#fff"/>',
  },
  pin: {
    label: "Location",
    svg: '<path d="M32 4a19 19 0 0 0-19 19c0 15 19 37 19 37s19-22 19-37A19 19 0 0 0 32 4z" fill="#ef4444"/><circle cx="32" cy="23" r="8" fill="#fff"/>',
  },
  person: {
    label: "Person",
    svg: '<circle cx="32" cy="20" r="12" fill="#fdba74"/><path d="M9 60c0-14 10-22 23-22s23 8 23 22z" fill="#3b82f6"/>',
  },
  team: {
    label: "Team",
    svg: '<circle cx="21" cy="19" r="9" fill="#fcd34d"/><path d="M3 52c0-11 8-17 18-17s18 6 18 17z" fill="#10b981"/><circle cx="43" cy="24" r="10" fill="#fdba74"/><path d="M23 60c0-12 9-19 20-19s20 7 20 19z" fill="#3b82f6"/>',
  },
  building: {
    label: "Organisation",
    svg: '<path d="M6 22L32 7l26 15z" fill="#64748b"/><rect x="9" y="22" width="46" height="5" fill="#94a3b8"/><g fill="#cbd5e1"><rect x="13" y="29" width="6" height="22"/><rect x="24" y="29" width="6" height="22"/><rect x="34" y="29" width="6" height="22"/><rect x="45" y="29" width="6" height="22"/></g><rect x="6" y="51" width="52" height="7" fill="#64748b"/>',
  },
  factory: {
    label: "Factory",
    svg: '<circle cx="51" cy="8" r="4" fill="#cbd5e1"/><path d="M4 58V30l14 8v-8l14 8v-8l14 8V14h10v44z" fill="#f97316"/><g fill="#fde68a"><rect x="10" y="44" width="8" height="8"/><rect x="26" y="44" width="8" height="8"/><rect x="42" y="44" width="8" height="8"/></g>',
  },
  machine: {
    label: "Machine",
    svg: '<circle cx="32" cy="32" r="21" fill="none" stroke="#64748b" stroke-width="10" stroke-dasharray="8.2 8.3"/><circle cx="32" cy="32" r="18" fill="#94a3b8"/><circle cx="32" cy="32" r="7" fill="#e2e8f0"/>',
  },
  tool: {
    label: "Tool",
    svg: '<path d="M43 5a15 15 0 0 0-14 20L8 46a5 5 0 0 0 0 7l3 3a5 5 0 0 0 7 0l21-21a15 15 0 0 0 20-14l-9 4-7-7 4-9a15 15 0 0 0-4-4z" fill="#64748b"/>',
  },
  truck: {
    label: "Vehicle",
    svg: '<rect x="3" y="16" width="37" height="28" rx="2" fill="#ef4444"/><path d="M40 24h11l9 11v9H40z" fill="#f87171"/><rect x="44" y="28" width="7" height="6" fill="#dbeafe"/><circle cx="15" cy="48" r="6" fill="#1e293b"/><circle cx="49" cy="48" r="6" fill="#1e293b"/><circle cx="15" cy="48" r="2.5" fill="#cbd5e1"/><circle cx="49" cy="48" r="2.5" fill="#cbd5e1"/>',
  },
  car: {
    label: "Car",
    svg: '<path d="M6 42l7-15h38l7 15v10H6z" fill="#3b82f6"/><path d="M18 30h28l4 10H14z" fill="#dbeafe"/><circle cx="18" cy="52" r="6" fill="#1e293b"/><circle cx="46" cy="52" r="6" fill="#1e293b"/>',
  },
  train: {
    label: "Train / station",
    svg: '<rect x="14" y="4" width="36" height="46" rx="8" fill="#8b5cf6"/><rect x="19" y="10" width="26" height="15" rx="2" fill="#ede9fe"/><circle cx="23" cy="38" r="3.5" fill="#fef08a"/><circle cx="41" cy="38" r="3.5" fill="#fef08a"/><path d="M20 50l-6 9M44 50l6 9" stroke="#475569" stroke-width="3.5"/>',
  },
  plane: {
    label: "Airport",
    svg: '<path d="M32 4c3 0 5 3 5 7v14l21 12v6l-21-6v12l7 5v5l-12-3-12 3v-5l7-5V37L6 43v-6l21-12V11c0-4 2-7 5-7z" fill="#0ea5e9"/>',
  },
  warehouse: {
    label: "Warehouse / depot",
    svg: '<path d="M3 26L32 9l29 17v32H3z" fill="#a16207"/><rect x="13" y="32" width="38" height="26" fill="#fde68a"/><path d="M13 38h38M13 44h38M13 50h38" stroke="#ca8a04" stroke-width="2"/>',
  },
  box: {
    label: "Product / resource",
    svg: '<path d="M32 5l25 12v30L32 59 7 47V17z" fill="#d97706"/><path d="M32 29L7 17 32 5l25 12z" fill="#fbbf24"/><path d="M32 29v30" stroke="#92400e" stroke-width="2"/><path d="M19 11l25 12" stroke="#b45309" stroke-width="4"/>',
  },
  shop: {
    label: "Shop",
    svg: '<rect x="10" y="26" width="44" height="32" fill="#f1f5f9" stroke="#cbd5e1"/><path d="M6 12h52l-3 16H9z" fill="#ef4444"/><path d="M17 12l-2 16M27 12l-1 16M37 12l1 16M47 12l2 16" stroke="#fff" stroke-width="4"/><rect x="36" y="36" width="12" height="22" fill="#0ea5e9"/><rect x="15" y="36" width="15" height="12" fill="#bae6fd"/>',
  },
  hospital: {
    label: "Hospital",
    svg: '<rect x="7" y="16" width="50" height="42" rx="3" fill="#e2e8f0"/><rect x="22" y="4" width="20" height="20" rx="3" fill="#ef4444"/><path d="M32 8v12M26 14h12" stroke="#fff" stroke-width="4"/><g fill="#93c5fd"><rect x="13" y="30" width="8" height="8"/><rect x="43" y="30" width="8" height="8"/><rect x="13" y="44" width="8" height="8"/><rect x="43" y="44" width="8" height="8"/></g><rect x="27" y="42" width="10" height="16" fill="#64748b"/>',
  },
  school: {
    label: "School",
    svg: '<path d="M4 26L32 9l28 17z" fill="#dc2626"/><rect x="10" y="26" width="44" height="32" fill="#fde68a"/><rect x="27" y="42" width="10" height="16" fill="#92400e"/><rect x="15" y="32" width="8" height="8" fill="#bfdbfe"/><rect x="41" y="32" width="8" height="8" fill="#bfdbfe"/><circle cx="32" cy="32" r="4" fill="#fff" stroke="#92400e" stroke-width="1.5"/>',
  },
  house: {
    label: "House",
    svg: '<path d="M5 30L32 7l27 23z" fill="#ea580c"/><rect x="11" y="30" width="42" height="28" fill="#fef3c7"/><rect x="29" y="40" width="10" height="18" fill="#92400e"/><rect x="16" y="36" width="9" height="9" fill="#93c5fd"/>',
  },
  clock: {
    label: "Time",
    svg: '<circle cx="32" cy="32" r="27" fill="#6366f1"/><circle cx="32" cy="32" r="21" fill="#fff"/><path d="M32 18v14l9 6" stroke="#1e293b" stroke-width="3.5" fill="none" stroke-linecap="round"/>',
  },
  calendar: {
    label: "Shift / day",
    svg: '<rect x="7" y="11" width="50" height="46" rx="5" fill="#fff" stroke="#cbd5e1" stroke-width="2"/><path d="M7 16a5 5 0 0 1 5-5h40a5 5 0 0 1 5 5v10H7z" fill="#ef4444"/><rect x="17" y="5" width="4" height="12" rx="2" fill="#475569"/><rect x="43" y="5" width="4" height="12" rx="2" fill="#475569"/><g fill="#fca5a5"><rect x="15" y="32" width="8" height="8"/><rect x="28" y="32" width="8" height="8"/><rect x="41" y="32" width="8" height="8"/><rect x="15" y="44" width="8" height="8"/><rect x="28" y="44" width="8" height="8"/></g>',
  },
  task: {
    label: "Task",
    svg: '<rect x="11" y="9" width="42" height="50" rx="4" fill="#a16207"/><rect x="15" y="15" width="34" height="40" rx="2" fill="#fff"/><rect x="24" y="5" width="16" height="9" rx="3" fill="#64748b"/><path d="M20 27l3 3 5-6M20 41l3 3 5-6" stroke="#16a34a" stroke-width="2.5" fill="none" stroke-linecap="round" stroke-linejoin="round"/><path d="M33 28h11M33 42h11" stroke="#94a3b8" stroke-width="2.5" stroke-linecap="round"/>',
  },
  skill: {
    label: "Skill",
    svg: '<path d="M32 4l8.5 17.5 19 2.5-14 13 3.5 19L32 47l-17 9 3.5-19-14-13 19-2.5z" fill="#facc15" stroke="#ca8a04" stroke-width="2" stroke-linejoin="round"/>',
  },
  money: {
    label: "Cost / money",
    svg: '<rect x="3" y="15" width="58" height="34" rx="4" fill="#22c55e"/><rect x="8" y="20" width="48" height="24" rx="2" fill="none" stroke="#bbf7d0" stroke-width="2"/><circle cx="32" cy="32" r="8" fill="#bbf7d0"/><path d="M32 26v12" stroke="#15803d" stroke-width="3"/>',
  },
};

/** The key a type is drawn with when nothing matches: a disc in its colour. */
export const GENERIC_ICON = "generic";

/** Words in a type's name that pick a gallery icon. The name is split on
 * `_`, and the FIRST word that matches wins -- so `cable_car` is a cable car,
 * not a car, and `night_shift` is a shift. */
const KEYWORDS: Record<string, string[]> = {
  hotel: ["hotel", "inn", "hostel", "motel", "lodge", "accommodation", "garni", "resort"],
  bus_stop: ["bus", "busstop", "stop"],
  city: ["city", "town", "village", "municipality"],
  restaurant: ["restaurant", "cafe", "bar", "food", "diner", "canteen", "kitchen", "pizzeria"],
  cable_car: ["cable", "cablecar", "gondola", "lift", "funicular"],
  mountain: ["mountain", "ski", "slope", "peak", "hill", "trail"],
  province: ["province", "region", "state", "country", "territory", "district", "area", "zone"],
  pin: ["location", "site", "place", "address", "point", "spot", "destination"],
  person: [
    "employee", "person", "people", "staff", "nurse", "doctor", "worker", "driver", "agent",
    "user", "customer", "patient", "member", "operator", "technician", "guest", "student", "teacher",
  ],
  team: ["team", "crew", "squad", "group", "department"],
  building: ["organization", "organisation", "company", "org", "office", "unit", "division", "branch", "business"],
  factory: ["factory", "plant", "mill", "production"],
  machine: ["machine", "equipment", "device", "robot", "asset"],
  tool: ["tool", "maintenance", "repair"],
  truck: ["truck", "vehicle", "lorry", "van", "fleet"],
  car: ["car", "taxi"],
  train: ["train", "rail", "station", "metro", "tram"],
  plane: ["airport", "flight", "plane", "aircraft"],
  warehouse: ["warehouse", "depot", "storage", "stock", "inventory", "hub"],
  box: ["product", "item", "resource", "material", "part", "package", "sku", "good"],
  shop: ["shop", "store", "retail", "market", "outlet", "supplier"],
  hospital: ["hospital", "clinic", "ward"],
  school: ["school", "university", "college", "classroom", "course"],
  house: ["house", "home", "household", "residence", "apartment"],
  clock: ["time", "hour", "slot", "period", "timeslot", "interval"],
  calendar: ["shift", "day", "week", "date", "calendar", "schedule", "month", "rota", "roster"],
  task: ["task", "job", "order", "activity", "operation", "request", "ticket", "project"],
  skill: ["skill", "qualification", "certificate", "competency", "licence", "license"],
  money: ["cost", "budget", "price", "money", "payment", "invoice", "revenue"],
};

const KEY_BY_WORD = new Map<string, string>(
  Object.entries(KEYWORDS).flatMap(([key, words]) => words.map((word) => [word, key] as const))
);

/** `entity_type.role` -> the icon a type of that role defaults to. */
const ROLE_ICON: Record<string, string> = {
  agent: "person",
  resource: "box",
  time: "clock",
  location: "pin",
  task: "task",
  org: "building",
};

function keyForWord(word: string): string | undefined {
  // Exact first, then the singular -- "employees" is an employee, but "bus"
  // must not become "bu".
  return KEY_BY_WORD.get(word) ?? (word.endsWith("s") ? KEY_BY_WORD.get(word.slice(0, -1)) : undefined);
}

/** The gallery key a type gets when it has not chosen one. */
export function defaultIconKey(name: string, role?: string | null): string {
  for (const word of name.toLowerCase().split(/[^a-z0-9]+/)) {
    const key = word ? keyForWord(word) : undefined;
    if (key) return key;
  }
  return (role && ROLE_ICON[role]) || GENERIC_ICON;
}

export function isUploadedIcon(icon: string | null | undefined): icon is string {
  return typeof icon === "string" && icon.startsWith("data:");
}

/** What a type is actually drawn with: an upload, a known gallery key, or
 * the default. An unknown key (from a newer build) falls back rather than
 * drawing nothing. */
export function resolveIcon(type: { name: string; role?: string | null; icon?: string | null }): string {
  if (isUploadedIcon(type.icon)) return type.icon;
  if (type.icon && ICONS[type.icon]) return type.icon;
  return defaultIconKey(type.name, type.role);
}

function genericSvg(colour: string): string {
  return `<circle cx="32" cy="32" r="24" fill="${colour}"/><circle cx="32" cy="32" r="24" fill="none" stroke="#0f172a" stroke-opacity=".15" stroke-width="2"/>`;
}

function svgUri(svg: string): string {
  return `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`;
}

/** An `<img>`-ready source for a resolved icon, without the caption --
 * what the picker shows. */
export function iconSrc(resolved: string, colour: string): string {
  if (isUploadedIcon(resolved)) return resolved;
  const inner = ICONS[resolved]?.svg ?? genericSvg(colour);
  return svgUri(`<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">${inner}</svg>`);
}

/** `bus_stop` -> `Bus stop`: the caption under a node reads as prose. */
export function humaniseTypeName(name: string): string {
  const spaced = name.replace(/_+/g, " ").trim();
  return spaced ? spaced[0].toUpperCase() + spaced.slice(1) : name;
}

/** The caption's colour: the type's own when it reads on the white canvas
 * (4.5:1, WCAG AA for small text), otherwise the app's dark label colour. */
export function captionColour(colour: string): string {
  const value = normaliseColour(colour);
  return value && contrastRatio(value, "#ffffff") >= 4.5 ? value : LABEL_DARK;
}

function escapeXml(value: string): string {
  return value.replace(/[&<>"']/g, (ch) => `&#${ch.charCodeAt(0)};`);
}

export const NODE_ICON_SIZE = 56;
const CAPTION_HEIGHT = 18;
/** Rough advance of a 12px semibold sans glyph. An estimate, like the ER
 * view's widths: jsdom cannot measure text, and a slightly wide box only
 * adds transparent margin. */
const CAPTION_CHAR_WIDTH = 7;

export type NodeImage = { image: string; w: number; h: number };

const cache = new Map<string, NodeImage>();

/**
 * The picture one entity type's nodes are drawn with: its icon, and its name
 * underneath in its colour -- one image per TYPE, so a 10,000-node graph
 * decodes a handful of images, not 10,000. The entity's own name is the
 * cytoscape label, drawn above (see `graphStylesheet`).
 */
export function nodeImage(type: {
  name: string;
  role?: string | null;
  icon?: string | null;
  colour: string;
}): NodeImage {
  const resolved = resolveIcon(type);
  const key = `${type.name}|${type.role ?? ""}|${type.colour}|${resolved}`;
  const hit = cache.get(key);
  if (hit) return hit;

  const caption = humaniseTypeName(type.name);
  const w = Math.max(NODE_ICON_SIZE + 8, Math.ceil(caption.length * CAPTION_CHAR_WIDTH) + 10);
  const h = NODE_ICON_SIZE + CAPTION_HEIGHT + 4;
  const x = (w - NODE_ICON_SIZE) / 2;
  const picture = isUploadedIcon(resolved)
    ? `<image href="${escapeXml(resolved)}" x="${x}" y="2" width="${NODE_ICON_SIZE}" height="${NODE_ICON_SIZE}" preserveAspectRatio="xMidYMid meet"/>`
    : `<svg x="${x}" y="2" width="${NODE_ICON_SIZE}" height="${NODE_ICON_SIZE}" viewBox="0 0 64 64">${
        ICONS[resolved]?.svg ?? genericSvg(type.colour)
      }</svg>`;
  const text =
    `<text x="${w / 2}" y="${h - 5}" text-anchor="middle" font-family="system-ui, -apple-system, 'Segoe UI', sans-serif"` +
    ` font-size="12" font-weight="600" fill="${captionColour(type.colour)}"` +
    ` stroke="#ffffff" stroke-width="3" paint-order="stroke">${escapeXml(caption)}</text>`;
  const result: NodeImage = {
    image: svgUri(
      `<svg xmlns="http://www.w3.org/2000/svg" width="${w}" height="${h}" viewBox="0 0 ${w} ${h}">${picture}${text}</svg>`
    ),
    w,
    h,
  };
  cache.set(key, result);
  return result;
}

/** The limits the API enforces (`app.api.validation.validate_icon`),
 * restated so a wrong file is refused before it is sent. */
export const UPLOAD_MAX_BYTES = 200 * 1024;
export const UPLOAD_TYPES = ["image/png", "image/svg+xml", "image/webp"] as const;

const SVG_DANGER: [RegExp, string][] = [
  [/<\s*script/i, "a <script> element"],
  [/<\s*foreignObject/i, "a <foreignObject> element"],
  [/<!\s*(DOCTYPE|ENTITY)/i, "a DOCTYPE or entity declaration"],
  [/\son[a-z]+\s*=/i, "an event-handler attribute"],
  [/javascript\s*:/i, "a javascript: link"],
  [/href\s*=\s*["'](?!#|data:)/i, "a link to another file"],
  [/url\(\s*["']?(?!#|data:)/i, "a url() to another file"],
];

/** Why a file cannot be uploaded, or null if it can. `text` is the file's
 * content, needed only for an SVG. Mirrors the server, which still decides. */
export function uploadProblem(file: { type: string; size: number }, text?: string): string | null {
  if (!(UPLOAD_TYPES as readonly string[]).includes(file.type)) {
    return "Choose a PNG, SVG or WebP image.";
  }
  if (file.size > UPLOAD_MAX_BYTES) {
    return `That image is ${Math.round(file.size / 1024)} KB; the limit is 200 KB.`;
  }
  if (file.type === "image/svg+xml" && text !== undefined) {
    for (const [pattern, what] of SVG_DANGER) {
      if (pattern.test(text)) return `This SVG contains ${what}; upload an SVG with shapes only, or a PNG.`;
    }
  }
  return null;
}
