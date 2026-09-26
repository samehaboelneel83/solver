"""0083: Idempotency-Key on run submit (OAAS Phase 5 / S02).

Client retries of POST …/runs with the same org-scoped key return the same
run instead of queueing a duplicate.
"""

from alembic import op

revision = "0083"
down_revision = "0082"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE run
            ADD COLUMN idempotency_key text NULL;
        CREATE UNIQUE INDEX run_idempotency_org_key
            ON run (organization_id, idempotency_key)
            WHERE idempotency_key IS NOT NULL;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP INDEX IF EXISTS run_idempotency_org_key;
        ALTER TABLE run DROP COLUMN IF EXISTS idempotency_key;
        """
    )
