"""0078: audit_event.actor_id is history, not a live FK (queue R34).

ON DELETE SET NULL on actor_id updated audit rows when a user was removed,
and the append-only trigger refused that UPDATE. Drop the FK: the uuid stays
as a record of who acted even after the account is gone.
"""

from alembic import op

revision = "0078"
down_revision = "0077"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE iam.audit_event DROP CONSTRAINT IF EXISTS audit_event_actor_id_fkey;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE iam.audit_event
            ADD CONSTRAINT audit_event_actor_id_fkey
            FOREIGN KEY (actor_id) REFERENCES iam.user_account(id) ON DELETE SET NULL;
        """
    )
