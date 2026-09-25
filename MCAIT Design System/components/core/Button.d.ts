/**
 * Primary interactive control. Use for all user-initiated actions.
 * @startingPoint section="Components" subtitle="Primary, secondary, ghost, destructive — sm/md/lg" viewport="400x160"
 */
export interface ButtonProps {
  /** Button label and/or icon children */
  children: React.ReactNode;
  /** Visual treatment */
  variant?: 'primary' | 'secondary' | 'ghost' | 'destructive' | 'brand';
  /** Size */
  size?: 'sm' | 'md' | 'lg';
  /** Disables the button */
  disabled?: boolean;
  /** Shows a spinner and disables */
  loading?: boolean;
  /** Expands to full container width */
  fullWidth?: boolean;
  /** Click handler */
  onClick?: () => void;
  /** HTML button type */
  type?: 'button' | 'submit' | 'reset';
  style?: React.CSSProperties;
}
