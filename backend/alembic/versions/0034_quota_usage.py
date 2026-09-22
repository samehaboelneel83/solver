"""Quotas and metered usage per organization (target roadmap Phase 7).

A shared queue needs two things once there is more than one tenant: a way
to say how much each may ask for, and a record of how much each used.

**`iam.quota`** -- one optional row per organization. Every limit is
nullable, and null means "no limit", so an organization without a row is
unlimited, which is every organization today:

- `max_concurrent_runs` -- enforced when a worker claims (`claim_next`);
- `max_queued_runs`, `max_time_limit_s`, `max_vars`, `cpu_seconds_month`
  -- checked when a run is submitted, refused with a 422 naming the quota.

**`iam.usage_month`** -- CPU-seconds per organization per calendar month
(UTC), metered by a trigger when a run settles: its wall time times the
threads it was given. A trigger, not application code, so no path that
finishes a run can forget to count it.

Tenants read their own rows; only an operator organization sets quotas.
"""

from alembic import op

revision = "0034"
down_revision = "0033"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE iam.quota (
            organization_id     uuid PRIMARY KEY REFERENCES iam.organization(id) ON DELETE CASCADE,
            max_concurrent_runs integer CHECK (max_concurrent_runs IS NULL OR max_concurrent_runs >= 1),
            max_queued_runs     integer CHECK (max_queued_runs IS NULL OR max_queued_runs >= 1),
            max_time_limit_s    double precision CHECK (max_time_limit_s IS NULL OR max_time_limit_s > 0),
            max_vars            integer CHECK (max_vars IS NULL OR max_vars >= 1),
            cpu_seconds_month   double precision CHECK (cpu_seconds_month IS NULL OR cpu_seconds_month > 0),
            updated_at          timestamptz NOT NULL DEFAULT now()
        );

        CREATE TABLE iam.usage_month (
            organization_id uuid NOT NULL REFERENCES iam.organization(id) ON DELETE CASCADE,
            month           date NOT NULL CHECK (month = date_trunc('month', month)::date),
            cpu_seconds     double precision NOT NULL DEFAULT 0 CHECK (cpu_seconds >= 0),
            runs            integer NOT NULL DEFAULT 0 CHECK (runs >= 0),
            PRIMARY KEY (organization_id, month)
        );

        -- A run settles once: `finished_at` goes from null to a time. Its
        -- wall time times its threads is what it cost; runs queued before
        -- migration 0030 recorded no threads and were given 8.
        CREATE FUNCTION meter_run() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF OLD.finished_at IS NULL AND NEW.finished_at IS NOT NULL THEN
                INSERT INTO iam.usage_month (organization_id, month, cpu_seconds, runs)
                VALUES (
                    NEW.organization_id,
                    date_trunc('month', NEW.finished_at AT TIME ZONE 'UTC')::date,
                    coalesce(NEW.wall_time_s, 0) * coalesce((NEW.params ->> 'workers')::double precision, 8),
                    1
                )
                ON CONFLICT (organization_id, month) DO UPDATE
                   SET cpu_seconds = iam.usage_month.cpu_seconds + EXCLUDED.cpu_seconds,
                       runs = iam.usage_month.runs + 1;
            END IF;
            RETURN NEW;
        END;
        $$;
        CREATE TRIGGER run_meter AFTER UPDATE OF finished_at ON run
            FOR EACH ROW EXECUTE FUNCTION meter_run();

        -- What has already been used this month, so the meter starts true.
        INSERT INTO iam.usage_month (organization_id, month, cpu_seconds, runs)
        SELECT organization_id,
               date_trunc('month', finished_at AT TIME ZONE 'UTC')::date,
               sum(coalesce(wall_time_s, 0) * coalesce((params ->> 'workers')::double precision, 8)),
               count(*)
          FROM run
         WHERE finished_at IS NOT NULL
         GROUP BY 1, 2;

        GRANT SELECT, INSERT, UPDATE, DELETE ON iam.quota, iam.usage_month TO solver_app;

        ALTER TABLE iam.quota ENABLE ROW LEVEL SECURITY;
        CREATE POLICY tenant_read ON iam.quota FOR SELECT
            USING (organization_id = app_org() OR app_is_operator());
        CREATE POLICY written_by_operators ON iam.quota FOR ALL
            USING (app_is_operator()) WITH CHECK (app_is_operator());

        -- The meter writes as whoever settles the run: the worker, or a
        -- request that cancels a queued run. Tenants read their own.
        ALTER TABLE iam.usage_month ENABLE ROW LEVEL SECURITY;
        CREATE POLICY tenant_read ON iam.usage_month FOR SELECT
            USING (organization_id = app_org() OR app_is_operator());
        CREATE POLICY metered_for_own ON iam.usage_month FOR ALL
            USING (organization_id = app_org() OR app_is_operator())
            WITH CHECK (organization_id = app_org() OR app_is_operator());
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TRIGGER run_meter ON run;
        DROP FUNCTION meter_run();
        DROP TABLE iam.usage_month;
        DROP TABLE iam.quota;
        """
    )
