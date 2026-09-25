/** Inline status message. Use for success confirmations, warnings, errors, and contextual info — never for toasts or loading states. */
export interface AlertProps {
  variant?: 'success' | 'warning' | 'danger' | 'info';
  /** Bold title line */
  title?: string;
  /** Body text */
  children?: React.ReactNode;
  /** If provided, renders a close button */
  onClose?: () => void;
}
