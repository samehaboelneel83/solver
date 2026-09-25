import React, { useState } from 'react';

/* ── MCAIT product suite (the shared family) ─────────────────────── */
export const MCAIT_APPS = [
  { id: 'cowork',   name: 'Cowork',   color: 'var(--mc-gold)',          icon: 'sparkle', iconColor: 'oklch(0.20 0.04 80)' },
  { id: 'drive',    name: 'Drive',    color: 'oklch(0.52 0.17 255)',    icon: 'folder' },
  { id: 'calendar', name: 'Calendar', color: 'oklch(0.52 0.13 150)',    icon: 'calendar' },
  { id: 'meet',     name: 'Meet',     color: 'oklch(0.55 0.11 200)',    icon: 'video' },
  { id: 'notebook', name: 'Notebook', color: 'oklch(0.52 0.16 295)',    icon: 'notebook' },
  { id: 'mail',     name: 'Mail',     color: 'oklch(0.55 0.17 25)',     icon: 'mail' },
  { id: 'aura',     name: 'Aura',     color: 'oklch(0.56 0.18 345)',    icon: 'globe' },
];

/* ── Lucide-style icons (currentColor, 1.5 stroke) ───────────────── */
const PATHS = {
  folder:   'M2 6a2 2 0 012-2h4l2 2h6a2 2 0 012 2v8a2 2 0 01-2 2H4a2 2 0 01-2-2V6z',
  file:     'M13 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V9l-7-7z M13 2v7h7',
  notebook: 'M4 4a2 2 0 012-2h12a2 2 0 012 2v16a2 2 0 01-2 2H6a2 2 0 01-2-2V4z M9 2v20',
  calendar: 'M8 2v4 M16 2v4 M3 8h18 M5 4h14a2 2 0 012 2v13a2 2 0 01-2 2H5a2 2 0 01-2-2V6a2 2 0 012-2z',
  video:    'M15 10l4.55-2.55A1 1 0 0121 8.4v7.2a1 1 0 01-1.45.9L15 14v-4z M3 8a2 2 0 012-2h8a2 2 0 012 2v8a2 2 0 01-2 2H5a2 2 0 01-2-2V8z',
  mail:     'M3 5h18v14H3z M3 6l9 7 9-7',
  globe:    'M12 2a10 10 0 100 20 10 10 0 000-20z M2 12h20 M12 2a15 15 0 010 20 15 15 0 010-20z',
  grid:     'M3 3h7v7H3z M14 3h7v7h-7z M3 14h7v7H3z M14 14h7v7h-7z',
  sparkle:  'M12 2l2.2 5.8L20 10l-5.8 2.2L12 18l-2.2-5.8L4 10l5.8-2.2z',
  search:   'M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z',
  chevRight:'M9 18l6-6-6-6',
  chevDown: 'M6 9l6 6 6-6',
  x:        'M18 6L6 18 M6 6l12 12',
  settings: 'M12 15a3 3 0 100-6 3 3 0 000 6z M19.4 15a1.65 1.65 0 00.33 1.82l.06.06a2 2 0 11-2.83 2.83l-.06-.06a1.65 1.65 0 00-1.82-.33 1.65 1.65 0 00-1 1.51V21a2 2 0 11-4 0v-.09A1.65 1.65 0 009 19.4a1.65 1.65 0 00-1.82.33l-.06.06a2 2 0 11-2.83-2.83l.06-.06a1.65 1.65 0 00.33-1.82 1.65 1.65 0 00-1.51-1H3a2 2 0 110-4h.09A1.65 1.65 0 004.6 9a1.65 1.65 0 00-.33-1.82l-.06-.06a2 2 0 112.83-2.83l.06.06a1.65 1.65 0 001.82.33H9a1.65 1.65 0 001-1.51V3a2 2 0 114 0v.09a1.65 1.65 0 001 1.51 1.65 1.65 0 001.82-.33l.06-.06a2 2 0 112.83 2.83l-.06.06a1.65 1.65 0 00-.33 1.82V9a1.65 1.65 0 001.51 1H21a2 2 0 110 4h-.09a1.65 1.65 0 00-1.51 1z',
  info:     'M12 2a10 10 0 100 20 10 10 0 000-20z M12 16v-4 M12 8h.01',
  logout:   'M9 21H5a2 2 0 01-2-2V5a2 2 0 012-2h4 M16 17l5-5-5-5 M21 12H9',
};

function Icon({ name, size = 18, color = 'currentColor', strokeWidth = 1.5, fill = 'none' }) {
  const d = PATHS[name] || PATHS.file;
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill={fill} stroke={color}
      strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round">
      {d.split(' M').map((seg, i) => <path key={i} d={i === 0 ? seg : 'M' + seg} />)}
    </svg>
  );
}

/* ── MCAIT seal (the "Mc 8" monogram) ────────────────────────────── */
export function Seal({ size = 30, radius = 8 }) {
  return (
    <div style={{ width: size, height: size, borderRadius: radius, background: 'var(--mc-gold)',
      display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
      <span style={{ fontFamily: 'var(--font-display)', fontWeight: 800, color: 'var(--mc-gold-fg)',
        letterSpacing: '0.5px', lineHeight: 1.05, display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
        <span style={{ fontSize: size * 0.27 }}>Mc</span>
        <span style={{ fontSize: size * 0.34 }}>8</span>
      </span>
    </div>
  );
}

function Avatar({ name = '', size = 28 }) {
  const initials = name.split(' ').filter(Boolean).slice(0, 2).map(w => w[0].toUpperCase()).join('');
  return (
    <span style={{ width: size, height: size, borderRadius: '50%', background: 'oklch(0.88 0.09 80)',
      display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0,
      fontSize: size * 0.4, fontWeight: 700, color: 'oklch(0.32 0.08 80)',
      fontFamily: 'var(--font-sans)', userSelect: 'none' }}>{initials}</span>
  );
}

/* ════════════════════════════════════════════════════════════════
   MCAITWidget — the shared identity cluster that lives on the right
   of every MCAIT product's app bar: M8 seal · Cowork · Apps · You.
   ════════════════════════════════════════════════════════════════ */
export function MCAITWidget({ apps = MCAIT_APPS, activeApp, user = { name: 'Omar Al-Amin', email: 'omar@mcait.com' }, onNavigate, showSeal = true }) {
  const [open, setOpen] = useState(null); // 'cowork' | 'apps' | 'user' | null
  const toggle = (k) => setOpen(o => o === k ? null : k);
  const close = () => setOpen(null);

  const iconBtn = (key, child, title, activeBg) => (
    <button title={title} onClick={() => toggle(key)}
      style={{ width: 32, height: 32, borderRadius: 8, border: 'none', cursor: 'pointer',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        background: open === key ? (activeBg || 'var(--mc-canvas-2)') : 'none', transition: 'background var(--dur-fast, .15s)' }}
      onMouseEnter={e => { if (open !== key) e.currentTarget.style.background = activeBg || 'var(--mc-canvas-2)'; }}
      onMouseLeave={e => { if (open !== key) e.currentTarget.style.background = 'none'; }}>
      {child}
    </button>
  );

  return (
    <div style={{ position: 'relative', display: 'flex', alignItems: 'center', gap: 2,
      background: 'var(--mc-canvas)', border: '1px solid var(--mc-border)', borderRadius: 'var(--radius-md)',
      padding: '4px 6px', flexShrink: 0, boxShadow: 'var(--shadow-sm)' }}>

      {open && <div style={{ position: 'fixed', inset: 0, zIndex: 299 }} onClick={close} />}

      {/* M8 seal */}
      {showSeal && <div style={{ width: 29, height: 32, borderRadius: 8, background: 'var(--mc-gold)', display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
        <span style={{ fontFamily: 'var(--font-display)', fontWeight: 800, color: 'var(--mc-gold-fg)', letterSpacing: '0.5px', lineHeight: 1.05, display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
          <span style={{ fontSize: 8 }}>Mc</span><span style={{ fontSize: 10 }}>8</span>
        </span>
      </div>}
      {showSeal && <div style={{ width: 1, height: 18, background: 'var(--mc-border)', margin: '0 2px', flexShrink: 0 }} />}

      {/* Cowork */}
      {iconBtn('cowork', <Icon name="sparkle" size={17} color="var(--mc-gold)" fill="var(--mc-gold)" strokeWidth={0} />, 'Cowork', 'var(--mc-gold-soft)')}
      {open === 'cowork' && (
        <div style={{ position: 'absolute', top: '100%', right: 0, marginTop: 8, zIndex: 300, width: 320,
          background: 'var(--mc-surface)', border: '1px solid var(--mc-border)', borderRadius: 'var(--radius-xl)',
          boxShadow: 'var(--shadow-lg)', overflow: 'hidden' }}>
          <div style={{ padding: '14px 16px', borderBottom: '1px solid var(--mc-border)', display: 'flex', alignItems: 'center', gap: 10, background: 'var(--mc-gold-soft)' }}>
            <div style={{ width: 28, height: 28, borderRadius: 7, background: 'var(--mc-gold)', display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
              <Icon name="sparkle" size={14} color="var(--mc-gold-fg)" fill="var(--mc-gold-fg)" strokeWidth={0} />
            </div>
            <div style={{ flex: 1 }}>
              <div style={{ fontFamily: 'var(--font-display)', fontWeight: 700, fontSize: 14, color: 'var(--mc-gold-ink)', letterSpacing: '-0.01em' }}>Cowork</div>
              <div style={{ fontSize: 10, color: 'var(--mc-muted)' }}>Your agentic workspace assistant</div>
            </div>
            <button onClick={close} style={{ background: 'none', border: 'none', cursor: 'pointer', padding: 4, display: 'flex' }}><Icon name="x" size={14} color="var(--mc-faint)" /></button>
          </div>
          <div style={{ padding: '10px 12px', display: 'flex', gap: 8, alignItems: 'center' }}>
            <input placeholder="Ask Cowork anything…" style={{ flex: 1, border: '1px solid var(--mc-border)', borderRadius: 'var(--radius-sm)', padding: '8px 12px', fontSize: 13, fontFamily: 'var(--font-sans)', outline: 'none', background: 'var(--mc-canvas-2)', caretColor: 'var(--mc-gold)' }}
              onFocus={e => e.target.style.borderColor = 'var(--mc-gold-line)'} onBlur={e => e.target.style.borderColor = 'var(--mc-border)'} />
            <button style={{ width: 34, height: 34, borderRadius: 'var(--radius-sm)', background: 'var(--mc-gold)', border: 'none', cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
              <Icon name="chevRight" size={15} color="var(--mc-gold-fg)" strokeWidth={2} />
            </button>
          </div>
        </div>
      )}

      {/* Apps grid */}
      {iconBtn('apps', <Icon name="grid" size={17} color="var(--mc-faint)" />, 'MCAIT apps')}
      {open === 'apps' && (
        <div style={{ position: 'absolute', top: '100%', right: 0, marginTop: 8, zIndex: 300, width: 276,
          background: 'var(--mc-surface)', border: '1px solid var(--mc-border)', borderRadius: 'var(--radius-xl)',
          boxShadow: 'var(--shadow-lg)', padding: 16 }}>
          <div style={{ fontSize: 10, fontWeight: 600, color: 'var(--mc-muted)', letterSpacing: '0.06em', textTransform: 'uppercase', marginBottom: 12 }}>MCAIT workspace</div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3,1fr)', gap: 2 }}>
            {apps.map(app => (
              <button key={app.id} onClick={() => { onNavigate && onNavigate(app.id); close(); }}
                style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 5, padding: '8px 4px', borderRadius: 'var(--radius-md)', background: 'none', border: 'none', cursor: 'pointer' }}
                onMouseEnter={e => e.currentTarget.style.background = 'var(--mc-canvas-2)'} onMouseLeave={e => e.currentTarget.style.background = 'none'}>
                <div style={{ width: 36, height: 36, borderRadius: 9, background: app.color, display: 'flex', alignItems: 'center', justifyContent: 'center', boxShadow: 'var(--shadow-sm)' }}>
                  <Icon name={app.icon} size={18} color={app.iconColor || '#fff'} strokeWidth={1.5} />
                </div>
                <span style={{ fontSize: 11, fontWeight: app.id === activeApp ? 600 : 400, color: app.id === activeApp ? 'var(--mc-accent)' : 'var(--mc-ink-soft)' }}>{app.name}</span>
              </button>
            ))}
          </div>
        </div>
      )}

      {/* User */}
      <button onClick={() => toggle('user')} style={{ background: 'none', border: 'none', cursor: 'pointer', borderRadius: '50%', padding: 2, display: 'flex' }}>
        <Avatar name={user.name} size={28} />
      </button>
      {open === 'user' && (
        <div style={{ position: 'absolute', top: '100%', right: 0, marginTop: 8, zIndex: 300, width: 264,
          background: 'var(--mc-surface)', border: '1px solid var(--mc-border)', borderRadius: 'var(--radius-xl)',
          boxShadow: 'var(--shadow-lg)', overflow: 'hidden' }}>
          <div style={{ padding: 20, display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 10, borderBottom: '1px solid var(--mc-border)', background: 'var(--mc-canvas)' }}>
            <Avatar name={user.name} size={60} />
            <div style={{ textAlign: 'center' }}>
              <div style={{ fontSize: 15, fontWeight: 600, color: 'var(--mc-ink)' }}>{user.name}</div>
              <div style={{ fontSize: 12, color: 'var(--mc-muted)', fontFamily: 'var(--font-mono)', marginTop: 2 }}>{user.email}</div>
            </div>
          </div>
          {[{ label: 'Manage your account', icon: 'settings' }, { label: 'Settings & preferences', icon: 'settings' }, { label: 'Privacy & terms', icon: 'info' }].map(({ label, icon }) => (
            <button key={label} style={{ width: '100%', display: 'flex', alignItems: 'center', gap: 10, padding: '10px 16px', background: 'none', border: 'none', cursor: 'pointer', fontSize: 13, fontFamily: 'var(--font-sans)', color: 'var(--mc-ink-soft)', textAlign: 'left' }}
              onMouseEnter={e => e.currentTarget.style.background = 'var(--mc-canvas-2)'} onMouseLeave={e => e.currentTarget.style.background = 'none'}>
              <Icon name={icon} size={15} color="var(--mc-faint)" />{label}
            </button>
          ))}
          <div style={{ height: 1, background: 'var(--mc-border)' }} />
          <button style={{ width: '100%', display: 'flex', alignItems: 'center', gap: 10, padding: '10px 16px', background: 'none', border: 'none', cursor: 'pointer', fontSize: 13, fontFamily: 'var(--font-sans)', color: 'var(--mc-ink-soft)', textAlign: 'left' }}
            onMouseEnter={e => e.currentTarget.style.background = 'var(--mc-canvas-2)'} onMouseLeave={e => e.currentTarget.style.background = 'none'}>
            <Icon name="logout" size={15} color="var(--mc-faint)" />Sign out
          </button>
        </div>
      )}
    </div>
  );
}

/* ════════════════════════════════════════════════════════════════
   AppBar — the standard MCAIT product top bar.
   Branded product mark on the left, optional center slot (search /
   controls), and the shared MCAITWidget identity cluster on the right.
   ════════════════════════════════════════════════════════════════ */
export function AppBar({ product = { id: 'cowork', name: 'Cowork', icon: 'sparkle' }, children, user, onNavigate, divider = true, style: extra = {} }) {
  const goldProduct = product.id === 'cowork';
  return (
    <header data-product={product.id}
      style={{ height: 52, background: 'var(--mc-surface)', borderBottom: divider ? '1px solid var(--mc-border)' : 'none',
        display: 'flex', alignItems: 'center', padding: '0 12px', gap: 10, flexShrink: 0, ...extra }}>

      {/* Product mark */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 7, flexShrink: 0 }}>
        <div style={{ width: 28, height: 28, borderRadius: 7, background: goldProduct ? 'var(--mc-gold)' : 'var(--mc-accent)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          <Icon name={product.icon || 'folder'} size={14} color={goldProduct ? 'var(--mc-gold-fg)' : '#fff'} fill={product.icon === 'sparkle' ? (goldProduct ? 'var(--mc-gold-fg)' : '#fff') : 'none'} strokeWidth={product.icon === 'sparkle' ? 0 : 1.75} />
        </div>
        <span style={{ fontSize: 14, fontWeight: 700, color: goldProduct ? 'var(--mc-gold-ink)' : 'var(--mc-accent)', fontFamily: 'var(--font-display)', letterSpacing: '-0.02em' }}>{product.name}</span>
      </div>

      {/* Center slot */}
      <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', minWidth: 0 }}>{children}</div>

      {/* Identity widget */}
      <MCAITWidget activeApp={product.id} user={user} onNavigate={onNavigate} />
    </header>
  );
}
