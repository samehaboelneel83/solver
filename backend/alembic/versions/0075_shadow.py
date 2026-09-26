"""0075: shadow runs (queue R31) -- settings `shadow.version` and `shadow.rate`.

A problem may name a candidate model version (`shadow.version`, a model version's id; 0 for none)
and a share of its real runs (`shadow.rate`, 0 to 1; 0 by default -- a shadow doubles the solving
it shadows, so turning it on is the organization's decision). Each real run is then, at that rate,
asked again of the candidate on the same frozen data and patch, at the lowest priority, as a run
with `purpose = 'shadow'` and `parent_run_id` the real run -- never shown to the planner. When both
have settled, the shadow's `verdict` compares them.
"""

from alembic import op

revision = "0075"
down_revision = "0074"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "INSERT INTO setting_key (key, value_type, default_value, description) VALUES"
        " ('shadow.version', 'number', CAST('0' AS jsonb),"
        "  'A candidate model version (its id) that answers a share of real runs beside the one in use; 0 for none'),"
        " ('shadow.rate', 'number', CAST('0' AS jsonb),"
        "  'The share of real runs (0 to 1) the candidate version also answers, at the lowest priority')"
    )


def downgrade() -> None:
    op.execute("DELETE FROM run WHERE purpose = 'shadow'")
    op.execute("DELETE FROM setting WHERE key IN ('shadow.version', 'shadow.rate')")
    op.execute("DELETE FROM setting_key WHERE key IN ('shadow.version', 'shadow.rate')")
