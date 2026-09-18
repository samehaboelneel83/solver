import { createContext, createElement, useCallback, useContext, useEffect, useMemo, useRef, type ReactNode } from "react";

type ConfirmLeaveFn = () => boolean;

type UnsavedChangesContextValue = {
  /** Ask the currently-registered guard (if any) whether it's OK to leave. */
  confirmLeave: ConfirmLeaveFn;
  /** Register/unregister the active guard. `null` clears it. */
  registerGuard: (fn: ConfirmLeaveFn | null) => void;
};

// Outside any <UnsavedChangesProvider> (e.g. a component test that mounts a
// form in isolation), navigation is simply never blocked -- consistent with
// how ToastProvider degrades to a no-op outside its own provider.
const noopContextValue: UnsavedChangesContextValue = {
  confirmLeave: () => true,
  registerGuard: () => {},
};

const UnsavedChangesContext = createContext<UnsavedChangesContextValue>(noopContextValue);

/**
 * Mount once, high enough in the tree to wrap both the navigation chrome
 * (AppShell's sidebar links) and the routed page beneath it (the form that
 * calls `useUnsavedChangesGuard`) -- AppShell wraps its whole subtree via
 * `<Outlet />`, so mounting it there covers both (C-3).
 *
 * A `.ts` file can't use JSX, so the provider element is built with
 * `createElement` directly.
 */
export function UnsavedChangesProvider({ children }: { children: ReactNode }) {
  const guardRef = useRef<ConfirmLeaveFn | null>(null);

  const registerGuard = useCallback((fn: ConfirmLeaveFn | null) => {
    guardRef.current = fn;
  }, []);

  const confirmLeave = useCallback<ConfirmLeaveFn>(() => (guardRef.current ? guardRef.current() : true), []);

  const value = useMemo(() => ({ confirmLeave, registerGuard }), [confirmLeave, registerGuard]);

  return createElement(UnsavedChangesContext.Provider, { value }, children);
}

/**
 * For an in-app navigation control (a sidebar `NavLink`, a form's Cancel or
 * breadcrumb link): call this in the click handler and skip navigating
 * (`event.preventDefault()`) when it returns false.
 */
export function useConfirmLeave(): ConfirmLeaveFn {
  return useContext(UnsavedChangesContext).confirmLeave;
}

const DEFAULT_MESSAGE = "You have unsaved changes. Leave without saving?";

/**
 * Call from a form with whether it currently has unsaved edits (C-3).
 * While `isDirty` is true this:
 *  - registers a guard with the nearest `UnsavedChangesProvider` so
 *    `useConfirmLeave()` callers (AppShell's nav links, this page's own
 *    Cancel/breadcrumb link) show a `window.confirm` prompt before
 *    navigating away, and
 *  - adds a `beforeunload` listener so closing the tab or a hard reload
 *    also warns.
 *
 * IMPORTANT: neither of these intercepts the browser's own Back/Forward
 * buttons. Doing that needs React Router's `useBlocker`, which only works
 * with a data router (`createBrowserRouter`); this app is built on the
 * plain `<BrowserRouter>`, which has no history-blocking hook. Migrating
 * routers is out of scope here, so Back still discards unsaved changes
 * silently -- only in-app link clicks and tab close/reload are covered.
 */
export function useUnsavedChangesGuard(isDirty: boolean, message: string = DEFAULT_MESSAGE): void {
  const { registerGuard } = useContext(UnsavedChangesContext);
  const isDirtyRef = useRef(isDirty);
  isDirtyRef.current = isDirty;

  useEffect(() => {
    function guard(): boolean {
      if (!isDirtyRef.current) return true;
      return window.confirm(message);
    }
    registerGuard(guard);
    return () => registerGuard(null);
  }, [registerGuard, message]);

  useEffect(() => {
    function handleBeforeUnload(event: BeforeUnloadEvent) {
      if (!isDirtyRef.current) return;
      event.preventDefault();
      // Chrome requires returnValue to be set for the native prompt to show.
      event.returnValue = "";
    }
    window.addEventListener("beforeunload", handleBeforeUnload);
    return () => window.removeEventListener("beforeunload", handleBeforeUnload);
  }, []);
}
