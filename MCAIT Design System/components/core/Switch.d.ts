/** Boolean toggle control. Use for settings and preferences that take effect immediately. */
export interface SwitchProps {
  checked?: boolean;
  onChange?: (checked: boolean) => void;
  /** Label rendered to the right of the toggle */
  label?: string;
  disabled?: boolean;
}
