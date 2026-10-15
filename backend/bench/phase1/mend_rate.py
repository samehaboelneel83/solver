"""How well the JSON mender restores the slips of the 16 Oct evidence on the gold practice models: exact, valid but
different (a repair that means something else -- the contract must then refuse it), or not mended.

    python -m bench.phase1.mend_rate      (test image; no model, no database)
"""

from __future__ import annotations

import json
from pathlib import Path

from app.agent import toolcall

GOLD = sorted((Path(__file__).parent / "gold").glob("*.json"))


def _closers(text: str) -> list[int]:
    out, in_str, esc = [], False, False
    for i, ch in enumerate(text):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
        elif ch == '"':
            in_str = True
        elif ch in "}]":
            out.append(i)
    return out


def slips(text: str):
    pos = _closers(text)
    for i in pos[len(pos) // 3:: max(1, len(pos) // 6)][:5]:
        other = "]" if text[i] == "}" else "}"
        yield "wrong kind", text[:i] + other + text[i + 1:]
        yield "doubled", text[:i] + text[i] + text[i:]
        yield "dropped", text[:i] + text[i + 1:]


def rates() -> dict[str, list[int]]:
    kinds: dict[str, list[int]] = {}
    for path in GOLD:
        gold = json.loads(path.read_text(encoding="utf-8"))
        orig = json.dumps({"domain_name": "W", "problem_name": "P", "seed": {}, "ir": gold["ir"]})
        for kind, broken in slips(orig):
            try:
                json.loads(broken)
                continue
            except json.JSONDecodeError:
                pass
            k = kinds.setdefault(kind, [0, 0, 0, 0])
            k[0] += 1
            fixed = toolcall.fix_spec(broken)
            if fixed is None:
                k[3] += 1
            elif json.loads(fixed) == json.loads(orig):
                k[1] += 1
            else:
                k[2] += 1
                got = json.loads(fixed)
                ir = got.get("ir") if isinstance(got, dict) else None
                from app.ir.validate import check_shape

                if not isinstance(ir, dict):
                    DIFFERENT["no ir: refused"] += 1
                elif ir == gold["ir"]:
                    DIFFERENT["same model (only names or seed moved)"] += 1
                elif check_shape(ir) is not None:
                    DIFFERENT["a different model: refused by the contract"] += 1
                else:
                    DIFFERENT["a different model the contract accepts"] += 1
    return kinds


DIFFERENT: dict[str, int] = __import__("collections").Counter()


if __name__ == "__main__":
    tot = [0, 0, 0, 0]
    for kind, (n, exact, other, none) in rates().items():
        print(f"{kind:11} n {n:3}  exact {exact:3}  valid-but-different {other:3}  not mended {none:3}")
        tot = [a + b for a, b in zip(tot, (n, exact, other, none))]
    print(f"{'all':11} n {tot[0]:3}  exact {tot[1]:3}  valid-but-different {tot[2]:3}  not mended {tot[3]:3}")
    for k, v in DIFFERENT.most_common():
        print(f"   valid-but-different: {v:3}  {k}")
