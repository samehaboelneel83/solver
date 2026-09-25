/** User identity avatar. Use wherever a person, team, or AI agent needs a visual identity mark. Falls back to initials with a deterministic hue when no src is provided. */
export interface AvatarProps {
  /** Full name — used for initials and hue derivation */
  name: string;
  /** Image URL — initials shown as fallback */
  src?: string;
  /** Size preset */
  size?: 'xs' | 'sm' | 'md' | 'lg' | 'xl';
  style?: React.CSSProperties;
}
