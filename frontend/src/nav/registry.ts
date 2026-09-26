/**
 * Shared navigation registry (OAAS proposal §3 / backlog N01).
 *
 * One place for destination ownership, labels, routes, and capabilities.
 * AppShell, CommandPalette, breadcrumbs, and compatibility redirects all
 * read from here so they cannot drift.
 */

export type NavScope = "global" | "domain" | "problem" | "operations" | "administration" | "help";

export type Destination = {
  /** Stable id for tests and analytics. */
  id: string;
  /** Path the router serves today (may still be a legacy path). */
  path: string;
  /** Preferred path once migration completes; equals `path` when already canonical. */
  canonical: string;
  /** Sentence-case label shown in the sidebar. */
  label: string;
  /** Short purpose for page headers / empty states. */
  purpose: string;
  scope: NavScope;
  /** Sidebar group key. */
  group: string;
  capability?: string;
  /** Old paths that should land here. */
  aliases?: string[];
};

/** User-facing terms (proposal §3.1 / §3.3). */
export const TERMS = {
  domain: "shared data for a business area",
  recordTypes: "Record types",
  records: "Records",
  relationshipTypes: "Relationship types",
  relationships: "Relationships",
  parameters: "Parameters",
  mapGraph: "Map & graph",
  problems: "Problems",
  model: "Model",
  versions: "Versions",
  scenarios: "Scenarios",
  runs: "Runs & results",
  workspace: "Guided run view",
  templates: "Template library",
} as const;

/** Canonical path templates (OAAS §3.5). `:domainId` / `:problemId` filled by `scopedPath`. */
const DOMAIN_TEMPLATES: Record<string, string> = {
  "record-types": "/domains/:domainId/structure/record-types",
  "relationship-types": "/domains/:domainId/structure/relationship-types",
  records: "/domains/:domainId/data/records",
  relationships: "/domains/:domainId/data/relationships",
  parameters: "/domains/:domainId/data/parameters",
  "map-graph": "/domains/:domainId/data/explore",
  problems: "/domains/:domainId/problems",
  model: "/domains/:domainId/problems/:problemId/model",
  versions: "/domains/:domainId/problems/:problemId/versions",
  scenarios: "/domains/:domainId/problems/:problemId/scenarios",
  runs: "/domains/:domainId/problems/:problemId/runs",
  workspace: "/domains/:domainId/problems/:problemId/runs",
};

export const DESTINATIONS: Destination[] = [
  {
    id: "home",
    path: "/",
    canonical: "/home",
    label: "Home",
    purpose: "Continue planning from recent work.",
    scope: "global",
    group: "home",
    aliases: ["/home"],
  },
  {
    id: "domains",
    path: "/public/domain",
    canonical: "/domains",
    label: "All domains",
    purpose: "Choose shared operational data for a business area.",
    scope: "global",
    group: "domains",
    aliases: ["/domains"],
  },
  {
    id: "record-types",
    path: "/entity-types",
    canonical: "/domains/:domainId/structure/record-types",
    label: TERMS.recordTypes,
    purpose: "Define what kinds of records exist in this domain.",
    scope: "domain",
    group: "structure",
  },
  {
    id: "relationship-types",
    path: "/relationship-types",
    canonical: "/domains/:domainId/structure/relationship-types",
    label: TERMS.relationshipTypes,
    purpose: "Define how record types connect.",
    scope: "domain",
    group: "structure",
  },
  {
    id: "records",
    path: "/entities",
    canonical: "/domains/:domainId/data/records",
    label: TERMS.records,
    purpose: "Edit the domain's operational records.",
    scope: "domain",
    group: "data",
  },
  {
    id: "relationships",
    path: "/relationships",
    canonical: "/domains/:domainId/data/relationships",
    label: TERMS.relationships,
    purpose: "Edit links between records.",
    scope: "domain",
    group: "data",
  },
  {
    id: "parameters",
    path: "/parameters",
    canonical: "/domains/:domainId/data/parameters",
    label: TERMS.parameters,
    purpose: "Edit numeric and structured inputs.",
    scope: "domain",
    group: "data",
  },
  {
    id: "map-graph",
    path: "/graph",
    canonical: "/domains/:domainId/data/explore",
    label: TERMS.mapGraph,
    purpose: "Explore domain data on the map and graph.",
    scope: "domain",
    group: "data",
  },
  {
    id: "problems",
    path: "/public/problem",
    canonical: "/domains/:domainId/problems",
    label: TERMS.problems,
    purpose: "Decisions to optimize in this domain.",
    scope: "domain",
    group: "problems",
  },
  {
    id: "model",
    path: "/model",
    canonical: "/domains/:domainId/problems/:problemId/model",
    label: TERMS.model,
    purpose: "Describe decisions, rules and goals.",
    scope: "problem",
    group: "problems",
  },
  {
    id: "versions",
    path: "/versions",
    canonical: "/domains/:domainId/problems/:problemId/versions",
    label: "Model versions",
    purpose: "Immutable published model definitions and quality checks.",
    scope: "problem",
    group: "problems",
  },
  {
    id: "scenarios",
    path: "/scenarios",
    canonical: "/domains/:domainId/problems/:problemId/scenarios",
    label: TERMS.scenarios,
    purpose: "Alternative assumptions and what-if patches.",
    scope: "problem",
    group: "problems",
  },
  {
    id: "runs",
    path: "/runs",
    canonical: "/domains/:domainId/problems/:problemId/runs",
    label: "Runs",
    purpose: "Executions and results for this problem.",
    scope: "problem",
    group: "results",
  },
  {
    id: "workspace",
    path: "/workspace",
    canonical: "/domains/:domainId/problems/:problemId/runs",
    label: TERMS.workspace,
    purpose: "Guided view of a run (opens Runs with the guided tab).",
    scope: "problem",
    group: "results",
    aliases: ["/workspace"],
  },
  {
    id: "templates",
    path: "/public/template",
    canonical: "/templates",
    label: "Templates",
    purpose: "Locally installed, versioned starting points.",
    scope: "global",
    group: "templates",
    capability: "model.publish",
    aliases: ["/templates"],
  },
  {
    id: "ops-queue",
    path: "/ops/queue",
    canonical: "/ops/queue",
    label: "Run queue",
    purpose: "Queued and running solves per organization.",
    scope: "operations",
    group: "operations",
  },
  {
    id: "solvers",
    path: "/solvers",
    canonical: "/solvers",
    label: "Solver health & licenses",
    purpose: "Installed solvers, conformance and licences.",
    scope: "operations",
    group: "operations",
  },
  {
    id: "ops-audit",
    path: "/ops/audit",
    canonical: "/ops/audit",
    label: "Audit history",
    purpose: "Append-only record of who changed what.",
    scope: "operations",
    group: "operations",
  },
  {
    id: "ops-backups",
    path: "/ops/backups",
    canonical: "/ops/backups",
    label: "Backups & recovery",
    purpose: "Last dump, RPO/RTO targets, and restore commands.",
    scope: "operations",
    group: "operations",
  },
  {
    id: "settings",
    path: "/settings",
    canonical: "/settings",
    label: "Platform settings",
    purpose: "Platform, domain and problem defaults.",
    scope: "administration",
    group: "administration",
  },
  {
    id: "api-keys",
    path: "/api-keys",
    canonical: "/api-keys",
    label: "API keys",
    purpose: "Programmatic credentials for this organization.",
    scope: "administration",
    group: "administration",
  },
  {
    id: "organizations",
    path: "/iam/organization",
    canonical: "/iam/organization",
    label: "Organizations",
    purpose: "Tenant organizations.",
    scope: "administration",
    group: "administration",
    capability: "domain.edit",
  },
  {
    id: "users",
    path: "/iam/user_account",
    canonical: "/iam/user_account",
    label: "Users",
    purpose: "People in this organization.",
    scope: "administration",
    group: "administration",
    capability: "iam.manage",
  },
  {
    id: "roles",
    path: "/iam/role",
    canonical: "/iam/role",
    label: "Roles",
    purpose: "Named bags of capabilities (roles and permissions).",
    scope: "administration",
    group: "administration",
    capability: "iam.manage",
  },
  {
    id: "user-roles",
    path: "/iam/user_role",
    canonical: "/iam/user_role",
    label: "User roles",
    purpose: "Which users hold which roles.",
    scope: "administration",
    group: "administration",
    capability: "iam.manage",
  },
  {
    id: "role-capabilities",
    path: "/iam/role_capability",
    canonical: "/iam/role_capability",
    label: "Role capabilities",
    purpose: "Grants on each role.",
    scope: "administration",
    group: "administration",
    capability: "iam.manage",
  },
  {
    id: "capabilities",
    path: "/iam/capability",
    canonical: "/iam/capability",
    label: "Capabilities",
    purpose: "Every verb the platform can grant.",
    scope: "administration",
    group: "administration",
    capability: "iam.manage",
  },
];

export type NavGroupDef = {
  key: string;
  label: string;
  /** Destination ids in display order. */
  itemIds: string[];
  emptyNote?: string;
  /** Place this group below a separator (Administration). */
  footer?: boolean;
};

/** Sidebar groups matching proposal §3.2. */
export const NAV_GROUP_DEFS: NavGroupDef[] = [
  { key: "home", label: "Home", itemIds: ["home"] },
  {
    key: "domains",
    label: "Domains",
    itemIds: ["domains", "records", "relationships", "parameters", "map-graph"],
  },
  {
    key: "structure",
    label: "Data structure",
    itemIds: ["record-types", "relationship-types"],
  },
  {
    key: "problems",
    label: "Problems",
    itemIds: ["problems", "model", "versions", "scenarios"],
  },
  {
    key: "results",
    label: "Runs & results",
    itemIds: ["runs", "workspace"],
  },
  {
    key: "templates",
    label: "Template library",
    itemIds: ["templates"],
  },
  {
    key: "operations",
    label: "Operations",
    itemIds: ["ops-queue", "solvers", "ops-audit", "ops-backups"],
  },
  {
    key: "administration",
    label: "Administration",
    itemIds: [
      "settings",
      "api-keys",
      "organizations",
      "users",
      "roles",
      "user-roles",
      "role-capabilities",
      "capabilities",
    ],
    footer: true,
  },
];

const byId = new Map(DESTINATIONS.map((d) => [d.id, d]));
const byPath = new Map<string, Destination>();
for (const d of DESTINATIONS) {
  byPath.set(d.path, d);
  byPath.set(d.canonical, d);
  for (const a of d.aliases ?? []) byPath.set(a, d);
}

export function destination(id: string): Destination | undefined {
  return byId.get(id);
}

/** Strip `/domains/:id` (and optional problem segment) to a legacy-comparable path. */
export function stripDomainPrefix(pathname: string): string {
  const m = pathname.match(/^\/domains\/\d+(\/.*)?$/);
  if (!m) return pathname;
  const rest = m[1] ?? "";
  // Problem-scoped paths first (more specific than /problems).
  if (/^\/problems\/\d+\/model/.test(rest)) return "/model";
  if (/^\/problems\/\d+\/versions/.test(rest)) return "/versions";
  if (/^\/problems\/\d+\/scenarios/.test(rest)) return "/scenarios";
  if (/^\/problems\/\d+\/runs/.test(rest)) return "/runs";
  if (/^\/problems\/\d+/.test(rest)) return "/public/problem";
  const map: Record<string, string> = {
    "/structure/record-types": "/entity-types",
    "/structure/relationship-types": "/relationship-types",
    "/data/records": "/entities",
    "/data/relationships": "/relationships",
    "/data/parameters": "/parameters",
    "/data/explore": "/graph",
    "/problems": "/public/problem",
    "/overview": "/public/domain",
  };
  for (const [prefix, legacy] of Object.entries(map)) {
    if (rest === prefix || rest.startsWith(`${prefix}/`)) return legacy;
  }
  return pathname;
}

export function destinationForPath(pathname: string): Destination | undefined {
  const normalized = stripDomainPrefix(pathname);
  if (byPath.has(pathname)) return byPath.get(pathname);
  if (byPath.has(normalized)) return byPath.get(normalized);
  let best: Destination | undefined;
  for (const d of DESTINATIONS) {
    if (normalized === d.path || normalized.startsWith(`${d.path}/`)) {
      if (!best || d.path.length > best.path.length) best = d;
    }
  }
  return best;
}

export type ScopedNavContext = {
  domainId?: number | null;
  problemId?: number | null;
};

/**
 * Preferred href for a destination given the current domain/problem context.
 * Falls back to the legacy `path` when required ids are missing.
 */
export function scopedPath(id: string, ctx: ScopedNavContext = {}): string {
  const d = byId.get(id);
  if (!d) return "/";
  const template = DOMAIN_TEMPLATES[id];
  if (!template) return d.path;
  if (d.scope === "domain" || d.scope === "problem") {
    if (ctx.domainId == null) return d.path;
    let out = template.replace(":domainId", String(ctx.domainId));
    if (out.includes(":problemId")) {
      if (ctx.problemId == null) {
        if (id === "problems") return `/domains/${ctx.domainId}/problems`;
        return d.path;
      }
      out = out.replace(":problemId", String(ctx.problemId));
    }
    if (id === "workspace") return `${out}?tab=guided`;
    return out;
  }
  return d.path;
}

export function buildNavGroups(ctx: ScopedNavContext = {}): {
  key: string;
  label: string;
  items: { to: string; label: string; capability?: string; id: string }[];
  emptyNote?: string;
  footer?: boolean;
}[] {
  return NAV_GROUP_DEFS.map((g) => ({
    key: g.key,
    label: g.label,
    emptyNote: g.emptyNote,
    footer: g.footer,
    items: g.itemIds
      .map((id) => byId.get(id))
      .filter((d): d is Destination => d != null)
      .map((d) => ({
        id: d.id,
        to: scopedPath(d.id, ctx),
        label: d.label,
        capability: d.capability,
      })),
  }));
}

/** Resolve a compatibility alias to the path AppShell already serves. */
export function resolveAlias(pathname: string): string | null {
  const d = byPath.get(pathname);
  if (!d) return null;
  if (pathname === d.path) return null;
  // `/domains` alone aliases to the all-domains list; scoped `/domains/:id/...` is not an alias.
  if (pathname === "/domains" || pathname === "/home" || pathname === "/templates") return d.path;
  if (pathname === d.canonical && !d.canonical.includes(":")) return d.path;
  return null;
}
