import React, { useState } from 'react';

export function Card({ children, padding = 'md', hover = false, onClick, style: extra = {} }) {
  const [isHovered, setIsHovered] = useState(false);
  const p = { sm: '12px', md: '20px', lg: '28px' }[padding] || '20px';
  return (
    <div
      onClick={onClick}
      onMouseEnter={() => setIsHovered(true)}
      onMouseLeave={() => setIsHovered(false)}
      style={{
        background: 'var(--mc-surface)', borderRadius: 'var(--radius-lg)',
        border: '1px solid var(--mc-border)',
        boxShadow: hover && isHovered ? 'var(--shadow-md)' : 'var(--shadow-sm)',
        transform: hover && isHovered ? 'translateY(-1px)' : 'translateY(0)',
        transition: 'box-shadow 0.2s, transform 0.2s',
        padding: p, cursor: onClick ? 'pointer' : undefined,
        ...extra,
      }}
    >
      {children}
    </div>
  );
}

export function CardHeader({ children, style: extra = {} }) {
  return (
    <div style={{ paddingBottom: '14px', marginBottom: '14px', borderBottom: '1px solid var(--mc-border)', ...extra }}>
      {children}
    </div>
  );
}

export function CardTitle({ children, style: extra = {} }) {
  return (
    <h3 style={{ margin: 0, fontSize: 'var(--text-md)', fontWeight: 'var(--weight-semibold)', color: 'var(--mc-ink)', fontFamily: 'var(--font-sans)', ...extra }}>
      {children}
    </h3>
  );
}

export function CardFooter({ children, style: extra = {} }) {
  return (
    <div style={{ paddingTop: '14px', marginTop: '14px', borderTop: '1px solid var(--mc-border)', display: 'flex', gap: '8px', alignItems: 'center', ...extra }}>
      {children}
    </div>
  );
}
