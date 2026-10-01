"""Make `camp_layout` importable: it is a package of its own in `backend/camp_layout/`.

The image sets PYTHONPATH to it; this covers a process started without it
(a test, a local run). It must come before the backend folder on the path:
there `camp_layout/` is the project folder, which Python would otherwise take
for an empty namespace package.
"""
from __future__ import annotations

import sys
from pathlib import Path

_ENGINE = str(Path(__file__).resolve().parents[2] / "camp_layout")
if _ENGINE not in sys.path:
    sys.path.insert(0, _ENGINE)
_loaded = sys.modules.get("camp_layout")
if _loaded is not None and getattr(_loaded, "__file__", None) is None:
    del sys.modules["camp_layout"]  # the empty namespace package, imported too early

import camp_layout  # noqa: E402,F401
from camp_layout import serial  # noqa: E402,F401
