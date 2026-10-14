"""Shared by the phase 1 problems (docs/plans/2026-10-10-phase1-evaluation.md): writing a case, reading the
platform's export, finding a decision by the records it is over.

A case is a folder `<problem>/<size>/` holding the data as CSV files, `message.txt` (what a person types), and
`expected.json` (the reference: an exact optimum, or a known feasible plan and a bound). Each problem's
`gen.py` writes its three sizes and has `check(case_dir, export_csv) -> list[str]`: every hard rule tested on
the exported plan against the data files alone.
"""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path
from typing import Any, Iterable

HERE = Path(__file__).parent


def write_csv(path: Path, header: list[str], rows: Iterable[Iterable[Any]]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header)
        for row in rows:
            w.writerow(row)
            count += 1
    return count


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def csv_text(path: Path) -> str:
    return path.read_text(encoding="utf-8").strip()


def write_case(folder: Path, message: str, expected: dict[str, Any]) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "message.txt").write_text(message.strip() + "\n", encoding="utf-8")
    (folder / "expected.json").write_text(json.dumps(expected, indent=2), encoding="utf-8")


def export_rows(export_csv: str) -> list[dict[str, str]]:
    """The platform's CSV export: decision,key1,key2,...,value."""
    return list(csv.DictReader(io.StringIO(export_csv)))


def decision_over(rows: list[dict[str, str]], *key_sets: set[str]) -> tuple[str, dict[tuple[str, ...], float]]:
    """The decision whose keys fall in these sets, in any order of the key positions (the model names its own
    decisions and orders its own indices: step 8 run 1 keyed (machine, product, shift) where the checker read
    (product, machine, shift)); its name and {keys: value}, the keys in the sets' order. ("", {}) when no
    decision fits."""
    from itertools import permutations

    by: dict[str, dict[tuple[str, ...], float]] = {}
    order: dict[str, tuple[int, ...]] = {}  # per decision: which key position holds each set's keys
    n = len(key_sets)
    for r in rows:
        keys = tuple(r.get(f"key{i + 1}") or "" for i in range(n))
        extra = [r.get(k) for k in r if k.startswith("key") and int(k[3:]) > n and r.get(k)]
        if extra:
            continue
        name = r["decision"]
        perm = order.get(name)
        if perm is None or not all(keys[perm[j]] in key_sets[j] for j in range(n)):
            perm = next((p for p in permutations(range(n)) if all(keys[p[j]] in key_sets[j] for j in range(n))), None)
            if perm is None:
                continue
            order[name] = perm
        by.setdefault(name, {})[tuple(keys[perm[j]] for j in range(n))] = float(r["value"])
    if not by:
        return "", {}
    # The decision holding amounts before a yes/no one over the same records (a setup beside the quantities).
    name = max(by, key=lambda n: (any(v not in (0.0, 1.0) for v in by[n].values()), len(by[n])))
    return name, by[name]
