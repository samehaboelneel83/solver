"""modification timestamps on entity, entity_type and relationship_type

Ruling 42 (USER DECISION): concurrent edits get real conflict detection.

The defect
----------
An entity form loaded at T0 sends the **whole** row back on save --
including the whole `attrs` object, deliberately (Tasks 11/12: rebuilding
`attrs` from today's `attribute_def` rows is what makes a key left behind
by a deleted definition disappear, and `EntityRecord.test.tsx` pins it).
So a second client's PATCH between T0 and the save is silently reverted:
the first form never read those values and overwrites them with what it
loaded. Sending only the touched fields would undo the stale-key
clearing, so the fix has to be detection, not a narrower payload.

Detection needs something to compare, and none of the three tables that
carry an editable form had a version or a timestamp. This migration adds
one to each:

    entity.updated_at, entity_type.updated_at, relationship_type.updated_at
    timestamptz NOT NULL

Why a trigger rather than a column DEFAULT plus application code
----------------------------------------------------------------
`DEFAULT clock_timestamp()` covers INSERT only, and every writer would
then have to remember to set the column on UPDATE. The writers are not
all application code: `app/seed.py` writes through the ORM, migrations
and `psql` write raw SQL, and a future worker is free to do either. A
BEFORE INSERT OR UPDATE trigger is the one place that covers all of them,
which is the same argument migration 0006 records for `entity_validate`
being the validator rather than a Pydantic model.

`clock_timestamp()`, not `now()`
--------------------------------
`now()` is transaction start time, so two UPDATEs in one transaction get
the same value and a row could be modified twice without its timestamp
moving. `clock_timestamp()` is read at the moment the trigger fires, so
every write moves it. It is not IMMUTABLE and is not used in an index or
a CHECK here, so there is no planner consequence.

A no-op UPDATE does not move it
-------------------------------
`IF NEW IS NOT DISTINCT FROM OLD THEN RETURN NEW` -- an UPDATE that
changes nothing leaves the timestamp alone, so it cannot make another
client's open form stale for no reason. (`NEW.updated_at` arrives holding
`OLD.updated_at` whenever the statement does not set the column itself,
which is what makes the row comparison meaningful.)

Trigger firing order
--------------------
Postgres fires BEFORE ROW triggers in name order. On `entity` that is
`entity_set_updated_at` before `entity_validate` ('s' < 'v'), so the
validating trigger sees the row with its new timestamp and passes it
through untouched -- it only ever rewrites `NEW.attrs`. The order is not
load-bearing either way; it is recorded so a later trigger named between
the two is a deliberate choice rather than a surprise.

What this migration does NOT do
-------------------------------
It does not make the column part of any uniqueness or ordering rule, and
it does not require a client to send it. `PATCH` checks it when the
payload carries it and skips the check when it does not, so every
existing caller keeps working; the three forms that can lose a
concurrent edit send it. See `app/api/concurrency.py`.

Revision ID: 0010
Revises: 0009
Create Date: 2026-09-20

"""
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


# The three tables that have an editable form, and so a save that can be
# built on stale data. `relationship` and `parameter_value` are edited
# through purpose-built surfaces that write one field at a time; they are
# not covered here and the fix-round-2 report says so.
TABLES = ("entity", "entity_type", "relationship_type")


def upgrade() -> None:
    op.execute(
        """
        CREATE FUNCTION set_updated_at() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            -- An UPDATE that changes nothing is not a modification.
            IF TG_OP = 'UPDATE' AND NEW IS NOT DISTINCT FROM OLD THEN
                RETURN NEW;
            END IF;
            NEW.updated_at := clock_timestamp();
            RETURN NEW;
        END $$;
        """
    )
    for table in TABLES:
        op.execute(
            f"""
            ALTER TABLE {table}
                ADD COLUMN updated_at timestamptz NOT NULL DEFAULT clock_timestamp();

            CREATE TRIGGER {table}_set_updated_at
                BEFORE INSERT OR UPDATE ON {table}
                FOR EACH ROW EXECUTE FUNCTION set_updated_at();
            """
        )


def downgrade() -> None:
    for table in TABLES:
        op.execute(
            f"""
            DROP TRIGGER IF EXISTS {table}_set_updated_at ON {table};
            ALTER TABLE {table} DROP COLUMN IF EXISTS updated_at;
            """
        )
    op.execute("DROP FUNCTION IF EXISTS set_updated_at()")
