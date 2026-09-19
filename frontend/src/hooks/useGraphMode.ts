import { useSyncExternalStore } from "react";
import type { GraphMode } from "../lib/typesGraph";

/**
 * Which view the graph page draws: the domain's **objects** (entities and
 * relationships, the default) or its **types** (the schema).
 *
 * Persisted in `localStorage` and shared through a small external store --
 * the same approach, and the same failure handling, as `useDomain`. It
 * matters for the same reason: the choice is a working context, and losing
 * it on every reload would make the toggle feel like a demo switch rather
 * than a setting.
 *
 * The URL is the *other* half, and `GraphDemo` owns it: `?mode=types` makes
 * a view linkable, and a link wins over the stored choice on arrival. This
 * module deliberately knows nothing about that -- a hook that read the URL
 * would need a router context and could not be the plain store the
 * selector and the page both share.
 */
export const GRAPH_MODE_STORAGE_KEY = "solver_graph_mode";

const DEFAULT_MODE: GraphMode = "objects";

type Listener = () => void;
const listeners = new Set<Listener>();

// Fallback for when localStorage throws (private mode, blocked storage):
// the choice then lasts for the page's lifetime instead of not at all.
let memoryValue: GraphMode = DEFAULT_MODE;
let storageBroken = false;

/** Anything that is not one of the two known modes reads as the default --
 * a stored value can outlive the code that wrote it. */
export function parseGraphMode(raw: string | null): GraphMode {
  return raw === "types" || raw === "objects" ? raw : DEFAULT_MODE;
}

function read(): GraphMode {
  if (storageBroken) return memoryValue;
  try {
    return parseGraphMode(localStorage.getItem(GRAPH_MODE_STORAGE_KEY));
  } catch {
    storageBroken = true;
    return memoryValue;
  }
}

function write(mode: GraphMode) {
  memoryValue = mode;
  try {
    localStorage.setItem(GRAPH_MODE_STORAGE_KEY, mode);
  } catch {
    storageBroken = true;
  }
  listeners.forEach((listener) => listener());
}

function subscribe(listener: Listener): () => void {
  listeners.add(listener);
  function onStorage(event: StorageEvent) {
    if (event.key === GRAPH_MODE_STORAGE_KEY || event.key === null) listener();
  }
  window.addEventListener("storage", onStorage);
  return () => {
    listeners.delete(listener);
    window.removeEventListener("storage", onStorage);
  };
}

export function useGraphMode(): { mode: GraphMode; setMode: (mode: GraphMode) => void } {
  // The server snapshot is the default rather than a read: there is no
  // localStorage during SSR, and guessing "types" there would flash the
  // wrong canvas.
  const mode = useSyncExternalStore(subscribe, read, () => DEFAULT_MODE);
  return { mode, setMode: write };
}
