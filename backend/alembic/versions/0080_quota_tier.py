"""0080: per-organization solve tiers (queue R40).

``tier``, ``priority_weight`` and ``max_memory_mb`` on ``iam.quota``. Higher
``priority_weight`` makes an organization look less busy in the fair claim.
"""

from alembic import op

revision = "0080"
down_revision = "0079"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE iam.quota
            ADD COLUMN tier text,
            ADD COLUMN priority_weight integer,
            ADD COLUMN max_memory_mb integer;
        ALTER TABLE iam.quota
            ADD CONSTRAINT quota_tier_known
            CHECK (tier IS NULL OR tier IN ('free', 'standard', 'enterprise'));
        ALTER TABLE iam.quota
            ADD CONSTRAINT quota_priority_weight_positive
            CHECK (priority_weight IS NULL OR priority_weight >= 1);
        ALTER TABLE iam.quota
            ADD CONSTRAINT quota_max_memory_mb_positive
            CHECK (max_memory_mb IS NULL OR max_memory_mb >= 256);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE iam.quota
            DROP CONSTRAINT IF EXISTS quota_max_memory_mb_positive,
            DROP CONSTRAINT IF EXISTS quota_priority_weight_positive,
            DROP CONSTRAINT IF EXISTS quota_tier_known;
        ALTER TABLE iam.quota
            DROP COLUMN IF EXISTS max_memory_mb,
            DROP COLUMN IF EXISTS priority_weight,
            DROP COLUMN IF EXISTS tier;
        """
    )
