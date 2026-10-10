"""Problem 3: camp layout with accessibility (geometric placement and connectivity).

    python -m bench.phase1.p03_camp gen [S M L]
    python -m bench.phase1.p03_camp check <case> <answer-map.json>

A rectangular site with protected zones and entrances on its edge, as a drawing (site.dxf, layers SITE,
PROTECTED, ENTRANCE). Beds are 2.0 m x 0.9 m, either way round. A bed must lie inside the site, clear of every
protected zone and of every other bed, and must touch open space at least 1.2 m wide (a corridor) that is
connected to an entrance by open space at least 1.2 m wide. Most beds; then the shortest walk to an entrance.

The checker reads the run's answer map (the placed beds' shapes, in the drawing's metres) and tests all of it
with shapely -- a layout image alone proves nothing. The reference is a constructed layout (rows of beds on
both sides of corridors, a spine to the entrance), checked by the same checker: a known feasible count; the
upper bound is the free area over each bed's share (its own area plus half a corridor along its short side).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

from bench.phase1.common import HERE, write_case

SIZES = {"S": (14, 10, 1, 1), "M": (40, 25, 3, 2), "L": (120, 60, 8, 4)}  # width, height, protected, entrances
OUT = HERE / "cases" / "p03"
BED = (2.0, 0.9)
CORRIDOR = 1.2
CHECK_FILE = "answer-map.json"  # what score.py hands to check() instead of the CSV export


def make(size: str, seed: int = 3) -> dict:
    w, h, n_p, n_e = SIZES[size]
    rng = np.random.default_rng(seed + w)
    protected = []
    while len(protected) < n_p:
        pw, ph = rng.uniform(2, max(3, w / 6)), rng.uniform(2, max(3, h / 5))
        x, y = rng.uniform(2, w - pw - 2), rng.uniform(3, h - ph - 1)
        protected.append((round(x, 1), round(y, 1), round(x + pw, 1), round(y + ph, 1)))
    entrances = [(round(float(x), 1), 0.0, round(float(x) + 1.5, 1), 0.0)
                 for x in np.linspace(1, w - 2.5, n_e + 2)[1:-1]]
    return dict(w=w, h=h, protected=protected, entrances=entrances)


def write_dxf(d: dict, path: Path) -> None:
    import ezdxf

    doc = ezdxf.new()
    msp = doc.modelspace()
    for layer in ("SITE", "PROTECTED", "ENTRANCE"):
        doc.layers.add(layer)
    msp.add_lwpolyline([(0, 0), (d["w"], 0), (d["w"], d["h"]), (0, d["h"])], close=True, dxfattribs={"layer": "SITE"})
    for x0, y0, x1, y1 in d["protected"]:
        msp.add_lwpolyline([(x0, y0), (x1, y0), (x1, y1), (x0, y1)], close=True, dxfattribs={"layer": "PROTECTED"})
    for x0, y0, x1, y1 in d["entrances"]:
        msp.add_line((x0, y0), (x1, y1), dxfattribs={"layer": "ENTRANCE"})
    path.parent.mkdir(parents=True, exist_ok=True)
    doc.saveas(path)


def constructed(d: dict) -> list:
    """Rows of beds either side of horizontal corridors, a vertical spine from each entrance."""
    from shapely.geometry import box

    beds = []
    spines = [box(x0, 0, x0 + 1.5, d["h"]) for x0, _, _, _ in d["entrances"]]
    period = 2 * BED[0] + CORRIDOR
    y = 0.0
    while y + BED[0] <= d["h"]:
        for row_y in (y, y + BED[0] + CORRIDOR):
            if row_y + BED[0] > d["h"]:
                continue
            x = 0.0
            while x + BED[1] <= d["w"]:
                b = box(x, row_y, x + BED[1], row_y + BED[0])
                if not any(b.intersects(s) for s in spines) and not any(
                        b.intersects(box(*p)) for p in d["protected"]):
                    beds.append(b)
                x += BED[1]
        y += period
    # keep only beds the checker accepts (accessible), until stable
    for _ in range(5):
        bad = set(_inaccessible(d, beds))
        if not bad:
            break
        beds = [b for i, b in enumerate(beds) if i not in bad]
    return beds


def _inaccessible(d: dict, beds: list) -> list[int]:
    from shapely.geometry import LineString, box
    from shapely.ops import unary_union

    site = box(0, 0, d["w"], d["h"])
    blocked = unary_union([box(*p) for p in d["protected"]] + beds)
    free = site.difference(blocked)
    core = free.buffer(-CORRIDOR / 2 + 1e-6)  # where the middle of a 1.2 m corridor can be
    parts = list(getattr(core, "geoms", [core])) if not core.is_empty else []
    doors = [LineString([(x0, y0), (x1, y1)]) for x0, y0, x1, y1 in d["entrances"]]
    reach = [p for p in parts if any(p.distance(e) <= CORRIDOR / 2 + 1e-3 for e in doors)]
    reach_u = unary_union(reach) if reach else None
    return [i for i, b in enumerate(beds) if reach_u is None or b.distance(reach_u) > CORRIDOR / 2 + 1e-3]


def check_beds(d: dict, beds: list) -> list[str]:
    from shapely.geometry import box

    site = box(0, 0, d["w"], d["h"])
    bad = []
    for i, b in enumerate(beds):
        dims = sorted([b.bounds[2] - b.bounds[0], b.bounds[3] - b.bounds[1]])
        if abs(dims[0] - BED[1]) > 0.02 or abs(dims[1] - BED[0]) > 0.02 or abs(b.area - BED[0] * BED[1]) > 0.02:
            bad.append(f"bed {i} is {dims[0]:.2f} x {dims[1]:.2f} m, not {BED[1]} x {BED[0]}")
        if not site.buffer(1e-6).contains(b):
            bad.append(f"bed {i} is not inside the site")
        for p in d["protected"]:
            if b.intersection(box(*p)).area > 1e-6:
                bad.append(f"bed {i} is in a protected zone")
    for i in range(len(beds)):
        for j in range(i + 1, len(beds)):
            if beds[i].intersection(beds[j]).area > 1e-6:
                bad.append(f"beds {i} and {j} overlap")
    bad += [f"bed {i} has no 1.2 m way to an entrance" for i in _inaccessible(d, beds)]
    return bad


def write(size: str) -> Path:
    d = make(size)
    folder = OUT / size
    write_dxf(d, folder / "site.dxf")
    (folder / "site.json").write_text(json.dumps(d))
    beds = constructed(d)
    assert not check_beds(d, beds), check_beds(d, beds)[:3]
    from shapely.geometry import box
    from shapely.ops import unary_union

    free = box(0, 0, d["w"], d["h"]).difference(unary_union([box(*p) for p in d["protected"]])).area
    bound = int(free // (BED[0] * BED[1] + BED[1] * CORRIDOR / 2))
    message = (f'Please build this in a new workspace called "{{workspace}}". Call the problem "Camp layout". Design '
               f"a camp on the site in the attached drawing site.dxf (metres): layer SITE is the {d['w']} m x {d['h']} m "
               f"site boundary, layer PROTECTED holds {len(d['protected'])} protected areas that nothing may occupy, and "
               f"layer ENTRANCE holds {len(d['entrances'])} entrance(s) on the boundary.\n\n"
               f"Rules: beds are {BED[0]} m x {BED[1]} m and may be turned either way. Every bed lies inside the site, "
               "never overlaps a protected area or another bed, and touches a corridor: open space at least "
               f"{CORRIDOR} m wide that connects, at least {CORRIDOR} m wide all the way, to an entrance. Goal: as many "
               "beds as possible; among layouts with as many beds, the shortest walk from the beds to an entrance. "
               "Report a 2D layout showing entrances, beds, protected areas and corridors, every bed's position, size "
               "and orientation, a check that every bed reaches an entrance, the bed count, and the trade-off between "
               "bed count and corridor width.\n\nEverything you need is here: please propose the model without "
               "further questions, then solve it.")
    report = [["layout drawn / map", r"map|layout|drawing"], ["bed positions", r"\d+(\.\d+)?\s*,\s*\d+(\.\d+)?|position|coordinate"],
              ["orientation", r"orient|rotat|turned"], ["accessibility check", r"entrance|access|corridor"],
              ["bed count", r"\d+ beds"], ["trade-off with corridor width", r"corridor width|trade-?off|wider"]]
    write_case(folder, message, {"problem": "p03", "size": size, "kind": "bounded", "goal": None,
                                 "known_feasible": len(beds), "bound": bound, "sense": "maximize", "report": report,
                                 "files": ["site.dxf"]})
    return folder


def check(folder: Path, answer_map: str) -> list[str]:
    """The placed beds from the run's answer map: polygons of about 2.0 x 0.9 m."""
    from shapely.geometry import shape

    d = json.loads((folder / "site.json").read_text())
    try:
        fc = json.loads(answer_map)
    except ValueError:
        return ["no answer map"]
    beds = []
    for f in fc.get("features") or []:
        g = f.get("geometry") or {}
        if g.get("type") in ("Polygon", "MultiPolygon"):
            s = shape(g)
            if 1.0 < s.area < 3.0:  # a bed, not the site or a zone
                beds.append(s)
    if not beds:
        return ["no bed shapes in the run's answer map"]
    return check_beds(d, beds)[:40] + [f"COST {len(beds)}"]


if __name__ == "__main__":
    if sys.argv[1] == "gen":
        for s in (sys.argv[2:] or list(SIZES)):
            f = write(s)
            print(s, f, (f / "expected.json").read_text().replace("\n", " ")[:200])
    elif sys.argv[1] == "check":
        print("\n".join(check(Path(sys.argv[2]), Path(sys.argv[3]).read_text(encoding="utf-8"))))
