import React, { useState } from 'react';

export function Switch({ checked = false, onChange, label, disabled = false }) {
  const [hovered, setHovered] = useState(false);
  return (
    <label style={{ display: 'inline-flex', alignItems: 'center', gap: '10px', cursor: disabled ? 'not-allowed' : 'pointer', opacity: disabled ? 0.5 : 1, fontFamily: 'var(--font-sans)', fontSize: 'var(--text-sm)', color: 'var(--mc-ink-soft)', userSelect: 'none' }}>
      <span
        role="switch"
        aria-checked={checked}
        onClick={() => !disabled && onChange && onChange(!checked)}
        onMouseEnter={() => setHovered(true)}
        onMouseLeave={() => setHovered(false)}
        style={{
          width: '36px', height: '20px', borderRadius: '10px', flexShrink: 0, position: 'relative',
          background: checked ? 'var(--mc-accent)' : hovered ? 'var(--mc-border-strong)' : 'var(--mc-border)',
          transition: 'background 0.2s',
        }}
      >
        <span style={{
          position: 'absolute', top: '3px',
          left: checked ? '19px' : '3px',
          width: '14px', height: '14px', borderRadius: '50%',
          background: '#fff', boxShadow: 'var(--shadow-sm)',
          transition: 'left 0.18s var(--ease-out)',
        }} />
      </span>
      {label}
    </label>
  );
}
