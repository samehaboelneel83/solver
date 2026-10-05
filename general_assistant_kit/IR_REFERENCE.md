# Problem Solver modelling vocabulary

This is the platform's own language for a model. Every construct below was checked with `POST /api/v1/problems/{id}/versions/validate` on this install. Set names are placeholders: replace `item`, `group` and the others with the kinds of record in the workspace.

## Data side

| Platform word | Meaning | Created from |
| --- | --- | --- |
| Kind of record (entity type) | A set of things: `item`, `site`, `shift` | A spreadsheet sheet, a CSV, or map features ("Make records") |
| Attribute | A number, text, enum, date or geometry on each record | Spreadsheet columns |
| Relationship type | A link `from_kind -> to_kind`, for example `item_group` | A two-column sheet: `from key`, `to key` |
| Data value (parameter) | A named number, plain or per record (`entity`, `index`) | The Data values page. It must exist before a model reads it |
| Shape | A geometry attribute; makes records and run answers show on the map | "Add shapes to records I have" |

## Model side (IR, version 2)

```json
{
  "version": 2,
  "sets": ["item", "group"],
  "relationships": ["item_group"],
  "variables": {
    "pick":  {"index": ["item"],  "domain": "binary"},
    "count": {"index": ["group"], "domain": "integer", "lower": 0, "upper": 1000}
  },
  "parameters": {},
  "constraints": [],
  "objective": {"mode": "lex", "sense": "maximize", "terms": []}
}
```

- **`domain`** is `binary`, `integer` or `continuous`. `lower` and `upper` are optional bounds.
- **`parameters`** lists only data values that already exist in the workspace. Their declaration keys are `entity`, `index` and `uncertainty`; `default` is refused. A plain number in a rule is written `{"const": 2000}`.

### Expressions

| Form | Example |
| --- | --- |
| variable | `{"var": "pick", "index": ["i"]}` |
| constant | `{"const": 1}` |
| data value | `{"par": "budget", "index": []}` |
| attribute of the bound record | `{"attr": {"of": "i", "name": "weight_kg"}}` |
| sum over a set | `{"sum": <expr>, "over": [{"set": "item", "index": "i"}]}` |
| sum over the records linked to `g` | `{"sum": <expr>, "over": [{"set": "item", "index": "i", "via": {"rel": "item_group", "to": "g"}}]}` |
| sum over the records `a` links to | `"via": {"rel": "from", "from": "a"}` |
| add, multiply | `{"add": [e1, e2]}`, `{"mul": [e1, e2]}` (keep products linear: a variable times a constant, data value or attribute) |

### Rules (constraints)

```json
{"id": "one_per_group",
 "forall": [{"set": "group", "index": "g"}],
 "left":  {"sum": {"var": "pick", "index": ["i"]}, "over": [{"set": "item", "index": "i", "via": {"rel": "item_group", "to": "g"}}]},
 "relation": "=", "right": {"const": 1},
 "severity": "hard"}
```

- **`id`** must match `^[a-z][a-z0-9_]*$`, for example `big_m`; `bigM` is refused. Term ids follow the same rule.
- **`relation`** is `<=`, `>=` or `=`.
- **`severity`** is `hard`, or `soft` with a `"weight"`, which pays a price instead of failing.
- **Filter a `forall`:** `{"set": "site", "index": "s", "where": [{"attr": "is_active", "op": "=", "value": 1}]}`. The attribute name is used alone, without the `s.` prefix.

### Goals

- **Lexicographic:** `"objective": {"mode": "lex", "sense": "maximize", "terms": [{"id": "served", "weight": 1, "expression": ...}, {"id": "cost", "weight": -1, "expression": ...}]}`. Terms are solved in order. A negative weight means "less is better" inside a maximize.
- **Weighted sum:** `"mode": "weighted"` with `"sense"` set to `"minimize"` or `"maximize"`.

## General patterns

The patterns are written with placeholder names. Each one is a building block, not a template for one problem.

1. **Choose one per group** (assignment, picking a variant). This is the rule shown above, with `pick[item]` binary.
2. **Capacity or budget.**
   `{"sum": {"mul": [{"var": "pick", "index": ["i"]}, {"attr": {"of": "i", "name": "cost"}}]}, "over": [{"set": "item", "index": "i"}]} <= {"par": "budget", "index": []}`
3. **Cover every demand.** For each `demand d`, take the sum of `open[site]` over the sites linked by `covers`, and require `>= 1`.
4. **One user per shared resource** (no overlap, packing). For each `resource r`, the sum of `use[thing]` over things linked to `r` by `occupies` must be `<= 1`, or `<= capacity`.
5. **Link a use to an opening.** `x[i] <= M * y[j]` is written `{"var": "x"} <= {"mul": [{"const": M}, {"var": "y"}]}`, with M as small as is valid.
6. **Connectivity and access.** Use flow on arcs `node -> node`:
   - inflow plus source equals outflow plus `use[node]`
   - flow only through used nodes (`flow <= M * use`)
   - sources at the entrances

   This proves every used node can be reached.
7. **Real geometry.** Generate candidate pieces at their real size with `run_python`: its position, the resources it occupies, and its neighbours. Import them as records and relationships, then use patterns 4 and 6. Pick a grid step that divides every real dimension. Never round a size to fit a grid.
8. **Ranked goals.** Use `mode: "lex"` in the user's order. Use `soft` rules for targets that may be out of reach, and report how far short the answer is.
