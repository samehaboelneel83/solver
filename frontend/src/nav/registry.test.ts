import { describe, expect, it } from "vitest";
import {
  buildNavGroups,
  destination,
  destinationForPath,
  resolveAlias,
  scopedPath,
  stripDomainPrefix,
  TERMS,
} from "./registry";

describe("nav registry", () => {
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
