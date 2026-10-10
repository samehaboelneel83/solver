"""The placement solver's export as bed shapes, for p03's checker when the run's answer map has none.

    python -m bench.phase1.p03_from_export <export.csv> <out.json> [length_cells width_cells cell_m]

x[slot], y[slot]: a bed's corner on the grid (cells of `cell_m`); turned[slot] = 1 swaps its sides; a slot
with placed = 1 is a bed. Cells not listed in the export are 0.
"""

from __future__ import annotations

import csv
import json
import sys


def main(export: str, out: str, length: int = 20, width: int = 9, cell: float = 0.1) -> int:
    val: dict[str, dict[str, float]] = {}
    with open(export, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            val.setdefault(r["decision"], {})[r["key1"]] = float(r["value"])
    beds = [k for k, v in val.get("placed", {}).items() if v > 0.5]
    features = []
    for b in beds:
        x0, y0 = val.get("x", {}).get(b, 0.0) * cell, val.get("y", {}).get(b, 0.0) * cell
        dx, dy = (width, length) if val.get("turned", {}).get(b, 0.0) > 0.5 else (length, width)
        x1, y1 = x0 + dx * cell, y0 + dy * cell
        features.append({"type": "Feature", "properties": {"set": "slot", "id": b},
                         "geometry": {"type": "Polygon", "coordinates": [[[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]]]}})
    with open(out, "w", encoding="utf-8") as f:
        json.dump({"type": "FeatureCollection", "features": features}, f)
    print(len(features), "beds")
    return 0


if __name__ == "__main__":
    a = sys.argv
    sys.exit(main(a[1], a[2], *(int(x) for x in a[3:5]), *(float(x) for x in a[5:6])))
