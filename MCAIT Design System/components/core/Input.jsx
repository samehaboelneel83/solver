import React, { useState } from 'react';

export function Input({
  label, placeholder, value, onChange, type = 'text',
  error, hint, disabled = false, prefix, suffix,
  style: extra = {},
}) {
  const [focused, setFocused] = useState(false);
  const borderColor = error ? 'var(--mc-danger-line)' : focused ? 'var(--mc-accent-line)' : 'var(--mc-border)';
  const shadow = focused ? 'var(--shadow-focus)' : 'none';

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '5px', fontFamily: 'var(--font-sans)', ...extra }}>
      {label && (
        <label style={{ fontSize: 'var(--text-xs)', fontWeight: 'var(--weight-semibold)', color: 'var(--mc-ink-soft)' }}>
          {label}
        </label>
      )}
      <div style={{
        display: 'flex', alignItems: 'center', gap: '8px',
        border: `1px solid ${borderColor}`, borderRadius: 'var(--radius-sm)',
        background: disabled ? 'var(--mc-canvas-2)' : 'var(--mc-surface)',
        padding: '0 12px', height: '36px',
        boxShadow: shadow, transition: 'border-color 0.16s, box-shadow 0.16s',
      }}>
        {prefix && <span style={{ color: 'var(--mc-faint)', display: 'flex', alignItems: 'center' }}>{prefix}</span>}
        <input
          type={type}
          value={value}
          onChange={onChange}
          placeholder={placeholder}
          disabled={disabled}
          onFocus={() => setFocused(true)}
          onBlur={() => setFocused(false)}
          style={{
            flex: 1, border: 'none', outline: 'none', background: 'transparent',
            fontFamily: 'var(--font-sans)', fontSize: 'var(--text-sm)',
            color: 'var(--mc-ink)', caretColor: 'var(--mc-accent)',
          }}
        />
        {suffix && <span style={{ color: 'var(--mc-faint)', display: 'flex', alignItems: 'center' }}>{suffix}</span>}
      </div>
      {(error || hint) && (
        <p style={{ fontSize: 'var(--text-xs)', color: error ? 'var(--mc-danger)' : 'var(--mc-muted)', margin: 0 }}>
          {error || hint}
        </p>
      )}
    </div>
  );
}
