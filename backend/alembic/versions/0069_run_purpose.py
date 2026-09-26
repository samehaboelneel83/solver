"""0069: why a run was made (queue R26) -- `run.purpose`, `run.parent_run_id`, `run.verdict`.

A run is a plan unless it says otherwise. A "why not?" probe (`why_not`) is a run
made from another run -- `parent_run_id` -- to answer one question about it: can
these cells be so, and if not, why? Its `verdict` holds the answer once it has
settled. `shadow` and `suite` are named now for the model CI of R29-R31, so the
CHECK need not change again then.

Probes are left out of the runs list unless asked for, count against the
organization's quota like any run, and are deleted with the run they ask about.
"""

from alembic import op

revision = "0069"
down_revision = "0068"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE run
            ADD COLUMN purpose text NOT NULL DEFAULT 'plan'
                CONSTRAINT run_purpose_known CHECK (purpose IN ('plan', 'why_not', 'shadow', 'suite')),
            ADD COLUMN parent_run_id bigint REFERENCES run(id) ON DELETE CASCADE,
            ADD COLUMN verdict jsonb,
            ADD CONSTRAINT run_parent_for_derived CHECK ((purpose = 'plan') = (parent_run_id IS NULL)
                                                         OR purpose = 'suite');
        CREATE INDEX run_parent_idx ON run (parent_run_id) WHERE parent_run_id IS NOT NULL;
    """)


def downgrade() -> None:
    op.execute("""
        DELETE FROM run WHERE purpose <> 'plan';
        DROP INDEX IF EXISTS run_parent_idx;
        ALTER TABLE run
            DROP CONSTRAINT IF EXISTS run_parent_for_derived,
            DROP COLUMN IF EXISTS verdict,
            DROP COLUMN IF EXISTS parent_run_id,
            DROP COLUMN IF EXISTS purpose;
    """)
