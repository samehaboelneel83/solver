"""0092: imports into relationships and parameters (Epic UX, U-4 follow-up).

An extraction could only become entities of one type. A mapping may now name
a relationship type (rows become links between two entities, by key) or a
parameter (rows become cells, one key column per index and a value) instead.
`import_validation` and `import_load` record which, in exactly one of three
columns; a row from before names its entity type as ever.
"""

from alembic import op

revision = "0092"
down_revision = "0091"
branch_labels = None
depends_on = None

TABLES = ("import_validation", "import_load")


def upgrade() -> None:
    for table in TABLES:
        op.execute(
            f"""
            ALTER TABLE {table}
                ALTER COLUMN entity_type_id DROP NOT NULL,
                ADD COLUMN relationship_type_id bigint REFERENCES relationship_type(id) ON DELETE CASCADE,
                ADD COLUMN parameter_id bigint REFERENCES parameter_def(id) ON DELETE CASCADE,
                ADD CONSTRAINT {table}_one_target
                    CHECK (num_nonnulls(entity_type_id, relationship_type_id, parameter_id) = 1);
            """
        )


def downgrade() -> None:
    for table in TABLES:
        op.execute(
            f"""
            DELETE FROM {table} WHERE entity_type_id IS NULL;
            ALTER TABLE {table}
                DROP CONSTRAINT {table}_one_target,
                DROP COLUMN parameter_id,
                DROP COLUMN relationship_type_id,
                ALTER COLUMN entity_type_id SET NOT NULL;
            """
        )
