"""Where each case's time went (the issues report of 11 October 2026, A.2), in counts and platform message templates
only -- every quoted name, snake_case name and number is replaced -- so it can run over the hidden set without
telling anything of a case.

    python -m bench.phase1.causes runs <tag>            (tuning: runs/<p>-S-<tag>/)
    python -m bench.phase1.causes runs/hidden <tag>     (hidden: runs/hidden/<h>-S-<tag>/)
"""

from __future__ import annotations

import collections
import json
import re
import sys
from pathlib import Path

_QUOTED = re.compile(r"\\?\"[^\"]*\\?\"|'[^']*'|\[[^\]]*\]")
_NUMBER = re.compile(r"\d+(?:\.\d+)?")
_MSG = re.compile(r'"msg":\s*"((?:[^"\\]|\\.)*)"')
_SNAKE = re.compile(r"\b[A-Za-z]+_\w*\b")


def template(text: str) -> str:
    """A refusal as its kind: the platform's words, the problem's names and numbers taken out."""
    msg = _MSG.search(text)
    body = msg.group(1) if msg else text.split("fix these:", 1)[-1]
    body = _NUMBER.sub("#", _QUOTED.sub("_", body))
    body = _SNAKE.sub("_", body)
    return re.sub(r"\s+", " ", body).strip()[:80]


def case(folder: Path) -> dict:
    result = json.loads((folder / "result.json").read_text()) if (folder / "result.json").exists() else {}
    panel = (folder / "panel.txt").read_text(encoding="utf-8", errors="replace") if (folder / "panel.txt").exists() else ""
    kinds = collections.Counter(template(m) for m in re.findall(r"Not valid yet[^\n]{0,400}", panel))
    return {
        "minutes": result.get("minutes"),
        "built": bool(result.get("built")),
        "cards": panel.count("Proposed model"),
        "declined": panel.count("That is not what I described"),
        "refused": sum(kinds.values()),
        "slow": len(re.findall(r"took over \d+ minutes", panel)),
        "continues": result.get("continues", 0),
        "stopped": bool(result.get("stopped")),
        "kinds": kinds,
    }


def main(root: str, tag: str) -> None:
    base = Path(__file__).parent / root
    folders = sorted(p for p in base.glob(f"*-S-{tag}") if p.is_dir())
    print(f"{'case':10} {'min':>5} {'built':>5} {'cards':>5} {'decl':>4} {'refus':>5} {'slow':>4} {'cont':>4} {'stop':>4}")
    total: collections.Counter = collections.Counter()
    for f in folders:
        c = case(f)
        total.update(c["kinds"])
        print(f"{f.name.split('-' + tag)[0]:10} {c['minutes'] or 0:>5} {'yes' if c['built'] else 'no':>5} {c['cards']:>5} "
              f"{c['declined']:>4} {c['refused']:>5} {c['slow']:>4} {c['continues']:>4} {'yes' if c['stopped'] else '':>4}")
    if total:
        print("\nrefusals by kind (all cases):")
        for kind, n in total.most_common(12):
            print(f"  {n:3}  {kind}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
