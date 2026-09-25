import React, { useState } from 'react';

const BASE = {
  display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
  gap: '6px', fontFamily: 'var(--font-sans)', fontWeight: 'var(--weight-semibold)',
  borderRadius: 'var(--radius-md)', border: 'none', cursor: 'pointer',
  transition: 'background 0.16s, box-shadow 0.16s, transform 0.12s',
  textDecoration: 'none', whiteSpace: 'nowrap', lineHeight: 1,
};

const SIZE = {
  sm: { fontSize: 'var(--text-xs)', padding: '6px 12px', height: '28px' },
  md: { fontSize: 'var(--text-sm)', padding: '8px 16px', height: '34px' },
  lg: { fontSize: 'var(--text-base)', padding: '10px 20px', height: '40px' },
};

const VARIANT = {
  primary: {
    background: 'var(--mc-accent)', color: 'var(--mc-accent-fg)',
    hover: { background: 'var(--mc-accent-hover)' },
  },
  secondary: {
    background: 'var(--mc-canvas-2)', color: 'var(--mc-ink-soft)',
    border: '1px solid var(--mc-border)',
    hover: { background: 'var(--mc-border)' },
  },
  ghost: {
    background: 'transparent', color: 'var(--mc-ink-soft)',
    hover: { background: 'var(--mc-canvas-2)' },
  },
  destructive: {
    background: 'var(--mc-danger-soft)', color: 'var(--mc-danger)',
    border: '1px solid var(--mc-danger-line)',
    hover: { background: 'var(--mc-danger)', color: '#fff' },
  },
  brand: {
    background: 'var(--mc-gold)', color: 'var(--mc-gold-fg)',
    hover: { background: 'var(--mc-gold-hover)' },
  },
};

export function Button({
  children,
  variant = 'primary',
  size = 'md',
  disabled = false,
  loading = false,
  fullWidth = false,
  onClick,
  type = 'button',
  style: extraStyle = {},
}) {
  const [hovered, setHovered] = useState(false);
  const [pressed, setPressed] = useState(false);
  const v = VARIANT[variant] || VARIANT.primary;
  const s = SIZE[size] || SIZE.md;

  const computed = {
    ...BASE,
    ...s,
    background: v.background,
    color: v.color,
    border: v.border || 'none',
    opacity: disabled || loading ? 0.5 : 1,
    cursor: disabled || loading ? 'not-allowed' : 'pointer',
    width: fullWidth ? '100%' : undefined,
    transform: pressed && !disabled ? 'scale(0.98)' : 'scale(1)',
    ...(hovered && !disabled && !pressed ? v.hover : {}),
    ...extraStyle,
  };

  return (
    <button
      type={type}
      style={computed}
      disabled={disabled || loading}
      onClick={onClick}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => { setHovered(false); setPressed(false); }}
      onMouseDown={() => setPressed(true)}
      onMouseUp={() => setPressed(false)}
    >
      {loading && (
        <svg width="14" height="14" viewBox="0 0 14 14" fill="none" style={{ animation: 'spin 0.7s linear infinite' }}>
          <circle cx="7" cy="7" r="5.5" stroke="currentColor" strokeWidth="1.5" strokeDasharray="28" strokeDashoffset="10" strokeLinecap="round" />
          <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
        </svg>
      )}
      {children}
    </button>
  );
}
