"""parameter_def: refuse duplicate index_type_ids (Ruling 10, temporary)

`snapshot_dataset()` (0007) builds each parameter row with
`jsonb_object_agg(t.name, e.key)` -- keyed by the index *type's* name. A
parameter indexed by the same entity type twice (`distance[location,
location]`) therefore collapses both coordinates onto one key, and every
snapshot of it silently loses a coordinate. No error is raised anywhere.

This migration adds the guard Ruling 10 (revised) put in the database
rather than the router, so the seed, psql and any future worker are
covered too:

    CHECK (cardinality(index_type_ids)
           = cardinality(ARRAY(SELECT DISTINCT unnest(index_type_ids))))

**The restriction is temporary.** Self-indexed parameters -- distance
matrices, transition costs, precedence -- are ordinary in this domain. The
real fix is to key snapshot rows by index *position* instead of type name,
which changes the dataset document contract with `psp/data.py` and is the
user's decision. When it is made, the fix is `downgrade()` of this
revision (or the two statements in it), not a data migration.

Why a helper function
---------------------
Postgres does not allow a subquery in a CHECK expression, and it has no
built-in "array has distinct elements" operator. The subquery therefore
moves into an IMMUTABLE SQL function, which a CHECK may call. The function
is exactly the ruling's expression, including its NULL semantics: `SELECT
DISTINCT` puts all NULLs in one group, so `{1,NULL}` passes and
`{NULL,NULL}` fails, as the inline form would. (NULL elements are not
otherwise excluded by the DDL; that is unchanged here.)

IMMUTABLE is truthful -- the result depends only on the argument -- and is
what makes the function legitimate inside a CHECK: Postgres re-evaluates a
CHECK only when the row changes, so a function whose answer could change
without the row changing would make the constraint lie.

Upgrading fails if any existing `parameter_def` row already repeats a type.
None can exist in a database built by this chain: nothing writes
`parameter_def` before Task 8's router, which enforces the same rule.

Revision ID: 0008
Revises: 0007
Create Date: 2026-09-19

"""
from alembic import op

# revision identifiers, used by Alembic.
revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE FUNCTION bigint_array_is_distinct(a bigint[]) RETURNS boolean
        LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
            SELECT cardinality(a) = cardinality(ARRAY(SELECT DISTINCT unnest(a)))
        $$;

        ALTER TABLE parameter_def
            ADD CONSTRAINT parameter_def_index_type_ids_distinct
            CHECK (bigint_array_is_distinct(index_type_ids));
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE parameter_def DROP CONSTRAINT IF EXISTS parameter_def_index_type_ids_distinct;
        DROP FUNCTION IF EXISTS bigint_array_is_distinct(bigint[]);
        """
    )
