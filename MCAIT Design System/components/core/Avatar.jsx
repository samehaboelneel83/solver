import React from 'react';

const SIZE_MAP = {
  xs: { size: 20, font: 9, radius: 6 },
  sm: { size: 28, font: 11, radius: 8 },
  md: { size: 36, font: 14, radius: 10 },
  lg: { size: 48, font: 18, radius: 12 },
  xl: { size: 64, font: 22, radius: 16 },
};

function initials(name = '') {
  return name.split(' ').filter(Boolean).slice(0, 2).map(w => w[0].toUpperCase()).join('');
}

// Deterministic hue from name string
function hueFromName(name = '') {
  let h = 0;
  for (let i = 0; i < name.length; i++) h = (h * 31 + name.charCodeAt(i)) & 0xffffffff;
  return Math.abs(h) % 360;
}

export function Avatar({ name, src, size = 'md', style: extra = {} }) {
  const s = SIZE_MAP[size] || SIZE_MAP.md;
  const hue = hueFromName(name);
  const bg = `oklch(0.88 0.09 ${hue})`;
  const fg = `oklch(0.32 0.08 ${hue})`;

  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
      width: s.size, height: s.size, borderRadius: s.radius,
      background: src ? 'transparent' : bg,
      overflow: 'hidden', flexShrink: 0,
      fontFamily: 'var(--font-sans)', fontWeight: 'var(--weight-bold)',
      fontSize: s.font, color: fg, userSelect: 'none',
      border: '1.5px solid oklch(1 0 0 / 0.5)',
      ...extra,
    }}>
      {src ? <img src={src} alt={name} style={{ width: '100%', height: '100%', objectFit: 'cover' }} /> : initials(name)}
    </span>
  );
}
