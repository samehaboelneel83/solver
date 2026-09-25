/* @ds-bundle: {"format":3,"namespace":"MCAITDesignSystem_6bac07","components":[{"name":"Alert","sourcePath":"components/core/Alert.jsx"},{"name":"MCAIT_APPS","sourcePath":"components/core/AppBar.jsx"},{"name":"Seal","sourcePath":"components/core/AppBar.jsx"},{"name":"MCAITWidget","sourcePath":"components/core/AppBar.jsx"},{"name":"AppBar","sourcePath":"components/core/AppBar.jsx"},{"name":"Avatar","sourcePath":"components/core/Avatar.jsx"},{"name":"Badge","sourcePath":"components/core/Badge.jsx"},{"name":"Button","sourcePath":"components/core/Button.jsx"},{"name":"Card","sourcePath":"components/core/Card.jsx"},{"name":"CardHeader","sourcePath":"components/core/Card.jsx"},{"name":"CardTitle","sourcePath":"components/core/Card.jsx"},{"name":"CardFooter","sourcePath":"components/core/Card.jsx"},{"name":"Input","sourcePath":"components/core/Input.jsx"},{"name":"Sidebar","sourcePath":"components/core/Sidebar.jsx"},{"name":"Switch","sourcePath":"components/core/Switch.jsx"},{"name":"Tabs","sourcePath":"components/core/Tabs.jsx"}],"sourceHashes":{"components/core/Alert.jsx":"39b0f9613db6","components/core/AppBar.jsx":"5e8f78cc1eda","components/core/Avatar.jsx":"24346297a1c0","components/core/Badge.jsx":"8557c3e34812","components/core/Button.jsx":"d5f480c37dad","components/core/Card.jsx":"8f9209edb190","components/core/Input.jsx":"a8276d30dfd5","components/core/Sidebar.jsx":"2480e77e4fdb","components/core/Switch.jsx":"973a5ff70169","components/core/Tabs.jsx":"af1724cb64cf"},"inlinedExternals":[],"unexposedExports":[]} */

(() => {

const __ds_ns = (window.MCAITDesignSystem_6bac07 = window.MCAITDesignSystem_6bac07 || {});

const __ds_scope = {};

(__ds_ns.__errors = __ds_ns.__errors || []);

// components/core/Alert.jsx
try { (() => {
const ALERT_STYLES = {
  success: {
    bg: 'var(--mc-success-soft)',
    border: 'var(--mc-success-line)',
    color: 'var(--mc-success)',
    icon: '✓'
  },
  warning: {
    bg: 'var(--mc-warning-soft)',
    border: 'var(--mc-warning-line)',
    color: 'var(--mc-warning)',
    icon: '!'
  },
  danger: {
    bg: 'var(--mc-danger-soft)',
    border: 'var(--mc-danger-line)',
    color: 'var(--mc-danger)',
    icon: '✕'
  },
  info: {
    bg: 'var(--mc-info-soft)',
    border: 'var(--mc-info-line)',
    color: 'var(--mc-info)',
    icon: 'i'
  }
};
function Alert({
  variant = 'info',
  title,
  children,
  onClose
}) {
  const s = ALERT_STYLES[variant] || ALERT_STYLES.info;
  return /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      gap: '12px',
      padding: '12px 16px',
      borderRadius: 'var(--radius-md)',
      border: `1px solid ${s.border}`,
      background: s.bg,
      fontFamily: 'var(--font-sans)'
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      width: '20px',
      height: '20px',
      borderRadius: '50%',
      flexShrink: 0,
      background: s.color,
      color: '#fff',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      fontSize: '11px',
      fontWeight: '700',
      marginTop: '1px'
    }
  }, s.icon), /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1,
      minWidth: 0
    }
  }, title && /*#__PURE__*/React.createElement("p", {
    style: {
      margin: '0 0 2px',
      fontSize: 'var(--text-sm)',
      fontWeight: 'var(--weight-semibold)',
      color: 'var(--mc-ink)'
    }
  }, title), children && /*#__PURE__*/React.createElement("p", {
    style: {
      margin: 0,
      fontSize: 'var(--text-xs)',
      color: 'var(--mc-ink-soft)',
      lineHeight: 1.5
    }
  }, children)), onClose && /*#__PURE__*/React.createElement("button", {
    onClick: onClose,
    style: {
      background: 'none',
      border: 'none',
      cursor: 'pointer',
      padding: 0,
      color: 'var(--mc-muted)',
      fontSize: '16px',
      lineHeight: 1,
      alignSelf: 'flex-start'
    }
  }, "\xD7"));
}
Object.assign(__ds_scope, { Alert });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/core/Alert.jsx", error: String((e && e.message) || e) }); }

// components/core/AppBar.jsx
try { (() => {
const {
  useState
} = React;
/* ── MCAIT product suite (the shared family) ─────────────────────── */
const MCAIT_APPS = [{
  id: 'cowork',
  name: 'Cowork',
  color: 'var(--mc-gold)',
  icon: 'sparkle',
  iconColor: 'oklch(0.20 0.04 80)'
}, {
  id: 'drive',
  name: 'Drive',
  color: 'oklch(0.52 0.17 255)',
  icon: 'folder'
}, {
  id: 'calendar',
  name: 'Calendar',
  color: 'oklch(0.52 0.13 150)',
  icon: 'calendar'
}, {
  id: 'meet',
  name: 'Meet',
  color: 'oklch(0.55 0.11 200)',
  icon: 'video'
}, {
  id: 'notebook',
  name: 'Notebook',
  color: 'oklch(0.52 0.16 295)',
  icon: 'notebook'
}, {
  id: 'mail',
  name: 'Mail',
  color: 'oklch(0.55 0.17 25)',
  icon: 'mail'
}, {
  id: 'aura',
  name: 'Aura',
  color: 'oklch(0.56 0.18 345)',
  icon: 'globe'
}];

/* ── Lucide-style icons (currentColor, 1.5 stroke) ───────────────── */
const PATHS = {
  folder: 'M2 6a2 2 0 012-2h4l2 2h6a2 2 0 012 2v8a2 2 0 01-2 2H4a2 2 0 01-2-2V6z',
  file: 'M13 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V9l-7-7z M13 2v7h7',
  notebook: 'M4 4a2 2 0 012-2h12a2 2 0 012 2v16a2 2 0 01-2 2H6a2 2 0 01-2-2V4z M9 2v20',
  calendar: 'M8 2v4 M16 2v4 M3 8h18 M5 4h14a2 2 0 012 2v13a2 2 0 01-2 2H5a2 2 0 01-2-2V6a2 2 0 012-2z',
  video: 'M15 10l4.55-2.55A1 1 0 0121 8.4v7.2a1 1 0 01-1.45.9L15 14v-4z M3 8a2 2 0 012-2h8a2 2 0 012 2v8a2 2 0 01-2 2H5a2 2 0 01-2-2V8z',
  mail: 'M3 5h18v14H3z M3 6l9 7 9-7',
  globe: 'M12 2a10 10 0 100 20 10 10 0 000-20z M2 12h20 M12 2a15 15 0 010 20 15 15 0 010-20z',
  grid: 'M3 3h7v7H3z M14 3h7v7h-7z M3 14h7v7H3z M14 14h7v7h-7z',
  sparkle: 'M12 2l2.2 5.8L20 10l-5.8 2.2L12 18l-2.2-5.8L4 10l5.8-2.2z',
  search: 'M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z',
  chevRight: 'M9 18l6-6-6-6',
  chevDown: 'M6 9l6 6 6-6',
  x: 'M18 6L6 18 M6 6l12 12',
  settings: 'M12 15a3 3 0 100-6 3 3 0 000 6z M19.4 15a1.65 1.65 0 00.33 1.82l.06.06a2 2 0 11-2.83 2.83l-.06-.06a1.65 1.65 0 00-1.82-.33 1.65 1.65 0 00-1 1.51V21a2 2 0 11-4 0v-.09A1.65 1.65 0 009 19.4a1.65 1.65 0 00-1.82.33l-.06.06a2 2 0 11-2.83-2.83l.06-.06a1.65 1.65 0 00.33-1.82 1.65 1.65 0 00-1.51-1H3a2 2 0 110-4h.09A1.65 1.65 0 004.6 9a1.65 1.65 0 00-.33-1.82l-.06-.06a2 2 0 112.83-2.83l.06.06a1.65 1.65 0 001.82.33H9a1.65 1.65 0 001-1.51V3a2 2 0 114 0v.09a1.65 1.65 0 001 1.51 1.65 1.65 0 001.82-.33l.06-.06a2 2 0 112.83 2.83l-.06.06a1.65 1.65 0 00-.33 1.82V9a1.65 1.65 0 001.51 1H21a2 2 0 110 4h-.09a1.65 1.65 0 00-1.51 1z',
  info: 'M12 2a10 10 0 100 20 10 10 0 000-20z M12 16v-4 M12 8h.01',
  logout: 'M9 21H5a2 2 0 01-2-2V5a2 2 0 012-2h4 M16 17l5-5-5-5 M21 12H9'
};
function Icon({
  name,
  size = 18,
  color = 'currentColor',
  strokeWidth = 1.5,
  fill = 'none'
}) {
  const d = PATHS[name] || PATHS.file;
  return /*#__PURE__*/React.createElement("svg", {
    width: size,
    height: size,
    viewBox: "0 0 24 24",
    fill: fill,
    stroke: color,
    strokeWidth: strokeWidth,
    strokeLinecap: "round",
    strokeLinejoin: "round"
  }, d.split(' M').map((seg, i) => /*#__PURE__*/React.createElement("path", {
    key: i,
    d: i === 0 ? seg : 'M' + seg
  })));
}

/* ── MCAIT seal (the "Mc 8" monogram) ────────────────────────────── */
function Seal({
  size = 30,
  radius = 8
}) {
  return /*#__PURE__*/React.createElement("div", {
    style: {
      width: size,
      height: size,
      borderRadius: radius,
      background: 'var(--mc-gold)',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      flexShrink: 0
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: 'var(--font-display)',
      fontWeight: 800,
      color: 'var(--mc-gold-fg)',
      letterSpacing: '0.5px',
      lineHeight: 1.05,
      display: 'flex',
      flexDirection: 'column',
      alignItems: 'center'
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: size * 0.27
    }
  }, "Mc"), /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: size * 0.34
    }
  }, "8")));
}
function Avatar({
  name = '',
  size = 28
}) {
  const initials = name.split(' ').filter(Boolean).slice(0, 2).map(w => w[0].toUpperCase()).join('');
  return /*#__PURE__*/React.createElement("span", {
    style: {
      width: size,
      height: size,
      borderRadius: '50%',
      background: 'oklch(0.88 0.09 80)',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      flexShrink: 0,
      fontSize: size * 0.4,
      fontWeight: 700,
      color: 'oklch(0.32 0.08 80)',
      fontFamily: 'var(--font-sans)',
      userSelect: 'none'
    }
  }, initials);
}

/* ════════════════════════════════════════════════════════════════
   MCAITWidget — the shared identity cluster that lives on the right
   of every MCAIT product's app bar: M8 seal · Cowork · Apps · You.
   ════════════════════════════════════════════════════════════════ */
function MCAITWidget({
  apps = MCAIT_APPS,
  activeApp,
  user = {
    name: 'Omar Al-Amin',
    email: 'omar@mcait.com'
  },
  onNavigate,
  showSeal = true
}) {
  const [open, setOpen] = useState(null); // 'cowork' | 'apps' | 'user' | null
  const toggle = k => setOpen(o => o === k ? null : k);
  const close = () => setOpen(null);
  const iconBtn = (key, child, title, activeBg) => /*#__PURE__*/React.createElement("button", {
    title: title,
    onClick: () => toggle(key),
    style: {
      width: 32,
      height: 32,
      borderRadius: 8,
      border: 'none',
      cursor: 'pointer',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      background: open === key ? activeBg || 'var(--mc-canvas-2)' : 'none',
      transition: 'background var(--dur-fast, .15s)'
    },
    onMouseEnter: e => {
      if (open !== key) e.currentTarget.style.background = activeBg || 'var(--mc-canvas-2)';
    },
    onMouseLeave: e => {
      if (open !== key) e.currentTarget.style.background = 'none';
    }
  }, child);
  return /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'relative',
      display: 'flex',
      alignItems: 'center',
      gap: 2,
      background: 'var(--mc-canvas)',
      border: '1px solid var(--mc-border)',
      borderRadius: 'var(--radius-md)',
      padding: '4px 6px',
      flexShrink: 0,
      boxShadow: 'var(--shadow-sm)'
    }
  }, open && /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'fixed',
      inset: 0,
      zIndex: 299
    },
    onClick: close
  }), showSeal && /*#__PURE__*/React.createElement("div", {
    style: {
      width: 29,
      height: 32,
      borderRadius: 8,
      background: 'var(--mc-gold)',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      flexShrink: 0
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: 'var(--font-display)',
      fontWeight: 800,
      color: 'var(--mc-gold-fg)',
      letterSpacing: '0.5px',
      lineHeight: 1.05,
      display: 'flex',
      flexDirection: 'column',
      alignItems: 'center'
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 8
    }
  }, "Mc"), /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 10
    }
  }, "8"))), showSeal && /*#__PURE__*/React.createElement("div", {
    style: {
      width: 1,
      height: 18,
      background: 'var(--mc-border)',
      margin: '0 2px',
      flexShrink: 0
    }
  }), iconBtn('cowork', /*#__PURE__*/React.createElement(Icon, {
    name: "sparkle",
    size: 17,
    color: "var(--mc-gold)",
    fill: "var(--mc-gold)",
    strokeWidth: 0
  }), 'Cowork', 'var(--mc-gold-soft)'), open === 'cowork' && /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'absolute',
      top: '100%',
      right: 0,
      marginTop: 8,
      zIndex: 300,
      width: 320,
      background: 'var(--mc-surface)',
      border: '1px solid var(--mc-border)',
      borderRadius: 'var(--radius-xl)',
      boxShadow: 'var(--shadow-lg)',
      overflow: 'hidden'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      padding: '14px 16px',
      borderBottom: '1px solid var(--mc-border)',
      display: 'flex',
      alignItems: 'center',
      gap: 10,
      background: 'var(--mc-gold-soft)'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      width: 28,
      height: 28,
      borderRadius: 7,
      background: 'var(--mc-gold)',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      flexShrink: 0
    }
  }, /*#__PURE__*/React.createElement(Icon, {
    name: "sparkle",
    size: 14,
    color: "var(--mc-gold-fg)",
    fill: "var(--mc-gold-fg)",
    strokeWidth: 0
  })), /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: 'var(--font-display)',
      fontWeight: 700,
      fontSize: 14,
      color: 'var(--mc-gold-ink)',
      letterSpacing: '-0.01em'
    }
  }, "Cowork"), /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 10,
      color: 'var(--mc-muted)'
    }
  }, "Your agentic workspace assistant")), /*#__PURE__*/React.createElement("button", {
    onClick: close,
    style: {
      background: 'none',
      border: 'none',
      cursor: 'pointer',
      padding: 4,
      display: 'flex'
    }
  }, /*#__PURE__*/React.createElement(Icon, {
    name: "x",
    size: 14,
    color: "var(--mc-faint)"
  }))), /*#__PURE__*/React.createElement("div", {
    style: {
      padding: '10px 12px',
      display: 'flex',
      gap: 8,
      alignItems: 'center'
    }
  }, /*#__PURE__*/React.createElement("input", {
    placeholder: "Ask Cowork anything\u2026",
    style: {
      flex: 1,
      border: '1px solid var(--mc-border)',
      borderRadius: 'var(--radius-sm)',
      padding: '8px 12px',
      fontSize: 13,
      fontFamily: 'var(--font-sans)',
      outline: 'none',
      background: 'var(--mc-canvas-2)',
      caretColor: 'var(--mc-gold)'
    },
    onFocus: e => e.target.style.borderColor = 'var(--mc-gold-line)',
    onBlur: e => e.target.style.borderColor = 'var(--mc-border)'
  }), /*#__PURE__*/React.createElement("button", {
    style: {
      width: 34,
      height: 34,
      borderRadius: 'var(--radius-sm)',
      background: 'var(--mc-gold)',
      border: 'none',
      cursor: 'pointer',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      flexShrink: 0
    }
  }, /*#__PURE__*/React.createElement(Icon, {
    name: "chevRight",
    size: 15,
    color: "var(--mc-gold-fg)",
    strokeWidth: 2
  })))), iconBtn('apps', /*#__PURE__*/React.createElement(Icon, {
    name: "grid",
    size: 17,
    color: "var(--mc-faint)"
  }), 'MCAIT apps'), open === 'apps' && /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'absolute',
      top: '100%',
      right: 0,
      marginTop: 8,
      zIndex: 300,
      width: 276,
      background: 'var(--mc-surface)',
      border: '1px solid var(--mc-border)',
      borderRadius: 'var(--radius-xl)',
      boxShadow: 'var(--shadow-lg)',
      padding: 16
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 10,
      fontWeight: 600,
      color: 'var(--mc-muted)',
      letterSpacing: '0.06em',
      textTransform: 'uppercase',
      marginBottom: 12
    }
  }, "MCAIT workspace"), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'grid',
      gridTemplateColumns: 'repeat(3,1fr)',
      gap: 2
    }
  }, apps.map(app => /*#__PURE__*/React.createElement("button", {
    key: app.id,
    onClick: () => {
      onNavigate && onNavigate(app.id);
      close();
    },
    style: {
      display: 'flex',
      flexDirection: 'column',
      alignItems: 'center',
      gap: 5,
      padding: '8px 4px',
      borderRadius: 'var(--radius-md)',
      background: 'none',
      border: 'none',
      cursor: 'pointer'
    },
    onMouseEnter: e => e.currentTarget.style.background = 'var(--mc-canvas-2)',
    onMouseLeave: e => e.currentTarget.style.background = 'none'
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      width: 36,
      height: 36,
      borderRadius: 9,
      background: app.color,
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      boxShadow: 'var(--shadow-sm)'
    }
  }, /*#__PURE__*/React.createElement(Icon, {
    name: app.icon,
    size: 18,
    color: app.iconColor || '#fff',
    strokeWidth: 1.5
  })), /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 11,
      fontWeight: app.id === activeApp ? 600 : 400,
      color: app.id === activeApp ? 'var(--mc-accent)' : 'var(--mc-ink-soft)'
    }
  }, app.name))))), /*#__PURE__*/React.createElement("button", {
    onClick: () => toggle('user'),
    style: {
      background: 'none',
      border: 'none',
      cursor: 'pointer',
      borderRadius: '50%',
      padding: 2,
      display: 'flex'
    }
  }, /*#__PURE__*/React.createElement(Avatar, {
    name: user.name,
    size: 28
  })), open === 'user' && /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'absolute',
      top: '100%',
      right: 0,
      marginTop: 8,
      zIndex: 300,
      width: 264,
      background: 'var(--mc-surface)',
      border: '1px solid var(--mc-border)',
      borderRadius: 'var(--radius-xl)',
      boxShadow: 'var(--shadow-lg)',
      overflow: 'hidden'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      padding: 20,
      display: 'flex',
      flexDirection: 'column',
      alignItems: 'center',
      gap: 10,
      borderBottom: '1px solid var(--mc-border)',
      background: 'var(--mc-canvas)'
    }
  }, /*#__PURE__*/React.createElement(Avatar, {
    name: user.name,
    size: 60
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      textAlign: 'center'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 15,
      fontWeight: 600,
      color: 'var(--mc-ink)'
    }
  }, user.name), /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 12,
      color: 'var(--mc-muted)',
      fontFamily: 'var(--font-mono)',
      marginTop: 2
    }
  }, user.email))), [{
    label: 'Manage your account',
    icon: 'settings'
  }, {
    label: 'Settings & preferences',
    icon: 'settings'
  }, {
    label: 'Privacy & terms',
    icon: 'info'
  }].map(({
    label,
    icon
  }) => /*#__PURE__*/React.createElement("button", {
    key: label,
    style: {
      width: '100%',
      display: 'flex',
      alignItems: 'center',
      gap: 10,
      padding: '10px 16px',
      background: 'none',
      border: 'none',
      cursor: 'pointer',
      fontSize: 13,
      fontFamily: 'var(--font-sans)',
      color: 'var(--mc-ink-soft)',
      textAlign: 'left'
    },
    onMouseEnter: e => e.currentTarget.style.background = 'var(--mc-canvas-2)',
    onMouseLeave: e => e.currentTarget.style.background = 'none'
  }, /*#__PURE__*/React.createElement(Icon, {
    name: icon,
    size: 15,
    color: "var(--mc-faint)"
  }), label)), /*#__PURE__*/React.createElement("div", {
    style: {
      height: 1,
      background: 'var(--mc-border)'
    }
  }), /*#__PURE__*/React.createElement("button", {
    style: {
      width: '100%',
      display: 'flex',
      alignItems: 'center',
      gap: 10,
      padding: '10px 16px',
      background: 'none',
      border: 'none',
      cursor: 'pointer',
      fontSize: 13,
      fontFamily: 'var(--font-sans)',
      color: 'var(--mc-ink-soft)',
      textAlign: 'left'
    },
    onMouseEnter: e => e.currentTarget.style.background = 'var(--mc-canvas-2)',
    onMouseLeave: e => e.currentTarget.style.background = 'none'
  }, /*#__PURE__*/React.createElement(Icon, {
    name: "logout",
    size: 15,
    color: "var(--mc-faint)"
  }), "Sign out")));
}

/* ════════════════════════════════════════════════════════════════
   AppBar — the standard MCAIT product top bar.
   Branded product mark on the left, optional center slot (search /
   controls), and the shared MCAITWidget identity cluster on the right.
   ════════════════════════════════════════════════════════════════ */
function AppBar({
  product = {
    id: 'cowork',
    name: 'Cowork',
    icon: 'sparkle'
  },
  children,
  user,
  onNavigate,
  divider = true,
  style: extra = {}
}) {
  const goldProduct = product.id === 'cowork';
  return /*#__PURE__*/React.createElement("header", {
    "data-product": product.id,
    style: {
      height: 52,
      background: 'var(--mc-surface)',
      borderBottom: divider ? '1px solid var(--mc-border)' : 'none',
      display: 'flex',
      alignItems: 'center',
      padding: '0 12px',
      gap: 10,
      flexShrink: 0,
      ...extra
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      alignItems: 'center',
      gap: 7,
      flexShrink: 0
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      width: 28,
      height: 28,
      borderRadius: 7,
      background: goldProduct ? 'var(--mc-gold)' : 'var(--mc-accent)',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center'
    }
  }, /*#__PURE__*/React.createElement(Icon, {
    name: product.icon || 'folder',
    size: 14,
    color: goldProduct ? 'var(--mc-gold-fg)' : '#fff',
    fill: product.icon === 'sparkle' ? goldProduct ? 'var(--mc-gold-fg)' : '#fff' : 'none',
    strokeWidth: product.icon === 'sparkle' ? 0 : 1.75
  })), /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 14,
      fontWeight: 700,
      color: goldProduct ? 'var(--mc-gold-ink)' : 'var(--mc-accent)',
      fontFamily: 'var(--font-display)',
      letterSpacing: '-0.02em'
    }
  }, product.name)), /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1,
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      minWidth: 0
    }
  }, children), /*#__PURE__*/React.createElement(MCAITWidget, {
    activeApp: product.id,
    user: user,
    onNavigate: onNavigate
  }));
}
Object.assign(__ds_scope, { MCAIT_APPS, Seal, MCAITWidget, AppBar });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/core/AppBar.jsx", error: String((e && e.message) || e) }); }

// components/core/Avatar.jsx
try { (() => {
const SIZE_MAP = {
  xs: {
    size: 20,
    font: 9,
    radius: 6
  },
  sm: {
    size: 28,
    font: 11,
    radius: 8
  },
  md: {
    size: 36,
    font: 14,
    radius: 10
  },
  lg: {
    size: 48,
    font: 18,
    radius: 12
  },
  xl: {
    size: 64,
    font: 22,
    radius: 16
  }
};
function initials(name = '') {
  return name.split(' ').filter(Boolean).slice(0, 2).map(w => w[0].toUpperCase()).join('');
}

// Deterministic hue from name string
function hueFromName(name = '') {
  let h = 0;
  for (let i = 0; i < name.length; i++) h = h * 31 + name.charCodeAt(i) & 0xffffffff;
  return Math.abs(h) % 360;
}
function Avatar({
  name,
  src,
  size = 'md',
  style: extra = {}
}) {
  const s = SIZE_MAP[size] || SIZE_MAP.md;
  const hue = hueFromName(name);
  const bg = `oklch(0.88 0.09 ${hue})`;
  const fg = `oklch(0.32 0.08 ${hue})`;
  return /*#__PURE__*/React.createElement("span", {
    style: {
      display: 'inline-flex',
      alignItems: 'center',
      justifyContent: 'center',
      width: s.size,
      height: s.size,
      borderRadius: s.radius,
      background: src ? 'transparent' : bg,
      overflow: 'hidden',
      flexShrink: 0,
      fontFamily: 'var(--font-sans)',
      fontWeight: 'var(--weight-bold)',
      fontSize: s.font,
      color: fg,
      userSelect: 'none',
      border: '1.5px solid oklch(1 0 0 / 0.5)',
      ...extra
    }
  }, src ? /*#__PURE__*/React.createElement("img", {
    src: src,
    alt: name,
    style: {
      width: '100%',
      height: '100%',
      objectFit: 'cover'
    }
  }) : initials(name));
}
Object.assign(__ds_scope, { Avatar });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/core/Avatar.jsx", error: String((e && e.message) || e) }); }

// components/core/Badge.jsx
try { (() => {
const VARIANT_STYLES = {
  default: {
    bg: 'var(--mc-canvas-2)',
    color: 'var(--mc-ink-soft)',
    border: 'var(--mc-border)'
  },
  primary: {
    bg: 'var(--mc-accent-soft)',
    color: 'var(--mc-accent-ink)',
    border: 'var(--mc-accent-line)'
  },
  success: {
    bg: 'var(--mc-success-soft)',
    color: 'var(--mc-success)',
    border: 'var(--mc-success-line)'
  },
  warning: {
    bg: 'var(--mc-warning-soft)',
    color: 'var(--mc-warning)',
    border: 'var(--mc-warning-line)'
  },
  danger: {
    bg: 'var(--mc-danger-soft)',
    color: 'var(--mc-danger)',
    border: 'var(--mc-danger-line)'
  },
  info: {
    bg: 'var(--mc-info-soft)',
    color: 'var(--mc-info)',
    border: 'var(--mc-info-line)'
  },
  gold: {
    bg: 'var(--mc-gold-soft)',
    color: 'var(--mc-gold-ink)',
    border: 'var(--mc-gold-line)'
  },
  solid: {
    bg: 'var(--mc-accent)',
    color: 'var(--mc-accent-fg)',
    border: 'transparent'
  }
};
const DOT_COLORS = {
  default: 'var(--mc-faint)',
  primary: 'var(--mc-accent)',
  success: 'var(--mc-success)',
  warning: 'var(--mc-warning)',
  danger: 'var(--mc-danger)',
  info: 'var(--mc-info)',
  gold: 'var(--mc-gold)',
  solid: 'var(--mc-accent-fg)'
};
function Badge({
  children,
  variant = 'default',
  dot = false,
  size = 'md',
  style: extra = {}
}) {
  const v = VARIANT_STYLES[variant] || VARIANT_STYLES.default;
  const sz = size === 'sm' ? {
    fontSize: '10px',
    padding: '2px 7px'
  } : {
    fontSize: 'var(--text-xs)',
    padding: '3px 9px'
  };
  return /*#__PURE__*/React.createElement("span", {
    style: {
      display: 'inline-flex',
      alignItems: 'center',
      gap: '5px',
      borderRadius: 'var(--radius-pill)',
      border: `1px solid ${v.border}`,
      background: v.bg,
      color: v.color,
      fontFamily: 'var(--font-sans)',
      fontWeight: 'var(--weight-semibold)',
      lineHeight: 1,
      whiteSpace: 'nowrap',
      ...sz,
      ...extra
    }
  }, dot && /*#__PURE__*/React.createElement("span", {
    style: {
      width: '6px',
      height: '6px',
      borderRadius: '50%',
      background: DOT_COLORS[variant] || DOT_COLORS.default,
      flexShrink: 0
    }
  }), children);
}
Object.assign(__ds_scope, { Badge });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/core/Badge.jsx", error: String((e && e.message) || e) }); }

// components/core/Button.jsx
try { (() => {
const {
  useState
} = React;
const BASE = {
  display: 'inline-flex',
  alignItems: 'center',
  justifyContent: 'center',
  gap: '6px',
  fontFamily: 'var(--font-sans)',
  fontWeight: 'var(--weight-semibold)',
  borderRadius: 'var(--radius-md)',
  border: 'none',
  cursor: 'pointer',
  transition: 'background 0.16s, box-shadow 0.16s, transform 0.12s',
  textDecoration: 'none',
  whiteSpace: 'nowrap',
  lineHeight: 1
};
const SIZE = {
  sm: {
    fontSize: 'var(--text-xs)',
    padding: '6px 12px',
    height: '28px'
  },
  md: {
    fontSize: 'var(--text-sm)',
    padding: '8px 16px',
    height: '34px'
  },
  lg: {
    fontSize: 'var(--text-base)',
    padding: '10px 20px',
    height: '40px'
  }
};
const VARIANT = {
  primary: {
    background: 'var(--mc-accent)',
    color: 'var(--mc-accent-fg)',
    hover: {
      background: 'var(--mc-accent-hover)'
    }
  },
  secondary: {
    background: 'var(--mc-canvas-2)',
    color: 'var(--mc-ink-soft)',
    border: '1px solid var(--mc-border)',
    hover: {
      background: 'var(--mc-border)'
    }
  },
  ghost: {
    background: 'transparent',
    color: 'var(--mc-ink-soft)',
    hover: {
      background: 'var(--mc-canvas-2)'
    }
  },
  destructive: {
    background: 'var(--mc-danger-soft)',
    color: 'var(--mc-danger)',
    border: '1px solid var(--mc-danger-line)',
    hover: {
      background: 'var(--mc-danger)',
      color: '#fff'
    }
  },
  brand: {
    background: 'var(--mc-gold)',
    color: 'var(--mc-gold-fg)',
    hover: {
      background: 'var(--mc-gold-hover)'
    }
  }
};
function Button({
  children,
  variant = 'primary',
  size = 'md',
  disabled = false,
  loading = false,
  fullWidth = false,
  onClick,
  type = 'button',
  style: extraStyle = {}
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
    ...extraStyle
  };
  return /*#__PURE__*/React.createElement("button", {
    type: type,
    style: computed,
    disabled: disabled || loading,
    onClick: onClick,
    onMouseEnter: () => setHovered(true),
    onMouseLeave: () => {
      setHovered(false);
      setPressed(false);
    },
    onMouseDown: () => setPressed(true),
    onMouseUp: () => setPressed(false)
  }, loading && /*#__PURE__*/React.createElement("svg", {
    width: "14",
    height: "14",
    viewBox: "0 0 14 14",
    fill: "none",
    style: {
      animation: 'spin 0.7s linear infinite'
    }
  }, /*#__PURE__*/React.createElement("circle", {
    cx: "7",
    cy: "7",
    r: "5.5",
    stroke: "currentColor",
    strokeWidth: "1.5",
    strokeDasharray: "28",
    strokeDashoffset: "10",
    strokeLinecap: "round"
  }), /*#__PURE__*/React.createElement("style", null, `@keyframes spin { to { transform: rotate(360deg); } }`)), children);
}
Object.assign(__ds_scope, { Button });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/core/Button.jsx", error: String((e && e.message) || e) }); }

// components/core/Card.jsx
try { (() => {
const {
  useState
} = React;
function Card({
  children,
  padding = 'md',
  hover = false,
  onClick,
  style: extra = {}
}) {
  const [isHovered, setIsHovered] = useState(false);
  const p = {
    sm: '12px',
    md: '20px',
    lg: '28px'
  }[padding] || '20px';
  return /*#__PURE__*/React.createElement("div", {
    onClick: onClick,
    onMouseEnter: () => setIsHovered(true),
    onMouseLeave: () => setIsHovered(false),
    style: {
      background: 'var(--mc-surface)',
      borderRadius: 'var(--radius-lg)',
      border: '1px solid var(--mc-border)',
      boxShadow: hover && isHovered ? 'var(--shadow-md)' : 'var(--shadow-sm)',
      transform: hover && isHovered ? 'translateY(-1px)' : 'translateY(0)',
      transition: 'box-shadow 0.2s, transform 0.2s',
      padding: p,
      cursor: onClick ? 'pointer' : undefined,
      ...extra
    }
  }, children);
}
function CardHeader({
  children,
  style: extra = {}
}) {
  return /*#__PURE__*/React.createElement("div", {
    style: {
      paddingBottom: '14px',
      marginBottom: '14px',
      borderBottom: '1px solid var(--mc-border)',
      ...extra
    }
  }, children);
}
function CardTitle({
  children,
  style: extra = {}
}) {
  return /*#__PURE__*/React.createElement("h3", {
    style: {
      margin: 0,
      fontSize: 'var(--text-md)',
      fontWeight: 'var(--weight-semibold)',
      color: 'var(--mc-ink)',
      fontFamily: 'var(--font-sans)',
      ...extra
    }
  }, children);
}
function CardFooter({
  children,
  style: extra = {}
}) {
  return /*#__PURE__*/React.createElement("div", {
    style: {
      paddingTop: '14px',
      marginTop: '14px',
      borderTop: '1px solid var(--mc-border)',
      display: 'flex',
      gap: '8px',
      alignItems: 'center',
      ...extra
    }
  }, children);
}
Object.assign(__ds_scope, { Card, CardHeader, CardTitle, CardFooter });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/core/Card.jsx", error: String((e && e.message) || e) }); }

// components/core/Input.jsx
try { (() => {
const {
  useState
} = React;
function Input({
  label,
  placeholder,
  value,
  onChange,
  type = 'text',
  error,
  hint,
  disabled = false,
  prefix,
  suffix,
  style: extra = {}
}) {
  const [focused, setFocused] = useState(false);
  const borderColor = error ? 'var(--mc-danger-line)' : focused ? 'var(--mc-accent-line)' : 'var(--mc-border)';
  const shadow = focused ? 'var(--shadow-focus)' : 'none';
  return /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      flexDirection: 'column',
      gap: '5px',
      fontFamily: 'var(--font-sans)',
      ...extra
    }
  }, label && /*#__PURE__*/React.createElement("label", {
    style: {
      fontSize: 'var(--text-xs)',
      fontWeight: 'var(--weight-semibold)',
      color: 'var(--mc-ink-soft)'
    }
  }, label), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      alignItems: 'center',
      gap: '8px',
      border: `1px solid ${borderColor}`,
      borderRadius: 'var(--radius-sm)',
      background: disabled ? 'var(--mc-canvas-2)' : 'var(--mc-surface)',
      padding: '0 12px',
      height: '36px',
      boxShadow: shadow,
      transition: 'border-color 0.16s, box-shadow 0.16s'
    }
  }, prefix && /*#__PURE__*/React.createElement("span", {
    style: {
      color: 'var(--mc-faint)',
      display: 'flex',
      alignItems: 'center'
    }
  }, prefix), /*#__PURE__*/React.createElement("input", {
    type: type,
    value: value,
    onChange: onChange,
    placeholder: placeholder,
    disabled: disabled,
    onFocus: () => setFocused(true),
    onBlur: () => setFocused(false),
    style: {
      flex: 1,
      border: 'none',
      outline: 'none',
      background: 'transparent',
      fontFamily: 'var(--font-sans)',
      fontSize: 'var(--text-sm)',
      color: 'var(--mc-ink)',
      caretColor: 'var(--mc-accent)'
    }
  }), suffix && /*#__PURE__*/React.createElement("span", {
    style: {
      color: 'var(--mc-faint)',
      display: 'flex',
      alignItems: 'center'
    }
  }, suffix)), (error || hint) && /*#__PURE__*/React.createElement("p", {
    style: {
      fontSize: 'var(--text-xs)',
      color: error ? 'var(--mc-danger)' : 'var(--mc-muted)',
      margin: 0
    }
  }, error || hint));
}
Object.assign(__ds_scope, { Input });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/core/Input.jsx", error: String((e && e.message) || e) }); }

// components/core/Sidebar.jsx
try { (() => {
const {
  useState
} = React;
/* ── Lucide-style icons (currentColor, 1.5 stroke) ───────────────── */
const PATHS = {
  folder: 'M2 6a2 2 0 012-2h4l2 2h6a2 2 0 012 2v8a2 2 0 01-2 2H4a2 2 0 01-2-2V6z',
  users: 'M17 21v-2a4 4 0 00-4-4H5a4 4 0 00-4 4v2 M23 21v-2a4 4 0 00-3-3.87 M16 3.13a4 4 0 010 7.75 M9 11a4 4 0 100-8 4 4 0 000 8z',
  clock: 'M12 2a10 10 0 110 20A10 10 0 0112 2zm0 4v6l4 2',
  star: 'M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z',
  trash: 'M3 6h18 M19 6l-1 14a2 2 0 01-2 2H8a2 2 0 01-2-2L5 6 M8 6V4a2 2 0 012-2h4a2 2 0 012 2v2',
  plus: 'M12 5v14 M5 12h14',
  chevLeft: 'M15 18l-6-6 6-6',
  chevRight: 'M9 18l6-6-6-6'
};
function Icon({
  name,
  size = 18,
  color = 'currentColor',
  strokeWidth = 1.5
}) {
  const d = PATHS[name] || PATHS.folder;
  return /*#__PURE__*/React.createElement("svg", {
    width: size,
    height: size,
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: color,
    strokeWidth: strokeWidth,
    strokeLinecap: "round",
    strokeLinejoin: "round",
    style: {
      flexShrink: 0
    }
  }, d.split(' M').map((seg, i) => /*#__PURE__*/React.createElement("path", {
    key: i,
    d: i === 0 ? seg : 'M' + seg
  })));
}

/* ════════════════════════════════════════════════════════════════
   Sidebar — collapsible product navigation rail. Optional featured
   "volume" card at the top (name · badge · usage meter), a list of
   nav items, and a collapse/expand toggle pinned to the bottom.
   Rounds its top-right corner by default so it tucks under the app bar.
   ════════════════════════════════════════════════════════════════ */
function Sidebar({
  items = [],
  active,
  onNavigate,
  volume,
  label = 'Volumes',
  collapsed: collapsedProp,
  defaultCollapsed = false,
  onToggle,
  roundedCorner = 'top-right',
  style: extra = {}
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
  const corners = roundedCorner === 'top-right' ? {
    borderTopRightRadius: radius
  } : roundedCorner === 'top-left' ? {
    borderTopLeftRadius: radius
  } : roundedCorner === 'right' ? {
    borderTopRightRadius: radius,
    borderBottomRightRadius: radius
  } : roundedCorner === 'none' ? {} : {
    borderTopRightRadius: radius
  };
  const volActive = volume && (active === volume.id || active === undefined);
  return /*#__PURE__*/React.createElement("aside", {
    style: {
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
      ...extra
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1,
      overflowY: 'auto',
      overflowX: 'hidden',
      padding: collapsed ? '12px 10px' : '16px 12px'
    }
  }, volume && /*#__PURE__*/React.createElement(React.Fragment, null, !collapsed && /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 11,
      fontWeight: 'var(--weight-semibold)',
      color: 'var(--mc-muted)',
      letterSpacing: '0.07em',
      textTransform: 'uppercase',
      padding: '0 4px 8px'
    }
  }, label), /*#__PURE__*/React.createElement("div", {
    onClick: () => onNavigate && onNavigate(volume.id),
    title: collapsed ? volume.name : undefined,
    style: {
      display: 'flex',
      flexDirection: collapsed ? 'row' : 'column',
      gap: collapsed ? 0 : 10,
      alignItems: collapsed ? 'center' : 'stretch',
      justifyContent: 'center',
      padding: collapsed ? 0 : '12px 14px',
      width: collapsed ? 44 : 'auto',
      height: collapsed ? 44 : 'auto',
      margin: collapsed ? '0 auto' : 0,
      borderRadius: collapsed ? 'var(--radius-md)' : 'var(--radius-lg)',
      cursor: 'pointer',
      background: volActive ? 'var(--mc-accent-soft)' : 'transparent',
      border: `1px solid ${volActive ? 'var(--mc-accent-line)' : 'transparent'}`,
      transition: 'background 0.13s, border-color 0.13s'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      alignItems: 'center',
      gap: 10,
      width: '100%',
      justifyContent: collapsed ? 'center' : 'flex-start'
    }
  }, /*#__PURE__*/React.createElement(Icon, {
    name: volume.icon || 'folder',
    size: collapsed ? 19 : 17,
    color: volActive ? 'var(--mc-accent)' : 'var(--mc-faint)',
    strokeWidth: 1.75
  }), !collapsed && /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement("span", {
    style: {
      flex: 1,
      fontSize: 14,
      fontWeight: 'var(--weight-semibold)',
      color: volActive ? 'var(--mc-accent-ink)' : 'var(--mc-ink)',
      whiteSpace: 'nowrap',
      overflow: 'hidden',
      textOverflow: 'ellipsis'
    }
  }, volume.name), volume.badge && /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 10,
      fontFamily: 'var(--font-mono)',
      color: 'var(--mc-muted)',
      background: 'var(--mc-canvas-2)',
      border: '1px solid var(--mc-border)',
      borderRadius: 4,
      padding: '1px 6px',
      flexShrink: 0
    }
  }, volume.badge))), !collapsed && volume.pct != null && /*#__PURE__*/React.createElement("div", {
    style: {
      width: '100%'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      height: 4,
      borderRadius: 99,
      background: 'var(--mc-canvas-2)',
      overflow: 'hidden'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      height: '100%',
      width: `${volume.pct}%`,
      background: 'var(--mc-accent)',
      borderRadius: 99,
      transition: 'width 0.3s'
    }
  })), volume.usage && /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 11,
      fontFamily: 'var(--font-mono)',
      color: 'var(--mc-muted)',
      marginTop: 6
    }
  }, volume.usage))), /*#__PURE__*/React.createElement("div", {
    style: {
      height: 1,
      background: 'var(--mc-border)',
      margin: collapsed ? '12px 6px' : '14px 4px'
    }
  })), /*#__PURE__*/React.createElement("nav", {
    style: {
      display: 'flex',
      flexDirection: 'column',
      gap: 2
    }
  }, items.map(n => {
    const isActive = active === n.id;
    const isHover = hovered === n.id;
    return /*#__PURE__*/React.createElement("div", {
      key: n.id,
      onClick: () => onNavigate && onNavigate(n.id),
      onMouseEnter: () => setHovered(n.id),
      onMouseLeave: () => setHovered(null),
      title: collapsed ? n.label : undefined,
      style: {
        display: 'flex',
        alignItems: 'center',
        gap: 11,
        justifyContent: collapsed ? 'center' : 'flex-start',
        padding: collapsed ? 0 : '9px 12px',
        width: collapsed ? 44 : 'auto',
        height: collapsed ? 44 : 'auto',
        margin: collapsed ? '0 auto' : 0,
        borderRadius: 'var(--radius-md)',
        cursor: 'pointer',
        background: isActive ? 'var(--mc-accent-soft)' : isHover ? 'var(--mc-canvas-2)' : 'transparent',
        color: isActive ? 'var(--mc-accent-ink)' : 'var(--mc-ink-soft)',
        transition: 'background 0.13s'
      }
    }, /*#__PURE__*/React.createElement(Icon, {
      name: n.icon,
      size: 18,
      color: isActive ? 'var(--mc-accent)' : 'var(--mc-faint)',
      strokeWidth: 1.5
    }), !collapsed && /*#__PURE__*/React.createElement("span", {
      style: {
        fontSize: 14,
        fontWeight: isActive ? 'var(--weight-semibold)' : 'var(--weight-medium)',
        whiteSpace: 'nowrap'
      }
    }, n.label));
  }))), /*#__PURE__*/React.createElement("div", {
    style: {
      borderTop: '1px solid var(--mc-border)',
      padding: 8,
      display: 'flex',
      justifyContent: collapsed ? 'center' : 'flex-end'
    }
  }, /*#__PURE__*/React.createElement("button", {
    onClick: toggle,
    title: collapsed ? 'Expand' : 'Collapse',
    "aria-label": collapsed ? 'Expand sidebar' : 'Collapse sidebar',
    style: {
      width: 32,
      height: 32,
      borderRadius: 'var(--radius-sm)',
      border: 'none',
      background: 'none',
      cursor: 'pointer',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      color: 'var(--mc-muted)',
      transition: 'background 0.13s'
    },
    onMouseEnter: e => e.currentTarget.style.background = 'var(--mc-canvas-2)',
    onMouseLeave: e => e.currentTarget.style.background = 'none'
  }, /*#__PURE__*/React.createElement(Icon, {
    name: collapsed ? 'chevRight' : 'chevLeft',
    size: 17,
    color: "var(--mc-faint)",
    strokeWidth: 2
  }))));
}
Object.assign(__ds_scope, { Sidebar });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/core/Sidebar.jsx", error: String((e && e.message) || e) }); }

// components/core/Switch.jsx
try { (() => {
const {
  useState
} = React;
function Switch({
  checked = false,
  onChange,
  label,
  disabled = false
}) {
  const [hovered, setHovered] = useState(false);
  return /*#__PURE__*/React.createElement("label", {
    style: {
      display: 'inline-flex',
      alignItems: 'center',
      gap: '10px',
      cursor: disabled ? 'not-allowed' : 'pointer',
      opacity: disabled ? 0.5 : 1,
      fontFamily: 'var(--font-sans)',
      fontSize: 'var(--text-sm)',
      color: 'var(--mc-ink-soft)',
      userSelect: 'none'
    }
  }, /*#__PURE__*/React.createElement("span", {
    role: "switch",
    "aria-checked": checked,
    onClick: () => !disabled && onChange && onChange(!checked),
    onMouseEnter: () => setHovered(true),
    onMouseLeave: () => setHovered(false),
    style: {
      width: '36px',
      height: '20px',
      borderRadius: '10px',
      flexShrink: 0,
      position: 'relative',
      background: checked ? 'var(--mc-accent)' : hovered ? 'var(--mc-border-strong)' : 'var(--mc-border)',
      transition: 'background 0.2s'
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      position: 'absolute',
      top: '3px',
      left: checked ? '19px' : '3px',
      width: '14px',
      height: '14px',
      borderRadius: '50%',
      background: '#fff',
      boxShadow: 'var(--shadow-sm)',
      transition: 'left 0.18s var(--ease-out)'
    }
  })), label);
}
Object.assign(__ds_scope, { Switch });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/core/Switch.jsx", error: String((e && e.message) || e) }); }

// components/core/Tabs.jsx
try { (() => {
const {
  useState
} = React;
function Tabs({
  tabs = [],
  activeIndex = 0,
  onChange,
  style: extra = {}
}) {
  return /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      gap: 0,
      borderBottom: '1px solid var(--mc-border)',
      fontFamily: 'var(--font-sans)',
      ...extra
    }
  }, tabs.map((tab, i) => {
    const active = i === activeIndex;
    return /*#__PURE__*/React.createElement("button", {
      key: i,
      onClick: () => onChange && onChange(i),
      style: {
        background: 'none',
        border: 'none',
        cursor: 'pointer',
        padding: '10px 16px',
        fontSize: 'var(--text-sm)',
        fontWeight: active ? 'var(--weight-semibold)' : 'var(--weight-medium)',
        color: active ? 'var(--mc-accent)' : 'var(--mc-muted)',
        borderBottom: active ? '2px solid var(--mc-accent)' : '2px solid transparent',
        marginBottom: '-1px',
        transition: 'color 0.15s',
        fontFamily: 'var(--font-sans)'
      }
    }, tab);
  }));
}
Object.assign(__ds_scope, { Tabs });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/core/Tabs.jsx", error: String((e && e.message) || e) }); }

__ds_ns.Alert = __ds_scope.Alert;

__ds_ns.MCAIT_APPS = __ds_scope.MCAIT_APPS;

__ds_ns.Seal = __ds_scope.Seal;

__ds_ns.MCAITWidget = __ds_scope.MCAITWidget;

__ds_ns.AppBar = __ds_scope.AppBar;

__ds_ns.Avatar = __ds_scope.Avatar;

__ds_ns.Badge = __ds_scope.Badge;

__ds_ns.Button = __ds_scope.Button;

__ds_ns.Card = __ds_scope.Card;

__ds_ns.CardHeader = __ds_scope.CardHeader;

__ds_ns.CardTitle = __ds_scope.CardTitle;

__ds_ns.CardFooter = __ds_scope.CardFooter;

__ds_ns.Input = __ds_scope.Input;

__ds_ns.Sidebar = __ds_scope.Sidebar;

__ds_ns.Switch = __ds_scope.Switch;

__ds_ns.Tabs = __ds_scope.Tabs;

})();
