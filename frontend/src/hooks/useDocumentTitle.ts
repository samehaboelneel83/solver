import { useEffect } from "react";

/**
 * Sets `document.title` while the calling component is mounted, restoring the previous
 * title on unmount. Every route should call this with its own page name so the browser
 * tab/history and screen readers can distinguish routes (H-10).
 */
export function useDocumentTitle(title: string) {
  useEffect(() => {
    const previous = document.title;
    document.title = `${title} · Problem Solver`;
    return () => {
      document.title = previous;
    };
  }, [title]);
}
