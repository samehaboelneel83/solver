// @types/react 18.3.x doesn't type the `inert` HTML attribute (it was added
// to React's own types upstream alongside React 19); the DOM attribute
// itself has been supported in every evergreen browser since 2022, and
// AppShell.tsx uses it (G-2 fix round 1) to remove the off-canvas drawer's
// contents from the tab order and the accessibility tree while it's closed.
// Passed as a string (`""` / `undefined`) rather than a boolean because
// React 18 doesn't recognize `inert` as one of its known boolean HTML
// attributes and drops a literal `true` instead of rendering it.
import "react";

declare module "react" {
  interface HTMLAttributes<T> {
    inert?: string;
  }
}
