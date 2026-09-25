import React, { useState } from 'react';

/* ── Lucide-style icons (currentColor, 1.5 stroke) ───────────────── */
const PATHS = {
  folder:      'M2 6a2 2 0 012-2h4l2 2h6a2 2 0 012 2v8a2 2 0 01-2 2H4a2 2 0 01-2-2V6z',
  users:       'M17 21v-2a4 4 0 00-4-4H5a4 4 0 00-4 4v2 M23 21v-2a4 4 0 00-3-3.87 M16 3.13a4 4 0 010 7.75 M9 11a4 4 0 100-8 4 4 0 000 8z',
  clock:       'M12 2a10 10 0 110 20A10 10 0 0112 2zm0 4v6l4 2',
  star:        'M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z',
  trash:       'M3 6h18 M19 6l-1 14a2 2 0 01-2 2H8a2 2 0 01-2-2L5 6 M8 6V4a2 2 0 012-2h4a2 2 0 012 2v2',
  plus:        'M12 5v14 M5 12h14',
  chevLeft:    'M15 18l-6-6 6-6',
  chevRight:   'M9 18l6-6-6-6',
};

function Icon({ name, size = 18, color = 'currentColor', strokeWidth = 1.5 }) {
  const d = PATHS[name] || PATHS.folder;
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color}
      strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round" style={{ flexShrink: 0 }}>
      {d.split(' M').map((seg, i) => <path key={i} d={i === 0 ? seg : 'M' + seg} />)}
    </svg>
  );
}

/* ════════════════════════════════════════════════════════════════
   Sidebar — collapsible product navigation rail. Optional featured
   "volume" card at the top (name · badge · usage meter), a list of
   nav items, and a collapse/expand toggle pinned to the bottom.
   Rounds its top-right corner by default so it tucks under the app bar.
   ════════════════════════════════════════════════════════════════ */
export function Sidebar({
  items = [],
  active,
  onNavigate,
  volume,
  label = 'Volumes',
  collapsed: collapsedProp,
  defaultCollapsed = false,
  onToggle,
  roundedCorner = 'top-right',
  style: extra = {},
}) {
  const [hovered, setHovered] = useState(null);
  const [internal, setInternal] = useState(defaultCollapsed);
  const collapsed = collapsedProp ?? internal;

  const toggle = () => {
    const next = !collapsed;
    if (collapsedProp === undefined) setInternal(next);
    onToggle && onToggle(next);
  };

  const radius = 'var(--radius-lg)';
  const corners =
    roundedCorner === 'top-right'    ? { borderTopRightRadius: radius } :
    roundedCorner === 'top-left'     ? { borderTopLeftRadius: radius } :
    roundedCorner === 'right'        ? { borderTopRightRadius: radius, borderBottomRightRadius: radius } :
    roundedCorner === 'none'         ? {} :
    { borderTopRightRadius: radius };

  const volActive = volume && (active === volume.id || active === undefined);

  return (
    <aside
      style={{
        width: collapsed ? 64 : 264,
        flexShrink: 0,
        background: 'var(--mc-surface)',
        borderTop: '1px solid var(--mc-border)',
        borderRight: '1px solid var(--mc-border)',
        display: 'flex',
        flexDirection: 'column',
        height: '100%',
        overflow: 'hidden',
        fontFamily: 'var(--font-sans)',
        transition: 'width 0.22s cubic-bezier(0.22,1,0.36,1)',
        ...corners,
        ...extra,
      }}
    >
      {/* ── scrollable body ── */}
      <div style={{ flex: 1, overflowY: 'auto', overflowX: 'hidden', padding: collapsed ? '12px 10px' : '16px 12px' }}>

        {/* Featured volume */}
        {volume && (
          <>
            {!collapsed && (
              <div style={{ fontSize: 11, fontWeight: 'var(--weight-semibold)', color: 'var(--mc-muted)', letterSpacing: '0.07em', textTransform: 'uppercase', padding: '0 4px 8px' }}>
                {label}
              </div>
            )}
            <div
              onClick={() => onNavigate && onNavigate(volume.id)}
              title={collapsed ? volume.name : undefined}
              style={{
                display: 'flex', flexDirection: collapsed ? 'row' : 'column', gap: collapsed ? 0 : 10,
                alignItems: collapsed ? 'center' : 'stretch', justifyContent: 'center',
                padding: collapsed ? 0 : '12px 14px',
                width: collapsed ? 44 : 'auto', height: collapsed ? 44 : 'auto', margin: collapsed ? '0 auto' : 0,
                borderRadius: collapsed ? 'var(--radius-md)' : 'var(--radius-lg)',
                cursor: 'pointer',
                background: volActive ? 'var(--mc-accent-soft)' : 'transparent',
                border: `1px solid ${volActive ? 'var(--mc-accent-line)' : 'transparent'}`,
                transition: 'background 0.13s, border-color 0.13s',
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: 10, width: '100%', justifyContent: collapsed ? 'center' : 'flex-start' }}>
                <Icon name={volume.icon || 'folder'} size={collapsed ? 19 : 17} color={volActive ? 'var(--mc-accent)' : 'var(--mc-faint)'} strokeWidth={1.75} />
                {!collapsed && (
                  <>
                    <span style={{ flex: 1, fontSize: 14, fontWeight: 'var(--weight-semibold)', color: volActive ? 'var(--mc-accent-ink)' : 'var(--mc-ink)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{volume.name}</span>
                    {volume.badge && (
                      <span style={{ fontSize: 10, fontFamily: 'var(--font-mono)', color: 'var(--mc-muted)', background: 'var(--mc-canvas-2)', border: '1px solid var(--mc-border)', borderRadius: 4, padding: '1px 6px', flexShrink: 0 }}>{volume.badge}</span>
                    )}
                  </>
                )}
              </div>
              {!collapsed && volume.pct != null && (
                <div style={{ width: '100%' }}>
                  <div style={{ height: 4, borderRadius: 99, background: 'var(--mc-canvas-2)', overflow: 'hidden' }}>
                    <div style={{ height: '100%', width: `${volume.pct}%`, background: 'var(--mc-accent)', borderRadius: 99, transition: 'width 0.3s' }} />
                  </div>
                  {volume.usage && (
                    <div style={{ fontSize: 11, fontFamily: 'var(--font-mono)', color: 'var(--mc-muted)', marginTop: 6 }}>{volume.usage}</div>
                  )}
                </div>
              )}
            </div>
            <div style={{ height: 1, background: 'var(--mc-border)', margin: collapsed ? '12px 6px' : '14px 4px' }} />
          </>
        )}

        {/* Nav items */}
        <nav style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
          {items.map(n => {
            const isActive = active === n.id;
            const isHover = hovered === n.id;
            return (
              <div
                key={n.id}
                onClick={() => onNavigate && onNavigate(n.id)}
                onMouseEnter={() => setHovered(n.id)}
                onMouseLeave={() => setHovered(null)}
                title={collapsed ? n.label : undefined}
                style={{
                  display: 'flex', alignItems: 'center', gap: 11,
                  justifyContent: collapsed ? 'center' : 'flex-start',
                  padding: collapsed ? 0 : '9px 12px',
                  width: collapsed ? 44 : 'auto', height: collapsed ? 44 : 'auto', margin: collapsed ? '0 auto' : 0,
                  borderRadius: 'var(--radius-md)', cursor: 'pointer',
                  background: isActive ? 'var(--mc-accent-soft)' : isHover ? 'var(--mc-canvas-2)' : 'transparent',
                  color: isActive ? 'var(--mc-accent-ink)' : 'var(--mc-ink-soft)',
                  transition: 'background 0.13s',
                }}
              >
                <Icon name={n.icon} size={18} color={isActive ? 'var(--mc-accent)' : 'var(--mc-faint)'} strokeWidth={1.5} />
                {!collapsed && <span style={{ fontSize: 14, fontWeight: isActive ? 'var(--weight-semibold)' : 'var(--weight-medium)', whiteSpace: 'nowrap' }}>{n.label}</span>}
              </div>
            );
          })}
        </nav>
      </div>

      {/* ── collapse / expand toggle ── */}
      <div style={{ borderTop: '1px solid var(--mc-border)', padding: 8, display: 'flex', justifyContent: collapsed ? 'center' : 'flex-end' }}>
        <button
          onClick={toggle}
          title={collapsed ? 'Expand' : 'Collapse'}
          aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
          style={{ width: 32, height: 32, borderRadius: 'var(--radius-sm)', border: 'none', background: 'none', cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--mc-muted)', transition: 'background 0.13s' }}
          onMouseEnter={e => e.currentTarget.style.background = 'var(--mc-canvas-2)'}
          onMouseLeave={e => e.currentTarget.style.background = 'none'}
        >
          <Icon name={collapsed ? 'chevRight' : 'chevLeft'} size={17} color="var(--mc-faint)" strokeWidth={2} />
        </button>
      </div>
    </aside>
  );
}
