/** Text input field with optional label, prefix/suffix, error and hint states. */
export interface InputProps {
  /** Field label rendered above */
  label?: string;
  placeholder?: string;
  value?: string;
  onChange?: (e: React.ChangeEvent<HTMLInputElement>) => void;
  type?: string;
  /** Error message — turns border red */
  error?: string;
  /** Hint text shown below */
  hint?: string;
  disabled?: boolean;
  /** Element shown before the text (e.g. a search icon) */
  prefix?: React.ReactNode;
  /** Element shown after the text (e.g. a unit label) */
  suffix?: React.ReactNode;
  style?: React.CSSProperties;
}
