"""The result cache: `run.cache_key` and `run.reused_from`.

A submit whose answer is already known -- the same model, the same frozen
data, the same scenario patch and the same settings that decide what the
answer is -- need not be solved again. `cache_key` is a sha256 of those
(`app.solve.cache.key_of`); a run proven globally optimal under a key
answers a later submit with the same key: a new run is recorded, already
finished, with `reused_from` pointing at the one that was solved, and the
answer copied (target roadmap Phase 12). Only a proven optimum is an
answer; a time-limited or local result is not reused.

`reused_from` is set null if the original is deleted: the copy stays an
answer, it only loses the pointer.
"""

from alembic import op

revision = "0042"
down_revision = "0041"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE run ADD COLUMN cache_key text")
    op.execute("ALTER TABLE run ADD COLUMN reused_from bigint REFERENCES run(id) ON DELETE SET NULL")
    # The lookup: a proven optimum under this key, newest first, per tenant
    # (RLS adds the organization; the index leads with it so the plan can).
    op.execute(
        "CREATE INDEX run_cache_idx ON run (organization_id, cache_key, id DESC)"
        " WHERE status = 'optimal' AND optimality = 'global'"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS run_cache_idx")
    op.execute("ALTER TABLE run DROP COLUMN IF EXISTS reused_from")
    op.execute("ALTER TABLE run DROP COLUMN IF EXISTS cache_key")
