import React from 'react';

export interface SidebarItem {
  /** Stable id passed to onNavigate + compared against `active` */
  id: string;
  /** Visible label (hidden when collapsed) */
  label: string;
  /** Icon key: folder, users, clock, star, trash */
  icon: string;
}

export interface SidebarVolume {
  id: string;
  /** Volume name, e.g. "My Drive" */
  name: string;
  /** Icon key. Default folder. */
  icon?: string;
  /** Small mono tag on the right, e.g. "default" */
  badge?: string;
  /** Usage meter fill 0–100. Omit to hide the meter. */
  pct?: number;
  /** Usage caption under the meter, e.g. "368.9 KB used" */
  usage?: string;
}

/**
 * Sidebar — collapsible product navigation rail. Shows an optional featured
 * "volume" card (name · badge · usage meter) above a list of nav items, with a
 * collapse/expand toggle pinned to the bottom. Collapses to a 64px icon rail.
 * Rounds its top-right corner by default so it tucks under the AppBar.
 * Controlled (pass `collapsed` + `onToggle`) or uncontrolled (`defaultCollapsed`).
 * @startingPoint section="Components" subtitle="Collapsible product nav rail — volume card · items · toggle" viewport="320x560"
 */
export function Sidebar(props: {
  /** Nav items below the volume card */
  items?: SidebarItem[];
  /** Currently active item/volume id */
  active?: string;
  /** Called with an item/volume id on click */
  onNavigate?: (id: string) => void;
  /** Featured volume card at the top. Omit to hide. */
  volume?: SidebarVolume;
  /** Eyebrow label above the volume card. Default "Volumes". */
  label?: string;
  /** Controlled collapsed state */
  collapsed?: boolean;
  /** Initial collapsed state when uncontrolled. Default false. */
  defaultCollapsed?: boolean;
  /** Fired with the next collapsed value when the toggle is clicked */
  onToggle?: (collapsed: boolean) => void;
  /** Which corner(s) to round. Default "top-right". */
  roundedCorner?: 'top-right' | 'top-left' | 'right' | 'none';
  style?: React.CSSProperties;
}): React.ReactElement;
