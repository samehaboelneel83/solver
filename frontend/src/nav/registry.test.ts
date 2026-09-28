import { describe, expect, it } from "vitest";
import {
  buildNavGroups,
  buildSidebarGroups,
  destination,
  destinationForPath,
  resolveAlias,
  scopedPath,
  stripDomainPrefix,
  TERMS,
} from "./registry";

describe("nav registry", () => {
  it("takes domain and problem ids from the URL instead of stale preferences", () => {
    const groups = buildSidebarGroups("/domains/8/problems/12/inputs", { domainId: 7, problemId: 9 });
    const workflow = groups.find(group => group.key === "planning")!;
    expect(workflow.items.map(item => item.label)).toEqual(["Problem overview", "Inputs", "Build model", "Versions", "Scenarios", "Runs & results"]);
    expect(workflow.items.find(item => item.id === "inputs")?.to).toBe("/domains/8/problems/12/inputs");
  });
  it("resolves new hubs without swallowing their child routes", () => {
    expect(destinationForPath("/domains/8/data/sources")?.id).toBe("sources");
    expect(destinationForPath("/domains/8/data/quality")?.id).toBe("quality");
    expect(destinationForPath("/domains/8/data/records/3")?.id).toBe("records");
    expect(destinationForPath("/domains/8/structure/record-types")?.id).toBe("record-types");
    expect(destinationForPath("/domains/8/problems/12/inputs")?.id).toBe("inputs");
  });
  it("gates operational and administration destinations with existing capabilities", () => {
    expect(destination("ops-queue")?.capability).toBe("solver.configure");
    expect(destination("solvers")?.capability).toBe("solver.configure");
    expect(destination("access")?.capability).toBe("iam.manage");
    expect(destination("ops-audit")?.scope).toBe("administration");
  });
  it("keeps global navigation independent of a remembered problem", () => {
    const ids = buildSidebarGroups("/", { domainId: 7, problemId: 9 }).flatMap((g) => g.items.map((i) => i.id));
    expect(ids).toContain("domains");
    expect(ids).not.toContain("model");
  });
  it("does not turn global pages into the remembered domain", () => {
    const links = buildSidebarGroups("/ops/queue", { domainId: 7 }).flatMap((g) => g.items);
    expect(links.some((i) => i.id === "data-records")).toBe(false);
    expect(links.some((i) => i.id === "data-structure")).toBe(false);
    expect(links.some((i) => i.id === "ops-queue")).toBe(true);
  });
  it("keeps the same top group on platform pages as inside a domain", () => {
    const labels = (path: string) => buildSidebarGroups(path, { domainId: 7 }).map((g) => g.label);
    expect(labels("/ops/queue")[0]).toBe("Navigate");
    expect(labels("/domains/7/problems/9/runs")[0]).toBe("Navigate");
  });
  it("offers the recent problem back on a platform page, as links to its own routes", () => {
    const groups = buildSidebarGroups("/ops/queue", { domainId: 7 }, { domainId: 7, problemId: 9 });
    const recent = groups.find((g) => g.key === "recent")!;
    expect(recent.label).toBe("Recent problem");
    expect(recent.items.find((i) => i.id === "runs")?.to).toBe("/domains/7/problems/9/runs");
    expect(recent.items.find((i) => i.id === "model")?.to).toBe("/domains/7/problems/9/model");
    // Still a platform page: the operations group is its own, not the problem's.
    expect(groups.some((g) => g.key === "planning")).toBe(false);
    expect(groups.find((g) => g.key === "operations")?.items.some((i) => i.id === "ops-queue")).toBe(true);
  });
  it("offers a recent domain when no problem was open", () => {
    const recent = buildSidebarGroups("/settings", { domainId: 7 }, { domainId: 7, problemId: null }).find((g) => g.key === "recent")!;
    expect(recent.label).toBe("Recent domain");
    expect(recent.items.map((i) => i.to)).toEqual(["/domains/7/overview", "/domains/7/problems"]);
  });
  it("drops the recent shortcut once another domain is selected", () => {
    const groups = buildSidebarGroups("/ops/queue", { domainId: 8 }, { domainId: 7, problemId: 9 });
    expect(groups.some((g) => g.key === "recent")).toBe(false);
  });
  it("hides domain data on global pages when no domain is selected", () => {
    const ids = buildSidebarGroups("/", {}).flatMap((g) => g.items.map((i) => i.id));
    expect(ids).not.toContain("records");
  });
  it("offers domain data without showing an unselected problem's editor", () => {
    const ids = buildSidebarGroups("/domains/7/overview", { domainId: 7 }).flatMap((g) => g.items.map((i) => i.id));
    expect(ids).toContain("data-records");
    expect(ids).toContain("problems");
    expect(ids).not.toContain("model");
  });
  it("focuses problem navigation and retains a path back to shared data", () => {
    const links = buildSidebarGroups("/domains/7/problems/9/model", { domainId: 7, problemId: 9 }).flatMap((g) => g.items);
    expect(links.find((i) => i.id === "domain-overview")?.to).toBe("/domains/7/overview");
    expect(links.filter((i) => i.to === "/domains/7/problems/9/runs")).toHaveLength(1);
    expect(links.some((i) => i.id === "records")).toBe(false);
  });
  it("offers overview links only with enough context and names them in breadcrumbs", () => {
    expect(buildNavGroups().flatMap((group) => group.items).some((item) => item.id.endsWith("-overview"))).toBe(false);
    const links = buildNavGroups({ domainId: 7, problemId: 3 }).flatMap((group) => group.items);
    expect(links.find((item) => item.id === "problem-overview")?.to).toBe("/domains/7/problems/3/overview");
    expect(destinationForPath("/domains/7/overview")?.id).toBe("domain-overview");
    expect(destinationForPath("/domains/7/problems/3/overview")?.id).toBe("problem-overview");
  });
  it("maps Records to the entities route with planner wording", () => {
    const records = destination("records");
    expect(records?.label).toBe(TERMS.records);
    expect(records?.path).toBe("/entities");
  });

  it("resolves aliases to legacy paths", () => {
    expect(resolveAlias("/home")).toBe("/");
    expect(resolveAlias("/domains")).toBe("/public/domain");
    expect(resolveAlias("/templates")).toBe("/public/template");
    expect(resolveAlias("/")).toBeNull();
  });

  it("finds destinations by path prefix for detail routes", () => {
    expect(destinationForPath("/entities/12")?.id).toBe("records");
  });

  it("maps canonical domain paths back to destinations", () => {
    expect(stripDomainPrefix("/domains/7/data/records")).toBe("/entities");
    expect(destinationForPath("/domains/7/data/records")?.id).toBe("records");
    expect(destinationForPath("/domains/7/problems/3/runs")?.id).toBe("runs");
  });

  it("builds scoped sidebar hrefs when a domain is selected", () => {
    expect(scopedPath("records", { domainId: 7 })).toBe("/domains/7/data/records");
    expect(scopedPath("model", { domainId: 7, problemId: 3 })).toBe("/domains/7/problems/3/model");
    expect(scopedPath("model", { domainId: 7 })).toBe("/model");
  });

  it("builds sidebar groups with Administration in the footer set", () => {
    const groups = buildNavGroups();
    expect(groups.map((g) => g.key)).toContain("administration");
    expect(groups.find((g) => g.key === "administration")?.footer).toBe(true);
    expect(groups.find((g) => g.key === "domains")?.items.some((i) => i.label === "Records")).toBe(true);
  });
});
