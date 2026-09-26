"""OAAS O05 — check.sh --isolated must require egress blocking."""

from __future__ import annotations

from pathlib import Path


def _check_sh() -> str:
    for path in (
        Path(__file__).resolve().parents[2] / "scripts" / "check.sh",
        Path("/scripts/check.sh"),
    ):
        if path.is_file():
            return path.read_text(encoding="utf-8")
    raise AssertionError("check.sh not found")


def test_check_sh_offers_isolated_mode():
    text = _check_sh()
    assert "--isolated" in text
    assert "EGRESS_BLOCKED=1" in text
    assert "REQUIRE_ISOLATED" in text


def test_isolated_mode_fails_when_stack_is_down():
    text = _check_sh()
    assert "start compose before scripts/check.sh --isolated" in text
