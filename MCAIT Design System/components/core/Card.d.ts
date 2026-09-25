/** Surface container for grouped content. Use for settings panels, file previews, summaries, and dashboards. */
export interface CardProps {
  children: React.ReactNode;
  /** Inner padding size */
  padding?: 'sm' | 'md' | 'lg';
  /** Enable hover lift effect */
  hover?: boolean;
  /** Makes the whole card clickable */
  onClick?: () => void;
  style?: React.CSSProperties;
}

/** Card header region — renders a bottom border separator. */
export interface CardHeaderProps { children: React.ReactNode; style?: React.CSSProperties; }
/** Card title text inside a CardHeader. */
export interface CardTitleProps { children: React.ReactNode; style?: React.CSSProperties; }
/** Card footer region — renders a top border separator, flex row. */
export interface CardFooterProps { children: React.ReactNode; style?: React.CSSProperties; }
