// @types/react 18.3.x doesn't type the `inert` HTML attribute (it was added
// to React's own types upstream alongside React 19); the DOM attribute
// itself has been supported in every evergreen browser since 2022, and
// AppShell.tsx uses it (G-2 fix round 1) to remove the off-canvas drawer's
// contents from the tab order and the accessibility tree while it's closed.
// Passed as a string (`""` / `undefined`) rather than a boolean because
// React 18 doesn't recognize `inert` as one of its known boolean HTML
// attributes and drops a literal `true` instead of rendering it.
//
// Typed as `"" | undefined` rather than a general `string` (fix round 2):
// `inert` is a boolean HTML attribute, so `inert="false"` still *activates*
// it -- a plain `string` type would let that typecheck while doing the
// opposite of what it says. This also means the eventual `@types/react` 19
// upgrade (which declares `inert?: boolean`) won't collide with this
// module augmentation as a TS2717 duplicate/incompatible property error;
// this file can simply be deleted once that upgrade happens.
import "react";

declare module "react" {
  // The parameter must be named `T` to merge with @types/react. `_T`
  // looks unused-friendly and replaces the interface instead, so
  // `children` and the rest of HTMLAttributes vanish.
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  interface HTMLAttributes<T> {
    inert?: "" | undefined;
  }
}
