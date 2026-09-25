import React from 'react';

export interface MCAITApp {
  id: string;
  name: string;
  /** Icon key (folder, calendar, video, sparkle, mail, notebook, globe, …) */
  icon: string;
  /** Tile background (CSS color / token) */
  color: string;
  /** Glyph color on the tile — defaults to white */
  iconColor?: string;
}

export interface MCAITUser {
  name: string;
  email: string;
}

/**
 * MCAITWidget — the shared identity cluster that anchors the right edge of
 * every MCAIT product app bar: the M8 seal, the Cowork assistant, the suite
 * app-switcher grid, and the account menu. This is the constant signature of
 * MCAIT inside each belonging product.
 * @startingPoint section="Components" subtitle="MCAIT identity cluster — seal · Cowork · apps · account" viewport="380x120"
 */
export function MCAITWidget(props: {
  /** Suite apps shown in the switcher grid. Defaults to the full MCAIT suite. */
  apps?: MCAITApp[];
  /** Id of the current product (highlighted in the grid) */
  activeApp?: string;
  /** Signed-in user */
  user?: MCAITUser;
  /** Called with an app id when a suite tile is clicked */
  onNavigate?: (appId: string) => void;
  /** Show the gold M8 seal at the start of the cluster. Default true. */
  showSeal?: boolean;
}): React.ReactElement;

/**
 * AppBar — the standard MCAIT product top bar. A branded product mark on the
 * left, an optional center slot for search/controls, and the shared
 * MCAITWidget identity cluster pinned to the right. Wrap with the product's
 * accent by passing the matching product id.
 * @startingPoint section="Components" subtitle="Product top bar with the MCAIT identity widget" viewport="1180x180"
 */
export function AppBar(props: {
  /** Current product — drives the left mark + accent. id one of cowork/drive/calendar/meet/notebook/mail/aura */
  product?: { id: string; name: string; icon?: string };
  /** Center content — typically a search field and view controls */
  children?: React.ReactNode;
  /** Signed-in user passed through to the identity widget */
  user?: MCAITUser;
  /** App-switch handler */
  onNavigate?: (appId: string) => void;
  /** Draw the bottom hairline. Set false for the inset-panel shell where the
   *  content area supplies its own top/left border + rounded corner. Default true. */
  divider?: boolean;
  style?: React.CSSProperties;
}): React.ReactElement;

/** The MCAIT "Mc 8" gold monogram seal. */
export function Seal(props: { size?: number; radius?: number }): React.ReactElement;

/** The canonical MCAIT product suite list. */
export const MCAIT_APPS: MCAITApp[];
