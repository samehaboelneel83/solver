/** Horizontal tab row. Use for switching between views within a page section — not for top-level app navigation. */
export interface TabsProps {
  /** Array of tab label strings */
  tabs: string[];
  /** Index of the active tab */
  activeIndex?: number;
  onChange?: (index: number) => void;
  style?: React.CSSProperties;
}
