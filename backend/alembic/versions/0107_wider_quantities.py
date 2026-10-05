"""0107: quantities hold eighteen integer digits, not nine.

0015 chose `numeric(15, 6)` for "fifteen significant digits, what a double round-trips". But six of
the fifteen are after the point, so only nine were left before it: no number could reach a billion.
A run whose objective added up past that (the Assistant's field test, October 2026: a model with
transport costs in the billions of EGP) was solved, optimal, and then crashed while saving its
answer -- `numeric field overflow`, and every retry the same. A cost of 1.2 billion could not be typed
as a parameter either.

`numeric(24, 6)` keeps the six decimal places and gives eighteen integer digits. What the API takes
in is still bounded to fifteen significant digits (app/api/quantity.py), the precision a solver's
doubles keep exactly; the column is simply no longer the narrower bound. Widening a numeric changes
no stored value, and `snapshot_dataset()` trims the scale, so no dataset's hash moves.

`run_overview` reads two of these columns and Postgres will not alter a column a view depends on:
it is dropped and recreated from 0015's copy of 0007's text, as 0015 itself did.
"""

import importlib.util
from pathlib import Path

from alembic import op

revision = "0107"
down_revision = "0106"
branch_labels = None
depends_on = None

_COLUMNS = [
    ("parameter_value", "value", False),
    ("parameter_def", "default_value", True),
    ("run", "objective", False),
    ("constraint_result", "total_violation", True),
    ("constraint_result", "penalty_paid", True),
    ("constraint_result", "slack", False),
    ("constraint_result", "dual", False),
    ("suite_nightly", "objective", False),
]


def _run_overview() -> str:
    spec = importlib.util.spec_from_file_location("m0015", Path(__file__).with_name("0015_decimal_parameters.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module._RUN_OVERVIEW_0007


def _alter(width: str) -> None:
    op.execute("DROP VIEW IF EXISTS run_overview")
    for table, column, defaulted in _COLUMNS:
        op.execute(f"ALTER TABLE {table} ALTER COLUMN {column} TYPE {width}")
        if defaulted:
            op.execute(f"ALTER TABLE {table} ALTER COLUMN {column} SET DEFAULT 0")
    op.execute(_run_overview())


def upgrade() -> None:
    _alter("numeric(24, 6)")


def downgrade() -> None:
    # Fails, rather than rounding or clipping, if a value no longer fits: that number is real data.
    _alter("numeric(15, 6)")
