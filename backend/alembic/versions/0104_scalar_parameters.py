"""0104: a data value may be one number, with no index -- a truck's capacity, a yearly budget.

Every data value needed at least one index (`cardinality(index_type_ids) >= 1`), so a single
number had to be a rule's constant, where a scenario could not change it and the data list could
not show it (benchmark, October 2026). With no index, its value is its `default_value`; the frozen
dataset already carries defaults, so a model reads it as `name` with no subscript.
"""
from alembic import op

revision = "0104"
down_revision = "0103"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE parameter_def DROP CONSTRAINT parameter_def_index_type_ids_check")
    op.execute("ALTER TABLE parameter_def ADD CONSTRAINT parameter_def_index_type_ids_check"
               " CHECK (cardinality(index_type_ids) >= 0)")


def downgrade() -> None:
    op.execute("ALTER TABLE parameter_def DROP CONSTRAINT parameter_def_index_type_ids_check")
    op.execute("ALTER TABLE parameter_def ADD CONSTRAINT parameter_def_index_type_ids_check"
               " CHECK (cardinality(index_type_ids) >= 1)")
