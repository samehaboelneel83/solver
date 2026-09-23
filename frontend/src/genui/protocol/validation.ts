/**
 * The gate between a stream and the renderer: an event that is not the
 * protocol's is dropped, with the reason, rather than rendered.
 */
import { AGENT_STATES, COMPONENT_STATES, COMPONENT_TYPES, EVENTS, type GenUIEvent } from "./types";

const has = (list: readonly string[], value: unknown): boolean => typeof value === "string" && list.includes(value);
const isObject = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);
const isId = (value: unknown): value is string => typeof value === "string" && /^[A-Za-z0-9_.:-]{1,120}$/.test(value);

export type Checked = { ok: true; event: GenUIEvent } | { ok: false; reason: string };

export function validateEvent(raw: unknown): Checked {
  if (!isObject(raw)) return { ok: false, reason: "an event is an object" };
  const name = raw.event;
  if (!has(EVENTS, name)) return { ok: false, reason: `unknown event ${JSON.stringify(name)}` };
  switch (name) {
    case "agent.state":
      return has(AGENT_STATES, raw.state)
        ? { ok: true, event: raw as GenUIEvent }
        : { ok: false, reason: `unknown agent state ${JSON.stringify(raw.state)}` };
    case "agent.message":
      return typeof raw.text === "string" && raw.text.length <= 2000
        ? { ok: true, event: raw as GenUIEvent }
        : { ok: false, reason: "a message is text of at most 2000 characters" };
    case "component.created": {
      const component = raw.component;
      if (!isObject(component) || !isId(component.id)) return { ok: false, reason: "a component needs an id" };
      if (!has(COMPONENT_TYPES, component.type)) {
        return { ok: false, reason: `unknown component type ${JSON.stringify(component.type)}` };
      }
      if (!has(COMPONENT_STATES, component.state)) {
        return { ok: false, reason: `unknown component state ${JSON.stringify(component.state)}` };
      }
      if (component.props !== undefined && !isObject(component.props)) return { ok: false, reason: "props is an object" };
      return { ok: true, event: raw as GenUIEvent };
    }
    default:
      if (!isId(raw.id)) return { ok: false, reason: `${String(name)} needs the id of a component` };
      if (name === "component.updated" && !has(COMPONENT_STATES, raw.state)) {
        return { ok: false, reason: `unknown component state ${JSON.stringify(raw.state)}` };
      }
      if (name === "component.data" && !isObject(raw.data)) return { ok: false, reason: "data is an object" };
      return { ok: true, event: raw as GenUIEvent };
  }
}
