/**
 * One component from the store, rendered through the registry.
 *
 * The outer `motion.div` keeps the component's identity (`layoutId` = its
 * id) for its whole life: a skeleton becoming content is a crossfade inside
 * a box that grows by a layout spring, never a swap of one element for
 * another; and the compact card in the conversation and the expanded one in
 * the workspace share the same `layoutId`, so opening one is the same box
 * moving and growing -- only one of the two is ever mounted.
 */
import { AnimatePresence, motion } from "framer-motion";
import { memo } from "react";
import { crossfade, enter, layoutSpring } from "../animation/variants";
import type { Variant } from "../components/shared";
import { entryFor } from "../registry/componentRegistry";
import { useGenUIComponent, type GenUIStore } from "./store";

export const GenUIComponent = memo(function GenUIComponent({
  store,
  id,
  variant,
  onExpand,
}: {
  store: GenUIStore;
  id: string;
  variant: Variant;
  onExpand?: (id: string) => void;
}) {
  const record = useGenUIComponent(store, id);
  if (!record) return null;
  const entry = entryFor(record.type);
  const loading = record.state === "skeleton" || (record.state === "hydrating" && Object.keys(record.data).length === 0);
  const Body = entry ? (loading ? entry.skeleton : entry.component) : null;
  const opens = variant === "compact" && entry?.expandable && onExpand && !loading;

  const content = Body ? (
    <Body record={record} variant={variant} />
  ) : (
    <p className="rounded border border-dashed border-slate-300 p-3 text-xs text-slate-500">
      A “{record.type}” component is not available in this version of the interface.
    </p>
  );

  return (
    <motion.div
      layout
      layoutId={id}
      variants={enter}
      initial="initial"
      animate="animate"
      exit="exit"
      transition={layoutSpring}
      data-genui-id={id}
      data-genui-state={record.state}
      className={variant === "expanded" ? "w-full" : undefined}
    >
      <AnimatePresence mode="popLayout" initial={false}>
        <motion.div key={loading ? "skeleton" : "content"} variants={crossfade} initial="initial" animate="animate" exit="exit">
          {opens ? (
            <button
              type="button"
              className="block w-full rounded-lg text-left focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
              onClick={() => onExpand!(id)}
              aria-label={`Open ${String(record.props.title ?? record.type)} in the workspace`}
            >
              {content}
            </button>
          ) : (
            content
          )}
        </motion.div>
      </AnimatePresence>
    </motion.div>
  );
});
