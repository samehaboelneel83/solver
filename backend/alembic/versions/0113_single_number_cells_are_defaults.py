"""0113: a parameter without an index keeps its one number as its default, never as a cell with no records.

Every read of parameter cells -- the run's snapshot (`snapshot_dataset`) and the editor's / trial's
`live_data` -- unnests a cell's records, so a cell with none was never read: the parameter took its default
instead (the database-source test, October 2026: assembly and finishing capacity were written as such cells,
read as 0, and the plan made nothing). The seed now writes the default (app/seed.py); this moves any such cell
already stored into its parameter's default and removes it.
"""

from alembic import op

revision = "0113"
down_revision = "0112"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    UPDATE parameter_def d SET default_value = v.value
      FROM parameter_value v
     WHERE v.parameter_def_id = d.id AND cardinality(v.entity_ids) = 0
       AND cardinality(coalesce(d.index_type_ids, '{}')) = 0
       AND d.value_type_id IS NULL AND v.value IS NOT NULL;
    DELETE FROM parameter_value v USING parameter_def d
     WHERE v.parameter_def_id = d.id AND cardinality(v.entity_ids) = 0
       AND cardinality(coalesce(d.index_type_ids, '{}')) = 0
       AND d.value_type_id IS NULL AND v.value IS NOT NULL;
    """)


def downgrade() -> None:
    pass  # The value is kept, as the default; there is nothing to restore.
