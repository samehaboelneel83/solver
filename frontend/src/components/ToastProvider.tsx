import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";

type ToastType = "success" | "error";
type ToastItem = { id: number; message: string; type: ToastType };

type ToastContextValue = {
  success: (message: string) => void;
  error: (message: string) => void;
};

// A component that calls useToast() without a <ToastProvider> ancestor (e.g.
// a unit test that mounts just that component) gets working no-ops rather
// than a crash -- the whole point of D-1 is confirming success, never
// breaking the app when confirmation isn't wired up yet. In dev builds the
// no-op also warns, so a real component accidentally mounted outside the
// provider fails loudly during development instead of silently dropping
// every confirmation it tries to show.
function warnDropped() {
  if (import.meta.env.DEV) {
     
    console.warn("useToast() called outside ToastProvider; the message was dropped");
  }
}

const ToastContext = createContext<ToastContextValue>({
  success: warnDropped,
  error: warnDropped,
});

export function useToast(): ToastContextValue {
  return useContext(ToastContext);
}

const MAX_VISIBLE = 3;
const SUCCESS_TIMEOUT_MS = 4000;
const ERROR_TIMEOUT_MS = 8000;

let nextToastId = 0;

function ToastRow({ toast, onDismiss }: { toast: ToastItem; onDismiss: () => void }) {
  const isError = toast.type === "error";
  return (
    <div
      className={`pointer-events-auto flex max-w-sm items-start gap-2 rounded-md border px-3 py-2 text-sm shadow-md animate-toast-in ${
        isError ? "border-red-300 bg-red-50 text-red-700" : "border-slate-300 bg-white text-slate-900"
      }`}
    >
      <span className="whitespace-pre-line">{toast.message}</span>
      <button
        type="button"
        onClick={onDismiss}
        aria-label="Dismiss notification"
        className={`ml-auto shrink-0 text-xs ${isError ? "text-red-700" : "text-slate-500"} hover:opacity-70`}
      >
        ×
      </button>
    </div>
  );
}

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<ToastItem[]>([]);
  const timers = useRef(new Map<number, ReturnType<typeof setTimeout>>());

  const clearTimer = useCallback((id: number) => {
    const timer = timers.current.get(id);
    if (timer) {
      clearTimeout(timer);
      timers.current.delete(id);
    }
  }, []);

  const dismiss = useCallback(
    (id: number) => {
      clearTimer(id);
      setToasts((prev) => prev.filter((t) => t.id !== id));
    },
    [clearTimer]
  );

  const push = useCallback(
    (message: string, type: ToastType) => {
      const id = nextToastId++;
      setToasts((prev) => {
        const next = [...prev, { id, message, type }];
        // Cap visible toasts at MAX_VISIBLE: drop the oldest ones over the
        // limit (and their now-pointless pending timers) rather than let the
        // stack grow unbounded.
        while (next.length > MAX_VISIBLE) {
          const dropped = next.shift();
          if (dropped) {
            clearTimer(dropped.id);
          }
        }
        return next;
      });
      const timeoutMs = type === "error" ? ERROR_TIMEOUT_MS : SUCCESS_TIMEOUT_MS;
      timers.current.set(
        id,
        setTimeout(() => dismiss(id), timeoutMs)
      );
    },
    [clearTimer, dismiss]
  );

  const success = useCallback((message: string) => push(message, "success"), [push]);
  const error = useCallback((message: string) => push(message, "error"), [push]);

  useEffect(() => {
    const timersMap = timers.current;
    return () => {
      timersMap.forEach((timer) => clearTimeout(timer));
      timersMap.clear();
    };
  }, []);

  const successToasts = toasts.filter((t) => t.type === "success");
  const errorToasts = toasts.filter((t) => t.type === "error");

  return (
    <ToastContext.Provider value={{ success, error }}>
      {children}
      {/* Bottom-right stack. The container is `pointer-events-none` so it never
          blocks clicks on the page beneath it; each toast opts back in with
          `pointer-events-auto` so its dismiss button still works. */}
      <div className="pointer-events-none fixed bottom-4 right-4 z-50 flex flex-col-reverse items-end gap-2">
        {/* Both live regions are always mounted -- even with zero toasts inside --
            so screen readers are already watching them when a toast is appended.
            Mounting/unmounting the region itself (rather than its contents) is
            what makes an aria-live announcement unreliable. */}
        <div role="status" aria-live="polite" className="flex flex-col-reverse items-end gap-2">
          {successToasts.map((t) => (
            <ToastRow key={t.id} toast={t} onDismiss={() => dismiss(t.id)} />
          ))}
        </div>
        <div role="alert" aria-live="assertive" className="flex flex-col-reverse items-end gap-2">
          {errorToasts.map((t) => (
            <ToastRow key={t.id} toast={t} onDismiss={() => dismiss(t.id)} />
          ))}
        </div>
      </div>
    </ToastContext.Provider>
  );
}
