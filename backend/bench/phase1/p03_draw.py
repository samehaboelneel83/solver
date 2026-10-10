"""Draw a p03 layout (beds as JSON features) on its site as an SVG, to look at what the checker judged.

    python -m bench.phase1.p03_draw <case dir> <beds.json> <out.svg>
"""

from __future__ import annotations

import json
import sys

from shapely.geometry import shape


def main(case: str, beds: str, out: str, scale: float = 40) -> None:
    d = json.load(open(f"{case}/site.json"))
    fc = json.load(open(beds))
    w, h = d["w"] * scale, d["h"] * scale
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{w + 20}" height="{h + 20}">',
             f'<g transform="translate(10,{h + 10}) scale(1,-1)">',
             f'<rect x="0" y="0" width="{w}" height="{h}" fill="white" stroke="black" stroke-width="3"/>']
    for x0, y0, x1, y1 in d["protected"]:
        parts.append(f'<rect x="{x0 * scale}" y="{y0 * scale}" width="{(x1 - x0) * scale}" '
                     f'height="{(y1 - y0) * scale}" fill="#e66" opacity="0.6"/>')
    for x0, _, x1, _ in d["entrances"]:
        parts.append(f'<line x1="{x0 * scale}" y1="0" x2="{x1 * scale}" y2="0" stroke="green" stroke-width="10"/>')
    for f in fc["features"]:
        x0, y0, x1, y1 = shape(f["geometry"]).bounds
        parts.append(f'<rect x="{x0 * scale}" y="{y0 * scale}" width="{(x1 - x0) * scale}" height="{(y1 - y0) * scale}" '
                     'fill="#48c" stroke="black" stroke-width="1" opacity="0.8"/>')
    parts.append("</g></svg>")
    open(out, "w").write("".join(parts))


if __name__ == "__main__":
    main(*sys.argv[1:4])
