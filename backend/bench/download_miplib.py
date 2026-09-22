"""Fetch a small MIPLIB 2017 subset into `bench/mps/` (not committed).

    python -m bench.download_miplib [--dir bench/mps] [names...]

The default list is a handful of small instances from the MIPLIB 2017
benchmark set, chosen to solve in seconds to a minute with an open-source
solver. Each is downloaded from the MIPLIB site as `<name>.mps.gz`; a name
the site no longer has is reported and skipped, not fatal.

It also fetches MIPLIB's solution file (`miplib2017.solu`: `=opt= name
value` for every instance with a proven optimum, `=inf=` for an infeasible
one), so the MPS lane checks each answer against the published optimum and
not only against the other backends (`bench.mps.known_optima`).
"""

from __future__ import annotations

import argparse
import os
import sys
import urllib.error
import urllib.request

URL = "https://miplib.zib.de/WebData/instances/{name}.mps.gz"
SOLU_URL = "https://miplib.zib.de/downloads/miplib2017-v31.solu"
SOLU_FILE = "miplib2017.solu"

# Small, easy members of the MIPLIB 2017 benchmark set.
DEFAULT = [
    "gen-ip002",
    "markshare_4_0",
    "mas74",
    "mas76",
    "neos5",
    "pk1",
    "glass4",
    "air05",
    "50v-10",
    "p200x1188c",
]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m bench.download_miplib")
    parser.add_argument("names", nargs="*", default=DEFAULT)
    parser.add_argument("--dir", default=os.path.join(os.path.dirname(__file__), "mps"))
    args = parser.parse_args(argv)
    os.makedirs(args.dir, exist_ok=True)
    failed = 0
    for name in args.names:
        target = os.path.join(args.dir, f"{name}.mps.gz")
        if os.path.exists(target):
            print(f"have {name}")
            continue
        try:
            urllib.request.urlretrieve(URL.format(name=name), target)
            print(f"got {name}")
        except (urllib.error.URLError, OSError) as exc:
            failed += 1
            print(f"skipped {name}: {exc}", file=sys.stderr)
    solu = os.path.join(args.dir, SOLU_FILE)
    if not os.path.exists(solu):
        try:
            urllib.request.urlretrieve(SOLU_URL, solu)
            print(f"got {SOLU_FILE}")
        except (urllib.error.URLError, OSError) as exc:
            print(f"skipped {SOLU_FILE}: {exc}; answers are checked only against each other", file=sys.stderr)
    return 1 if failed == len(args.names) else 0


if __name__ == "__main__":
    raise SystemExit(main())
