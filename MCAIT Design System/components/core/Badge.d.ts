/** Small status chip. Use to label states, categories, counts, or file types. Never use for interactive actions — use Button. */
export interface BadgeProps {
  children: React.ReactNode;
  /** Color treatment */
  variant?: 'default' | 'primary' | 'success' | 'warning' | 'danger' | 'info' | 'gold' | 'solid';
  /** Prepends a small colored dot — good for live status */
  dot?: boolean;
  /** Size */
  size?: 'md' | 'sm';
  style?: React.CSSProperties;
}
