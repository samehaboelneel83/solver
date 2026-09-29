/**
 * Who may open which page (Epic UX, U-1).
 *
 * The same registry that hides a menu item decides whether its page opens, so a
 * link typed, bookmarked or pasted from an email lands on the same answer the
 * menu gave: the page, or a plain "this account may not open it". The server
 * still enforces every read and write; this only stops a page from rendering
 * as a string of 403s.
 */
import { DESTINATIONS, destinationForPath, type Destination } from "./registry";

/** The seeded roles and what each is granted (migrations 0013, 0014, 0085). */
export const ROLE_CAPABILITIES: Record<string, string[]> = {
  admin: ["domain.edit", "model.publish", "run.submit", "solver.configure", "iam.manage", "settings.edit",
    "integration.manage", "integration.run"],
  modeller: ["domain.edit", "model.publish", "run.submit", "solver.configure", "settings.edit"],
  planner: ["run.submit"],
  viewer: [],
};

/** The destination a path belongs to and the capability it needs, if any. */
export function accessFor(pathname: string): { destination: Destination | undefined; capability: string | undefined } {
  // A plain canonical path or an old alias (`/templates/42`) belongs to its destination too,
  // or a page the menu calls by another name would open to anyone.
  let aliased: Destination | undefined;
  let longest = 0;
  for (const d of DESTINATIONS) {
    for (const p of [d.canonical, ...(d.aliases ?? [])]) {
      if (p.includes(":") || p === "/") continue;
      if ((pathname === p || pathname.startsWith(`${p}/`)) && p.length > longest) {
        aliased = d;
        longest = p.length;
      }
    }
  }
  const destination = aliased?.capability ? aliased : destinationForPath(pathname) ?? aliased;
  return { destination, capability: destination?.capability };
}

/** Whether `can` opens `pathname`. */
export function mayOpen(pathname: string, can: (capability: string) => boolean): boolean {
  const { capability } = accessFor(pathname);
  return !capability || can(capability);
}
