import { existsSync, readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { MODEL_PARTS, OBJECTIVE_NODE_ID, buildModelView, modelDetails } from "./modelGraph";
import type { EntityType } from "../api/v1";

/**
 * The optimization view, built from the seeded workforce model -- the
 * contract's own worked example (`backend/tests/ir_fixtures.json`), read off
 * disk rather than copied, so this test is about the model people actually
 * have and cannot drift from it.
 *
 * What it pins is the part a picture could get quietly wrong: which rule
 * reads which variable and parameter, which sets a rule holds "for every" of,
 * which attribute a rule reads as a number, and that a rule which may bend is
 * joined to the objective it is paid for in.
 */

const FIXTURE_PATH = (() => {
  const relative = "backend/tests/ir_fixtures.json";
  for (let dir = process.cwd(); ; dir = dirname(dir)) {
    const candidate = resolve(dir, relative);
    if (existsSync(candidate)) return candidate;
    if (dirname(dir) === dir) throw new Error(`${relative} was not found above ${process.cwd()}`);
  }
})();

const WORKFORCE = (
  JSON.parse(readFileSync(FIXTURE_PATH, "utf-8")) as { valid: { name: string; ir: Record<string, unknown> }[] }
).valid.find((fixture) => fixture.name === "workforce")!.ir;

const type = (id: number, name: string, colour: string | null = null): EntityType => ({
  id,
  domain_id: 1,
  name,
  role: "other",
  colour,
  icon: null,
  updated_at: "2026-09-22T00:00:00+00:00",
  attributes: [],
});

const TYPES = [type(1, "employee", "#2563eb"), type(2, "unit"), type(3, "day"), type(4, "shift")];
const { graph, palette } = buildModelView(WORKFORCE, TYPES);
const edge = (source: string, target: string) =>
  graph.edges.find((candidate) => candidate.source === source && candidate.target === target);

describe("buildModelView on the workforce model", () => {
  it("draws every part of the model, grouped by what it is", () => {
    const byPart = Object.fromEntries(
      MODEL_PARTS.map((part) => [part, graph.nodes.filter((node) => node.type === part).map((node) => node.id)])
    );
    expect(byPart).toEqual({
      // A set that is an entity type keeps that type's node id, so selecting
      // it opens the same panel the ERD does.
      sets: ["type-1", "type-2", "type-3", "type-4"],
      variables: ["model-var-assign"],
      parameters: ["model-par-demand"],
      rules: [
        "model-con-c_cover_demand",
        "model-con-c_one_shift_per_day",
        "model-con-c_max_hours",
        "model-con-c_north_region_lates",
      ],
      objective: [OBJECTIVE_NODE_ID],
    });
    expect(graph.entity_types.map((option) => option.name)).toEqual([...MODEL_PARTS]);
  });

  it("joins each set to what it indexes", () => {
    for (const set of ["type-1", "type-3", "type-4"]) {
      expect(edge(set, "model-var-assign")).toBeDefined();
    }
    expect(edge("type-3", "model-par-demand")).toBeDefined();
    expect(edge("type-4", "model-par-demand")).toBeDefined();
    // `unit` does not index assign.
    expect(edge("type-2", "model-var-assign")).toBeUndefined();
  });

  it("joins each rule to the variables and parameters it reads", () => {
    expect(edge("model-var-assign", "model-con-c_cover_demand")).toBeDefined();
    expect(edge("model-par-demand", "model-con-c_cover_demand")).toBeDefined();
    // The hours rule reads no parameter.
    expect(edge("model-par-demand", "model-con-c_max_hours")).toBeUndefined();
  });

  it("joins a rule to the sets it holds for every one of", () => {
    expect(edge("type-3", "model-con-c_cover_demand")).toBeDefined();
    expect(edge("type-4", "model-con-c_cover_demand")).toBeDefined();
    expect(edge("type-1", "model-con-c_cover_demand")).toBeUndefined();
  });

  it("names an attribute a rule reads as a number on the line from its set", () => {
    // `hours_per_week` flowing into the hours rule is what this view is for.
    expect(edge("type-1", "model-con-c_max_hours")?.label).toBe("hours_per_week");
  });

  it("marks a rule that may bend, and joins it to the objective it is paid in", () => {
    expect(palette.nodeData?.["model-con-c_north_region_lates"]?.soft).toBe("yes");
    expect(palette.nodeData?.["model-con-c_max_hours"]?.soft).toBe("no");
    expect(edge("model-con-c_north_region_lates", OBJECTIVE_NODE_ID)?.label).toBe("penalty");
    expect(edge("model-con-c_max_hours", OBJECTIVE_NODE_ID)).toBeUndefined();
  });

  it("joins the objective to what it adds up", () => {
    expect(edge("model-var-assign", OBJECTIVE_NODE_ID)).toBeDefined();
    expect(graph.nodes.find((node) => node.id === OBJECTIVE_NODE_ID)?.label).toBe("minimize\n1 term");
  });

  it("writes each part out for the side panel", () => {
    const rule = modelDetails(graph.nodes.find((node) => node.id === "model-con-c_cover_demand"));
    expect(rule).toContainEqual(["Kind", "Rule that must hold (hard)"]);
    expect(rule?.find(([label]) => label === "Rule")?.[1]).toMatch(/≥ demand\[d, s\]/);
    expect(rule?.find(([label]) => label === "For every")?.[1]).toBe("d in day, s in shift");

    const variable = modelDetails(graph.nodes.find((node) => node.id === "model-var-assign"));
    expect(variable).toContainEqual(["Domain", "binary"]);
    expect(variable).toContainEqual(["Values", "0 or 1"]);

    const soft = modelDetails(graph.nodes.find((node) => node.id === "model-con-c_north_region_lates"));
    expect(soft).toContainEqual(["Price per unit broken", "4"]);
  });

  it("colours a set from its entity type, as the ERD does", () => {
    expect(palette.nodeFill["type-1"]).toBe("#2563eb");
  });
});

describe("buildModelView on models that are not tidy", () => {
  it("draws a rule published before the IR contract, and says it has no expression", () => {
    const { graph: built } = buildModelView(
      { sets: [], parameters: {}, variables: {}, constraints: [{ id: "c_old", note: "never expressed" }] },
      []
    );
    const details = modelDetails(built.nodes.find((node) => node.id === "model-con-c_old"));
    expect(details?.find(([label]) => label === "Rule")?.[1]).toMatch(/no expression/);
    expect(details).toContainEqual(["Note", "never expressed"]);
  });

  it("draws a set that names no entity type, rather than dropping it", () => {
    const { graph: built } = buildModelView({ sets: ["ghost"], parameters: {}, variables: {}, constraints: [] }, []);
    expect(built.nodes.map((node) => node.id)).toEqual(["model-set-ghost"]);
  });

  it("drops a line to a variable the model never declared, rather than breaking the canvas", () => {
    const { graph: built } = buildModelView(
      {
        sets: [],
        parameters: {},
        variables: {},
        constraints: [
          { id: "c", left: { var: "nowhere", index: [] }, relation: "<=", right: { const: 1 }, severity: "hard" },
        ],
      },
      []
    );
    expect(built.edges).toEqual([]);
  });

  it("says when the goal is quadratic", () => {
    const { graph: built } = buildModelView(
      {
        sets: [],
        parameters: {},
        variables: { x: { index: [], domain: "continuous", lower: 0, upper: 1 } },
        constraints: [],
        objective: {
          sense: "minimize",
          terms: [{ id: "o", weight: 1, expression: { mul: [{ var: "x", index: [] }, { var: "x", index: [] }] } }],
        },
      },
      []
    );
    const objective = built.nodes.find((node) => node.id === OBJECTIVE_NODE_ID);
    expect(objective?.label).toBe("minimize\n1 term · quadratic");
    expect(modelDetails(objective)).toContainEqual(["Kind", "Objective (quadratic)"]);
  });

  it("says when a rule is quadratic", () => {
    const x = { var: "x", index: [] };
    const { graph: built } = buildModelView(
      {
        sets: [],
        parameters: {},
        variables: { x: { index: [], domain: "continuous", lower: 0, upper: 5 } },
        constraints: [{ id: "c_disc", left: { mul: [x, x] }, relation: "<=", right: { const: 25 }, severity: "hard" }],
      },
      []
    );
    const rule = built.nodes.find((node) => node.id === "model-con-c_disc");
    expect(rule?.label).toBe("c_disc" + "\n" + "must hold · quadratic");
    expect(modelDetails(rule)).toContainEqual(["Kind", "Rule that must hold (hard), quadratic"]);
  });

  it("is empty, not broken, with no model at all", () => {
    const { graph: built } = buildModelView(null, []);
    expect(built.nodes).toEqual([]);
    expect(built.edges).toEqual([]);
  });
});
