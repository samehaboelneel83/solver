"""Test helpers: remove every camp, its records and the camp structure from the test database."""
from __future__ import annotations

from sqlalchemy import text

from app.camp.domain import STRUCTURE


def clear_camps(session) -> None:
    session.execute(text("DELETE FROM camp_solve"))
    session.execute(text("DELETE FROM parameter_def WHERE name = ANY(:n)"), {"n": [p["name"] for p in STRUCTURE["parameters"]]})
    session.execute(text("DELETE FROM entity_type WHERE name = ANY(:n)"), {"n": [t["name"] for t in STRUCTURE["entity_types"]]})
    session.commit()
