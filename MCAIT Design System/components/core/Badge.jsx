import React from 'react';

const VARIANT_STYLES = {
  default:  { bg: 'var(--mc-canvas-2)',      color: 'var(--mc-ink-soft)',  border: 'var(--mc-border)' },
  primary:  { bg: 'var(--mc-accent-soft)',   color: 'var(--mc-accent-ink)', border: 'var(--mc-accent-line)' },
  success:  { bg: 'var(--mc-success-soft)',  color: 'var(--mc-success)',   border: 'var(--mc-success-line)' },
  warning:  { bg: 'var(--mc-warning-soft)',  color: 'var(--mc-warning)',   border: 'var(--mc-warning-line)' },
  danger:   { bg: 'var(--mc-danger-soft)',   color: 'var(--mc-danger)',    border: 'var(--mc-danger-line)' },
  info:     { bg: 'var(--mc-info-soft)',     color: 'var(--mc-info)',      border: 'var(--mc-info-line)' },
  gold:     { bg: 'var(--mc-gold-soft)',     color: 'var(--mc-gold-ink)',  border: 'var(--mc-gold-line)' },
  solid:    { bg: 'var(--mc-accent)',        color: 'var(--mc-accent-fg)', border: 'transparent' },
};

const DOT_COLORS = {
  default: 'var(--mc-faint)', primary: 'var(--mc-accent)', success: 'var(--mc-success)',
  warning: 'var(--mc-warning)', danger: 'var(--mc-danger)', info: 'var(--mc-info)',
  gold: 'var(--mc-gold)', solid: 'var(--mc-accent-fg)',
};

export function Badge({ children, variant = 'default', dot = false, size = 'md', style: extra = {} }) {
  const v = VARIANT_STYLES[variant] || VARIANT_STYLES.default;
  const sz = size === 'sm' ? { fontSize: '10px', padding: '2px 7px' } : { fontSize: 'var(--text-xs)', padding: '3px 9px' };
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', gap: '5px',
      borderRadius: 'var(--radius-pill)', border: `1px solid ${v.border}`,
      background: v.bg, color: v.color,
      fontFamily: 'var(--font-sans)', fontWeight: 'var(--weight-semibold)',
      lineHeight: 1, whiteSpace: 'nowrap',
      ...sz, ...extra,
    }}>
      {dot && (
        <span style={{ width: '6px', height: '6px', borderRadius: '50%', background: DOT_COLORS[variant] || DOT_COLORS.default, flexShrink: 0 }} />
      )}
      {children}
    </span>
  );
}
