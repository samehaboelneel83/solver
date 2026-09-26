"""A stand-in for a licensed solver's program (queue R42): check the licence the platform put in
this process's environment, then solve as the highs-cli reference does. A licence it rejects is
quoted back on stderr, as vendors' messages sometimes do -- which the platform must scrub."""

import os
import sys

key = os.environ.get("DEMO_LICENCE_KEY", "")
path = os.environ.get("DEMO_LICENCE_FILE", "")
try:
    with open(path, encoding="utf-8") as handle:
        first = handle.readline().strip()
except OSError:
    first = ""
if not key.startswith("DEMO-") or first != "demo licence":
    print(f"licence rejected: key {key!r}, file {path!r}", file=sys.stderr)
    raise SystemExit(3)

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "highs-cli"))
from highs_cli import main  # noqa: E402

raise SystemExit(main(sys.argv))
