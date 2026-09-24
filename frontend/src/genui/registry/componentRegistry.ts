/**
 * The only way an agent's intent becomes something on screen: a component
 * type names an entry here. Adding a component is adding an entry; the
 * renderer and the stream do not change. A type the protocol has and this
 * build does not yet render shows as a plain notice, never as nothing.
 */
import type { ComponentType as FC } from "react";
import type { ComponentType } from "../protocol/types";
import type { GenUIProps } from "../components/shared";
import {
  MetricCard,
  MetricSkeleton,
  ModelSummary,
  ModelSummarySkeleton,
  OptimizationSummary,
  OptimizationSummarySkeleton,
  SolverLog,
  SolverLogSkeleton,
  SolverProgress,
  SolverProgressSkeleton,
  SolverStatus,
  SolverStatusSkeleton,
  Timeline,
  TimelineSkeleton,
} from "../components/cards";
import SpatialMap, { SpatialMapSkeleton } from "../components/SpatialMap";

export type RegistryEntry = {
  component: FC<GenUIProps>;
  skeleton: FC<GenUIProps>;
  /** Whether a card of this kind opens into the workspace when clicked. */
  expandable: boolean;
  /** How wide it sits in the conversation: a metric sits beside others. */
  inline?: boolean;
};

export const componentRegistry: Partial<Record<ComponentType, RegistryEntry>> = {
  metric: { component: MetricCard, skeleton: MetricSkeleton, expandable: false, inline: true },
  "optimization-summary": { component: OptimizationSummary, skeleton: OptimizationSummarySkeleton, expandable: true },
  "solver-status": { component: SolverStatus, skeleton: SolverStatusSkeleton, expandable: false },
  "solver-progress": { component: SolverProgress, skeleton: SolverProgressSkeleton, expandable: true },
  "model-summary": { component: ModelSummary, skeleton: ModelSummarySkeleton, expandable: true },
  timeline: { component: Timeline, skeleton: TimelineSkeleton, expandable: false },
  "solver-log": { component: SolverLog, skeleton: SolverLogSkeleton, expandable: true },
  "spatial-map": { component: SpatialMap, skeleton: SpatialMapSkeleton, expandable: true },
};

export function entryFor(type: ComponentType): RegistryEntry | undefined {
  return componentRegistry[type];
}
