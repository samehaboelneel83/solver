/**
 * The role x page matrix (Epic UX, U-1): for each seeded role, every destination in the
 * registry and a deep link into each, the menu and the page agree -- a page the menu hides
 * says it cannot be opened, and a page the menu shows opens.
 */
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { DESTINATIONS, buildNavGroups } from "./registry";
import { ROLE_CAPABILITIES, accessFor, mayOpen } from "./access";

const held = { current: new Set<string>(), known: true };
vi.mock("../hooks/useCapability", () => ({
  useCapabilities: () => ({ can: (c: string) => held.current.has(c), known: held.known, username: "u" }),
}));

import CapabilityGate from "../components/CapabilityGate";

/** Every destination's own path with ids filled in, and a deep link one level below it. */
function linksOf(path: string): string[] {
  const filled = path.replace(":domainId", "3").replace(":problemId", "7");
  return [filled, `${filled.replace(/\/$/, "")}/42`];
}

function open(path: string) {
  render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route element={<CapabilityGate />}>
          <Route path="*" element={<p>the page</p>} />
        </Route>
      </Routes>
    </MemoryRouter>
  );
}

const ROLES = Object.keys(ROLE_CAPABILITIES);
const CASES = ROLES.flatMap((role) =>
  DESTINATIONS.flatMap((d) => [d.path, d.canonical].filter((p, i, all) => all.indexOf(p) === i)
    .flatMap((p) => linksOf(p).map((link) => ({ role, id: d.id, link, capability: d.capability }))))
);

describe("the role x page matrix", () => {
  beforeEach(() => {
    held.known = true;
  });

  it.each(CASES)("$role opening $link ($id)", ({ role, link, capability }) => {
    held.current = new Set(ROLE_CAPABILITIES[role]);
    const allowed = !capability || held.current.has(capability);
    open(link);
    if (allowed) {
      expect(screen.getByText("the page")).toBeInTheDocument();
    } else {
      expect(screen.queryByText("the page")).not.toBeInTheDocument();
      expect(screen.getByRole("alert")).toHaveTextContent(capability as string);
    }
  });

  it.each(ROLES)("the menu shows %s exactly the pages it may open", (role) => {
    const can = (c: string) => ROLE_CAPABILITIES[role].includes(c);
    for (const group of buildNavGroups({ domainId: 3, problemId: 7 })) {
      for (const item of group.items) {
        const shown = !item.capability || can(item.capability);
        expect(mayOpen(item.to.split("?")[0], can), `${role}: ${item.to}`).toBe(shown);
      }
    }
  });

  it("every capability a destination asks for is held by some role, and admin opens everything", () => {
    const granted = new Set(Object.values(ROLE_CAPABILITIES).flat());
    for (const d of DESTINATIONS) if (d.capability) expect(granted.has(d.capability), d.id).toBe(true);
    for (const d of DESTINATIONS) expect(mayOpen(d.path, (c) => ROLE_CAPABILITIES.admin.includes(c)), d.id).toBe(true);
  });

  it("a deep link below a gated page is gated the same way", () => {
    expect(accessFor("/iam/role/5").capability).toBe("iam.manage");
    expect(accessFor("/domains/3/data/sources").capability).toBe("integration.run");
    expect(accessFor("/domains/3/problems/7/runs/9").capability).toBeUndefined();
  });

  it("renders the page while the account's permissions are still loading", () => {
    held.current = new Set();
    held.known = false;
    open("/settings");
    expect(screen.getByText("the page")).toBeInTheDocument();
  });
});
