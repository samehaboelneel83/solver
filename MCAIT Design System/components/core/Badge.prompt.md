/** Single-sentence: What & when — small status chip for labelling states, categories, or counts. */

```jsx
// Default
<Badge>Draft</Badge>

// With semantic color
<Badge variant="success" dot>Active</Badge>
<Badge variant="danger">Overdue</Badge>
<Badge variant="warning">Pending</Badge>
<Badge variant="info">Syncing</Badge>

// With product accent color
<Badge variant="primary">Drive</Badge>
<Badge variant="gold">MCAIT</Badge>

// Solid (filled accent)
<Badge variant="solid">New</Badge>

// Small
<Badge size="sm" variant="success">3</Badge>
```

Notable variants/props:
- `variant`: default | primary | success | warning | danger | info | gold | solid
- `dot`: prepends a small colored dot (good for status indicators)
- `size`: md (default) | sm
