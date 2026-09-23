"""Every module imports on its own, in a fresh interpreter.

A test run imports half the application before any one test starts, so an
import cycle that fails only when a module is the *first* thing a process
loads never shows up there -- and in the worker it failed the first run
that reached it (`app.solve.dcp` -> `app.ir.contract` -> `app.expressions`
-> `app.models` -> `app.ir.contract`, half-loaded).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parent.parent / "app"
MODULES = sorted(
    ".".join(("app", *path.relative_to(APP).with_suffix("").parts)).removesuffix(".__init__")
    for path in APP.rglob("*.py")
)


def test_the_list_is_the_application():
    assert "app.ir.contract" in MODULES and "app.solve.dcp" in MODULES and len(MODULES) > 50


@pytest.mark.parametrize("module", MODULES)
def test_each_module_imports_first(module):
    done = subprocess.run([sys.executable, "-c", f"import {module}"], capture_output=True, text=True, cwd=APP.parent)
    assert done.returncode == 0, done.stderr[-2000:]
