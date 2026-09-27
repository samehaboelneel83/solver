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
  it("keeps global navigation independent of a remembered problem", () => {
    const ids = buildSidebarGroups("/", { domainId: 7, problemId: 9 }).flatMap((g) => g.items.map((i) => i.id));
    expect(ids).toContain("domains");
    expect(ids).not.toContain("model");
    expect(ids).not.toContain("records");
  });
  it("offers domain data without showing an unselected problem's editor", () => {
    const ids = buildSidebarGroups("/domains/7/overview", { domainId: 7 }).flatMap((g) => g.items.map((i) => i.id));
    expect(ids).toContain("records");
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
