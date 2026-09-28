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
  mapGraph: "Data relationships (graph)",
  problems: "Problems",
  model: "Build model",
  versions: "Versions",
  scenarios: "Scenarios",
  runs: "Runs & results",
  workspace: "Guided run view",
  templates: "Template library",
} as const;

/** Canonical path templates (OAAS §3.5). `:domainId` / `:problemId` filled by `scopedPath`. */
const DOMAIN_TEMPLATES: Record<string, string> = {
  "domain-overview": "/domains/:domainId/overview",
  "problem-overview": "/domains/:domainId/problems/:problemId/overview",
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
  inputs: "/domains/:domainId/problems/:problemId/inputs",
  "data-records": "/domains/:domainId/data",
  "data-structure": "/domains/:domainId/structure",
  sources: "/domains/:domainId/data/sources",
  quality: "/domains/:domainId/data/quality",
};

export const DESTINATIONS: Destination[] = [
  { id: "inputs", path: "/inputs", canonical: DOMAIN_TEMPLATES.inputs, label: "Inputs", purpose: "Prepare shared data and scenario inputs.", scope: "problem", group: "problems" },
  { id: "data-records", path: "/data", canonical: DOMAIN_TEMPLATES["data-records"], label: "Records & relationships", purpose: "Manage operational records, links and values.", scope: "domain", group: "data" },
  { id: "data-structure", path: "/structure", canonical: DOMAIN_TEMPLATES["data-structure"], label: "Data structure", purpose: "Define record types and relationship types.", scope: "domain", group: "data" },
  { id: "sources", path: "/sources", canonical: DOMAIN_TEMPLATES.sources, label: "Sources & imports", purpose: "Review configured database sources.", scope: "domain", group: "data", capability: "integration.run" },
  { id: "quality", path: "/quality", canonical: DOMAIN_TEMPLATES.quality, label: "Quality checks", purpose: "Review data and model validation workflows.", scope: "domain", group: "data" },
  { id: "access", path: "/administration/access", canonical: "/administration/access", label: "Access & policies", purpose: "Manage people, permissions and platform policies.", scope: "administration", group: "administration", capability: "iam.manage" },
  { id: "domain-overview", path: "/domains/:domainId/overview", canonical: "/domains/:domainId/overview",
    label: "Domain overview", purpose: "Prepare data and continue a planning problem.", scope: "domain", group: "domains" },
  { id: "problem-overview", path: "/domains/:domainId/problems/:problemId/overview", canonical: "/domains/:domainId/problems/:problemId/overview",
    label: "Problem overview", purpose: "See model readiness, scenarios and results.", scope: "problem", group: "problems" },
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
    label: "Versions",
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
    label: "Runs & results",
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
    label: "Runs & queues",
    purpose: "Queued and running solves per organization.",
    scope: "operations",
    group: "operations",
    capability: "solver.configure",
  },
  {
    id: "solvers",
    path: "/solvers",
    canonical: "/solvers",
    label: "Workers & solver availability",
    purpose: "Installed solvers, conformance and licences.",
    scope: "operations",
    group: "operations",
    capability: "solver.configure",
  },
  {
    id: "ops-audit",
    path: "/ops/audit",
    canonical: "/ops/audit",
    label: "Audit history",
    purpose: "Append-only record of who changed what.",
    scope: "administration",
    group: "administration",
    capability: "iam.manage",
  },
  {
    id: "ops-backups",
    path: "/ops/backups",
    canonical: "/ops/backups",
    label: "Backups & recovery",
    purpose: "Last dump, RPO/RTO targets, and restore commands.",
    scope: "operations",
    group: "operations",
    capability: "solver.configure",
  },
  {
    id: "help-start",
    path: "/help/getting-started",
    canonical: "/help/getting-started",
    label: "Getting started",
    purpose: "From sign-in to a first optimal answer.",
    scope: "help",
    group: "help",
  },
  {
    id: "help-modeling",
    path: "/help/modeling",
    canonical: "/help/modeling",
    label: "Modeling guide",
    purpose: "How a business question becomes a model.",
    scope: "help",
    group: "help",
  },
  {
    id: "help-coverage",
    path: "/help/coverage",
    canonical: "/help/coverage",
    label: "Problem coverage & limitations",
    purpose: "What this install claims to run.",
    scope: "help",
    group: "help",
  },
  {
    id: "help-api",
    path: "/help/api",
    canonical: "/help/api",
    label: "API reference",
    purpose: "OpenAPI docs and API keys on this install.",
    scope: "help",
    group: "help",
  },
  {
    id: "help-releases",
    path: "/help/release-notes",
    canonical: "/help/release-notes",
    label: "Release notes",
    purpose: "Recent product deliveries on this line.",
    scope: "help",
    group: "help",
  },
  {
    id: "settings",
    path: "/settings",
    canonical: "/settings",
    label: "Platform settings",
    purpose: "Platform, domain and problem defaults.",
    scope: "administration",
    group: "administration",
    capability: "settings.edit",
  },
  {
    id: "help-install",
    path: "/help/install",
    canonical: "/help/install",
    label: "Installation & updates",
    purpose: "Offline bundle, digests, and recovery.",
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
    purpose: "People in this organization. Assign roles on each user's page.",
    scope: "administration",
    group: "administration",
    capability: "iam.manage",
  },
  {
    id: "roles",
    path: "/iam/role",
    canonical: "/iam/role",
    label: "Roles & permissions",
    purpose: "Named roles; grant capabilities on each role's page.",
    scope: "administration",
    group: "administration",
    capability: "iam.manage",
  },
  {
    id: "user-roles",
    path: "/iam/user_role",
    canonical: "/iam/user_role",
    label: "Role assignments",
    purpose: "Junction rows; prefer assigning roles from a user's page.",
    scope: "administration",
    group: "administration",
    capability: "iam.manage",
  },
  {
    id: "role-capabilities",
    path: "/iam/role_capability",
    canonical: "/iam/role_capability",
    label: "Role permissions",
    purpose: "Junction rows; prefer granting capabilities from a role's page.",
    scope: "administration",
    group: "administration",
    capability: "iam.manage",
  },
  {
    id: "capabilities",
    path: "/iam/capability",
    canonical: "/iam/capability",
    label: "Capabilities",
    purpose: "Every verb the platform can grant (catalogue).",
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
    itemIds: ["domains", "domain-overview", "records", "relationships", "parameters", "map-graph"],
  },
  {
    key: "structure",
    label: "Data structure",
    itemIds: ["record-types", "relationship-types"],
  },
  { key: "data", label: "Data", itemIds: ["data-records", "data-structure", "sources", "quality"] },
  {
    key: "problems",
    label: "Problems",
    itemIds: ["problems", "problem-overview", "inputs", "model", "versions", "scenarios"],
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
    itemIds: ["ops-queue", "solvers", "ops-backups"],
  },
  {
    key: "help",
    label: "Help",
    itemIds: [
      "help-start",
      "help-modeling",
      "help-coverage",
      "help-api",
      "help-releases",
    ],
  },
  {
    key: "administration",
    label: "Administration",
    itemIds: [
      "access",
      "ops-audit",
      "settings",
      "help-install",
      "api-keys",
      "organizations",
      "users",
      "roles",
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
  if (/^\/problems\/\d+\/inputs/.test(rest)) return "/inputs";
  if (/^\/problems\/\d+/.test(rest)) return "/public/problem";
  const map: Record<string, string> = {
    "/structure/record-types": "/entity-types",
    "/structure/relationship-types": "/relationship-types",
    "/data/records": "/entities",
    "/data/relationships": "/relationships",
    "/data/parameters": "/parameters",
    "/data/explore": "/graph",
    "/data/sources": "/sources",
    "/data/quality": "/quality",
    "/data": "/data",
    "/structure": "/structure",
    "/problems": "/public/problem",
    "/overview": "/public/domain",
  };
  for (const [prefix, legacy] of Object.entries(map)) {
    if (rest === prefix || rest.startsWith(`${prefix}/`)) return legacy;
  }
  return pathname;
}

export function destinationForPath(pathname: string): Destination | undefined {
  if (/^\/domains\/\d+(?:\/overview)?\/?$/.test(pathname)) return byId.get("domain-overview");
  if (/^\/domains\/\d+\/problems\/\d+(?:\/overview)?\/?$/.test(pathname)) return byId.get("problem-overview");
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
      .filter((d) => d.id !== "domain-overview" || ctx.domainId != null)
      .filter((d) => d.id !== "problem-overview" || (ctx.domainId != null && ctx.problemId != null))
      .filter((d) => !["data-records", "data-structure", "sources", "quality"].includes(d.id) || ctx.domainId != null)
      .filter((d) => d.id !== "inputs" || (ctx.domainId != null && ctx.problemId != null))
      .map((d) => ({
        id: d.id,
        to: scopedPath(d.id, ctx),
        label: d.label,
        capability: d.capability,
      })),
  }));
}

/** Where the person last worked: a domain, and a problem in it if one was open. */
export type RecentScope = { domainId: number; problemId: number | null };

/** The domain or problem a URL is scoped to, or null for a platform page. */
export function scopeOfPath(pathname: string): RecentScope | null {
  const route = pathname.match(/^\/domains\/(\d+)(?:\/problems\/(\d+))?(?:\/|$)/);
  return route ? { domainId: Number(route[1]), problemId: route[2] ? Number(route[2]) : null } : null;
}

/** A problem's own pages, which a domain switch can land on again in another problem. */
const PROBLEM_PAGES = new Set(["overview", "inputs", "model", "versions", "scenarios", "runs"]);

/**
 * Where choosing domain `next` in the sidebar should take the person, from
 * `pathname`: the same kind of page, never the old domain's records.
 *
 * - A problem page goes to the same page of the problem last opened in the
 *   new domain (`lastProblem`), or to that domain's problem list if none was.
 * - A domain page goes to the same page of the new domain, cut before any
 *   record id, since an id belongs to the old domain.
 * - A platform page (Home, operations, help) stays where it is: null.
 */
export function domainSwitchTarget(pathname: string, next: number, lastProblem: number | null): string | null {
  const scope = scopeOfPath(pathname);
  if (!scope) return null;
  if (scope.problemId !== null) {
    const page = pathname.split("/")[5] ?? "";
    if (lastProblem === null) return `/domains/${next}/problems`;
    return `/domains/${next}/problems/${lastProblem}/${PROBLEM_PAGES.has(page) ? page : "overview"}`;
  }
  const rest = pathname.split("/").slice(3).filter(Boolean);
  const cut = rest.findIndex((segment) => /^\d+$/.test(segment));
  const kept = cut === -1 ? rest : rest.slice(0, cut);
  return `/domains/${next}/${kept.length ? kept.join("/") : "overview"}`;
}

/**
 * Contextual sidebar; the palette retains the complete destination catalog.
 *
 * A platform page (operations, administration, help, home) is never scoped
 * to a remembered domain. But the tree must not jump away from the work in
 * hand either (plan §4.2: a recent domain is a shortcut, separate from
 * active scope), so `recent` -- the last domain or problem the person had
 * open -- is offered there as its own group of links back to it, when it is
 * in the domain still selected.
 */
export function buildSidebarGroups(pathname: string, ctx: ScopedNavContext = {}, recent: RecentScope | null = null): ReturnType<typeof buildNavGroups> {
  // Route context is authoritative, even before stored selection has caught up.
  const route = pathname.match(/^\/domains\/(\d+)(?:\/problems\/(\d+))?(?:\/|$)/);
  if (route) ctx = { domainId: Number(route[1]), problemId: route[2] ? Number(route[2]) : null };
  const groups = buildNavGroups(ctx);
  const inDomain = /^\/domains\/\d+(?:\/|$)/.test(pathname) && ctx.domainId != null;
  const inProblem = inDomain && /^\/domains\/\d+\/problems\/\d+(?:\/|$)/.test(pathname) && ctx.problemId != null;
  // Legacy pages retain their navigation until their canonical migration finishes.
  const legacy = destinationForPath(pathname);
  if (!inDomain && legacy && ["domain", "problem"].includes(legacy.scope) && !["domains"].includes(legacy.id)) return groups;
  const select = (key: string, label: string, ids: string[]) => ({
    key, label, items: ids.map((id) => {
      const d = byId.get(id)!;
      return { id, to: scopedPath(id, ctx), label: d.label, capability: d.capability };
    }),
  });
  const common = [
    select("operations", "Operations", ["ops-queue", "solvers"]),
    { ...select("administration", "Administration", ["access", "ops-audit", "settings"]), footer: true },
    select("help", "Help", ["help-start", "help-modeling", "help-coverage"]),
  ];
  if (inProblem) return [
    select("context", "Navigate", ["home", "domains", "domain-overview", "problems"]),
    select("planning", "This problem", ["problem-overview", "inputs", "model", "versions", "scenarios", "runs"]),
    ...common,
  ];
  if (inDomain) return [
    select("context", "Navigate", ["home", "domains", "templates"]),
    select("domain", "This domain", ["domain-overview", "problems"]),
    select("data", "Data", ["data-records", "data-structure", "map-graph", "sources", "quality"]),
    ...common,
  ];
  const navigate = select("context", "Navigate", ["home", "domains", "templates"]);
  const back = recent && ctx.domainId != null && recent.domainId === ctx.domainId ? recent : null;
  if (back?.problemId != null) {
    const scope = { domainId: back.domainId, problemId: back.problemId };
    return [navigate, {
      key: "recent", label: "Recent problem",
      items: ["problem-overview", "inputs", "model", "versions", "scenarios", "runs"].map((id) => {
        const d = byId.get(id)!;
        return { id, to: scopedPath(id, scope), label: d.label, capability: d.capability };
      }),
    }, ...common];
  }
  if (back) {
    const scope = { domainId: back.domainId, problemId: null };
    return [navigate, {
      key: "recent", label: "Recent domain",
      items: ["domain-overview", "problems"].map((id) => {
        const d = byId.get(id)!;
        return { id, to: scopedPath(id, scope), label: d.label, capability: d.capability };
      }),
    }, ...common];
  }
  return [navigate, ...common];
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
