import { existsSync, readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { AGENT_STATES, COMPONENT_STATES, COMPONENT_TYPES, EVENTS, PROTOCOL_VERSION } from "./types";
import { validateEvent } from "./validation";

const PROTOCOL_PATH = (() => {
  const relative = "backend/app/genui/protocol.json";
  for (let dir = process.cwd(); ; dir = dirname(dir)) {
    const candidate = resolve(dir, relative);
    if (existsSync(candidate)) return candidate;
    if (dirname(dir) === dir) throw new Error(`${relative} was not found above ${process.cwd()}`);
  }
})();

describe("the GenUI protocol", () => {
  it("is the same in TypeScript and in the JSON the server reads", () => {
    const raw = JSON.parse(readFileSync(PROTOCOL_PATH, "utf8")) as Record<string, unknown>;
    const json = Object.fromEntries(Object.entries(raw).filter(([key]) => !key.startsWith("//")));
    expect({
      version: PROTOCOL_VERSION,
      componentTypes: [...COMPONENT_TYPES],
      componentStates: [...COMPONENT_STATES],
      agentStates: [...AGENT_STATES],
      events: [...EVENTS],
    }).toEqual(json);
  });

  it("lets the protocol's events through and names what it refuses", () => {
    expect(validateEvent({ event: "agent.state", state: "solving" }).ok).toBe(true);
    expect(
      validateEvent({ event: "component.created", component: { id: "run-1-model", type: "model-summary", state: "skeleton" } }).ok
    ).toBe(true);
    expect(validateEvent({ event: "component.data", id: "run-1-model", data: { variables: 3 } }).ok).toBe(true);
    const refused: [unknown, string][] = [
      [{ event: "agent.state", state: "dreaming" }, 'unknown agent state "dreaming"'],
      [{ event: "component.created", component: { id: "x", type: "script", state: "skeleton" } }, 'unknown component type "script"'],
      [{ event: "component.created", component: { id: "<img>", type: "metric", state: "skeleton" } }, "a component needs an id"],
      [{ event: "component.data", id: "x", data: "html" }, "data is an object"],
      [{ event: "render.html", html: "<b>" }, 'unknown event "render.html"'],
    ];
    for (const [event, reason] of refused) expect(validateEvent(event)).toEqual({ ok: false, reason });
  });
});
