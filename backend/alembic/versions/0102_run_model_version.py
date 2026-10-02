"""0102: a run records the model version it solved.

A run read its model through its scenario, and a scenario can be moved to a newer version
(`PATCH /scenarios/{id}`, and solving from the problem page moves "Base" forward). Every earlier
run of it was then shown, exported, compared and explained with the new model: two runs of
versions 1 and 2 "differed only by data" (benchmark, October 2026), and a version-1 answer was
printed against version 2's goals.

- `run.model_version_id`: set as the run is queued, by a trigger so every writer is covered --
  the version a shadow run names in its params (`model_version_id`), else its scenario's.
- Existing runs take the same, as best known: the version their scenario is on now.
"""
from alembic import op

revision = "0102"
down_revision = "0101"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE run ADD COLUMN model_version_id bigint REFERENCES model_version(id) ON DELETE CASCADE;

        UPDATE run r SET model_version_id = coalesce((r.params ->> 'model_version_id')::bigint, s.model_version_id)
          FROM scenario s WHERE s.id = r.scenario_id;

        ALTER TABLE run ALTER COLUMN model_version_id SET NOT NULL;
        CREATE INDEX run_model_version_idx ON run (model_version_id);

        CREATE FUNCTION run_model_version() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF NEW.model_version_id IS NULL THEN
                NEW.model_version_id := coalesce((NEW.params ->> 'model_version_id')::bigint,
                                                 (SELECT model_version_id FROM scenario WHERE id = NEW.scenario_id));
            END IF;
            RETURN NEW;
        END $$;

        CREATE TRIGGER run_model_version BEFORE INSERT ON run
            FOR EACH ROW EXECUTE FUNCTION run_model_version();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS run_model_version ON run")
    op.execute("DROP FUNCTION IF EXISTS run_model_version()")
    op.execute("ALTER TABLE run DROP COLUMN IF EXISTS model_version_id")
