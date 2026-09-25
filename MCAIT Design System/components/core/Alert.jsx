import React from 'react';

const ALERT_STYLES = {
  success: { bg: 'var(--mc-success-soft)', border: 'var(--mc-success-line)', color: 'var(--mc-success)', icon: '✓' },
  warning: { bg: 'var(--mc-warning-soft)', border: 'var(--mc-warning-line)', color: 'var(--mc-warning)', icon: '!' },
  danger:  { bg: 'var(--mc-danger-soft)',  border: 'var(--mc-danger-line)',  color: 'var(--mc-danger)',  icon: '✕' },
  info:    { bg: 'var(--mc-info-soft)',    border: 'var(--mc-info-line)',    color: 'var(--mc-info)',    icon: 'i' },
};

export function Alert({ variant = 'info', title, children, onClose }) {
  const s = ALERT_STYLES[variant] || ALERT_STYLES.info;
  return (
    <div style={{
      display: 'flex', gap: '12px', padding: '12px 16px',
      borderRadius: 'var(--radius-md)', border: `1px solid ${s.border}`,
      background: s.bg, fontFamily: 'var(--font-sans)',
    }}>
      <span style={{
        width: '20px', height: '20px', borderRadius: '50%', flexShrink: 0,
        background: s.color, color: '#fff', display: 'flex',
        alignItems: 'center', justifyContent: 'center',
        fontSize: '11px', fontWeight: '700', marginTop: '1px',
      }}>{s.icon}</span>
      <div style={{ flex: 1, minWidth: 0 }}>
        {title && <p style={{ margin: '0 0 2px', fontSize: 'var(--text-sm)', fontWeight: 'var(--weight-semibold)', color: 'var(--mc-ink)' }}>{title}</p>}
        {children && <p style={{ margin: 0, fontSize: 'var(--text-xs)', color: 'var(--mc-ink-soft)', lineHeight: 1.5 }}>{children}</p>}
      </div>
      {onClose && (
        <button onClick={onClose} style={{ background: 'none', border: 'none', cursor: 'pointer', padding: 0, color: 'var(--mc-muted)', fontSize: '16px', lineHeight: 1, alignSelf: 'flex-start' }}>×</button>
      )}
    </div>
  );
}
