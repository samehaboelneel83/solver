import { useSyncExternalStore } from "react";

/**
 * The domain everything domain-scoped is shown for (entity types, entities,
 * relationship types, parameters, problems). Persisted in `localStorage`
 * so it survives a reload, and shared by every component that calls
 * `useDomain()` -- the selector in the sidebar writes it, pages read it --
 * without a provider, through a small external store.
 *
 * This hook only stores the choice; it does not know which domains exist.
 * `DomainSelector` owns validating it against the real list (see
 * `resolveDomainId`), which is why a page can briefly see a stale id on a
 * cold load before the list arrives: treat `domainId` as a scope to query
 * with, not as proof the domain exists.
 */
export const DOMAIN_STORAGE_KEY = "solver_domain_id";

type Listener = () => void;
const listeners = new Set<Listener>();

// Fallback for when localStorage throws (private mode, blocked storage):
// the choice then lasts for the page's lifetime instead of not at all.
let memoryValue: number | null = null;
let storageBroken = false;

/** A positive integer written in plain decimal, or null. Rejects "1.5",
 * "1e3", " 4", "0" and "-3" -- anything a real bigint id would not be. */
function parseId(raw: string | null): number | null {
  if (raw === null || !/^[1-9][0-9]*$/.test(raw)) return null;
  const id = Number(raw);
  return Number.isSafeInteger(id) ? id : null;
}

function read(): number | null {
  if (storageBroken) return memoryValue;
  try {
    return parseId(localStorage.getItem(DOMAIN_STORAGE_KEY));
  } catch {
    storageBroken = true;
    return memoryValue;
  }
}

function write(id: number | null) {
  memoryValue = id;
  try {
    if (id === null) {
      localStorage.removeItem(DOMAIN_STORAGE_KEY);
    } else {
      localStorage.setItem(DOMAIN_STORAGE_KEY, String(id));
    }
  } catch {
    storageBroken = true;
  }
  listeners.forEach((listener) => listener());
}

function subscribe(listener: Listener): () => void {
  listeners.add(listener);
  // Another tab changed it (or cleared storage entirely: key === null).
  function onStorage(event: StorageEvent) {
    if (event.key === DOMAIN_STORAGE_KEY || event.key === null) listener();
  }
  window.addEventListener("storage", onStorage);
  return () => {
    listeners.delete(listener);
    window.removeEventListener("storage", onStorage);
  };
}

export function useDomain(): { domainId: number | null; setDomainId: (id: number | null) => void } {
  const domainId = useSyncExternalStore(subscribe, read, () => null);
  return { domainId, setDomainId: write };
}

/**
 * Which domain to show, given the stored choice and the domains that
 * actually exist: the stored one if it is still there, otherwise the
 * *first one listed* (the selector's own order -- not the lowest id), or
 * null when there are none.
 */
export function resolveDomainId(stored: number | null, domains: readonly { id: number }[]): number | null {
  if (domains.length === 0) return null;
  if (stored !== null && domains.some((domain) => domain.id === stored)) return stored;
  return domains[0].id;
}
