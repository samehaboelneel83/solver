"""CLI: ``python -m bench.load`` — fair claim under load (queue R33)."""

from __future__ import annotations

import sys

from app.ops.load import main

if __name__ == "__main__":
    sys.exit(main())
