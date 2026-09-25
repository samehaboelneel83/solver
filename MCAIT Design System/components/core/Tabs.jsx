import React, { useState } from 'react';

export function Tabs({ tabs = [], activeIndex = 0, onChange, style: extra = {} }) {
  return (
    <div style={{ display: 'flex', gap: 0, borderBottom: '1px solid var(--mc-border)', fontFamily: 'var(--font-sans)', ...extra }}>
      {tabs.map((tab, i) => {
        const active = i === activeIndex;
        return (
          <button
            key={i}
            onClick={() => onChange && onChange(i)}
            style={{
              background: 'none', border: 'none', cursor: 'pointer',
              padding: '10px 16px', fontSize: 'var(--text-sm)',
              fontWeight: active ? 'var(--weight-semibold)' : 'var(--weight-medium)',
              color: active ? 'var(--mc-accent)' : 'var(--mc-muted)',
              borderBottom: active ? '2px solid var(--mc-accent)' : '2px solid transparent',
              marginBottom: '-1px', transition: 'color 0.15s',
              fontFamily: 'var(--font-sans)',
            }}
          >
            {tab}
          </button>
        );
      })}
    </div>
  );
}
