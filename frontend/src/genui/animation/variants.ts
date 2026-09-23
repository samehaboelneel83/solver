/**
 * The GenUI motion vocabulary: one spring for layout (a card growing as it
 * hydrates, a card expanding into the workspace), one fade for content.
 * Opacity and transform only -- never width, height, top or margin -- so
 * nothing here makes the browser lay the page out again on each frame.
 * `MotionConfig reducedMotion="user"` (the Workspace page) turns the
 * transforms off for anyone who asked for less motion.
 */
import type { Transition, Variants } from "framer-motion";

export const layoutSpring: Transition = { type: "spring", stiffness: 400, damping: 30 };

/** A component arriving: a slight grow from its own place. */
export const enter: Variants = {
  initial: { opacity: 0, scale: 0.96 },
  animate: { opacity: 1, scale: 1, transition: layoutSpring },
  exit: { opacity: 0, scale: 0.98, transition: { duration: 0.12 } },
};

/** Skeleton to content, inside a component that keeps its place. */
export const crossfade: Variants = {
  initial: { opacity: 0 },
  animate: { opacity: 1, transition: { duration: 0.18 } },
  exit: { opacity: 0, transition: { duration: 0.1 } },
};
