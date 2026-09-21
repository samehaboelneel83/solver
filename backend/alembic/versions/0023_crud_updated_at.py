"""0023: optimistic locking on the generic CRUD tables

0010/0021/0022 covered the purpose-built forms. The generic factory's PUT
sends every filled writable field, so two clients opening the same
``domain``, ``template``, ``problem`` or ``iam`` row is the same silent
overwrite. This revision attaches the existing ``set_updated_at()``
function to those seven tables.

A PUT that omits ``updated_at`` is still not checked.

Revision ID: 0023
Revises: 0022
Create Date: 2026-09-21
"""
from alembic import op

revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None

TABLES = (
    ("iam", "organization"),
    ("iam", "user_account"),
    ("iam", "role"),
    ("iam", "user_role"),
    ("public", "domain"),
    ("public", "template"),
    ("public", "problem"),
)


def upgrade() -> None:
    for schema, table in TABLES:
        qualified = f"{schema}.{table}" if schema != "public" else table
        op.execute(
            f"""
            ALTER TABLE {qualified}
                ADD COLUMN updated_at timestamptz NOT NULL DEFAULT clock_timestamp();

            CREATE TRIGGER {table}_set_updated_at
                BEFORE INSERT OR UPDATE ON {qualified}
                FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();
            """
        )


def downgrade() -> None:
    for schema, table in reversed(TABLES):
        qualified = f"{schema}.{table}" if schema != "public" else table
        op.execute(
            f"""
            DROP TRIGGER IF EXISTS {table}_set_updated_at ON {qualified};
            ALTER TABLE {qualified} DROP COLUMN IF EXISTS updated_at;
            """
        )
