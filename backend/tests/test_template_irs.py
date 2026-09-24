"""Every template's IR, as the frontend's Blocks round trip reads it (Blocks 2).

The frontend cannot import Python, so the templates are written to
tests/template_irs.json. This test fails when the file and the templates
disagree; `SOLVER_WRITE_TEMPLATE_IRS=1 pytest tests/test_template_irs.py`
rewrites it.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from app.seed import WEEKLY_ROTA_TEMPLATE, weekly_rota_template_ir
from app.showcase import SHOWCASE

PATH = Path(__file__).parent / "template_irs.json"


def _templates() -> dict:
    return {WEEKLY_ROTA_TEMPLATE: weekly_rota_template_ir(), **{name: ir for name, (_seed, ir) in SHOWCASE.items()}}


def test_the_frontend_reads_every_template_as_it_is():
    templates = _templates()
    if os.environ.get("SOLVER_WRITE_TEMPLATE_IRS") == "1":
        PATH.write_text(json.dumps(templates, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    # Compared as data, not bytes: a Windows checkout writes the file with
    # CRLF line ends (core.autocrlf), which is the same document.
    assert json.loads(PATH.read_text(encoding="utf-8")) == templates, "run with SOLVER_WRITE_TEMPLATE_IRS=1 to refresh"
