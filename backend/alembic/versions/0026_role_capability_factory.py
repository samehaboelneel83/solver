"""0026: role_capability through the generic factory

0013 made capabilities rows and the grant a composite primary key
``(role_id, capability_code)``. Assigning a *user* a role is already a
factory form (``user_role`` has a surrogate id). Saying what that role
may do still needed SQL, because the factory's GET/PUT/DELETE are keyed
by one column.

This revision gives the existing grant table the same shape as
``user_role``: a UUID ``id``, ``updated_at`` with the existing trigger,
and a unique pair so a duplicate grant is still a 409. No new object --
the vocabulary is still ``iam.capability``.

Revision ID: 0026
Revises: 0025
Create Date: 2026-09-21
"""
from alembic import op

revision = "0026"
down_revision = "0025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE iam.role_capability
            ADD COLUMN id uuid NOT NULL DEFAULT gen_random_uuid();
        ALTER TABLE iam.role_capability
            ADD COLUMN updated_at timestamptz NOT NULL DEFAULT clock_timestamp();

        ALTER TABLE iam.role_capability DROP CONSTRAINT role_capability_pkey;
        ALTER TABLE iam.role_capability ADD PRIMARY KEY (id);
        ALTER TABLE iam.role_capability
            ADD CONSTRAINT role_capability_role_capability_key
            UNIQUE (role_id, capability_code);

        CREATE TRIGGER role_capability_set_updated_at
            BEFORE INSERT OR UPDATE ON iam.role_capability
            FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TRIGGER IF EXISTS role_capability_set_updated_at ON iam.role_capability;
        ALTER TABLE iam.role_capability DROP CONSTRAINT role_capability_role_capability_key;
        ALTER TABLE iam.role_capability DROP CONSTRAINT role_capability_pkey;
        ALTER TABLE iam.role_capability DROP COLUMN id;
        ALTER TABLE iam.role_capability DROP COLUMN updated_at;
        ALTER TABLE iam.role_capability
            ADD PRIMARY KEY (role_id, capability_code);
        """
    )
