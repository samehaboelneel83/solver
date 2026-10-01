"""0096: camp solves -- a camp's layouts, the camp itself being records of its domain.

A camp is domain data (`app.camp.domain`): a `camp` record with its doors,
closed and no-bed areas, bed zones and bed types as records, linked by
relationships and tuned by parameters. What is not domain data is a layout
someone asked for: `camp_solve` keeps the problem as it was asked (so editing
the camp never changes an answer already given), the worker's progress, and
the result -- the input and the layout as GeoJSON in local metres, the report
and the layout record.

Solves are queued here and claimed by the worker with `FOR UPDATE SKIP
LOCKED`, as runs are; a worker heartbeats on the one it holds.
"""

from alembic import op

revision = "0096"
down_revision = "0095"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE camp_solve (
            id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            organization_id uuid NOT NULL REFERENCES iam.organization(id),
            domain_id       bigint NOT NULL REFERENCES domain(id) ON DELETE CASCADE,
            camp_entity_id  bigint NOT NULL REFERENCES entity(id) ON DELETE CASCADE,
            camp_name       text NOT NULL,
            problem         jsonb NOT NULL CHECK (jsonb_typeof(problem) = 'object'),
            options         jsonb NOT NULL DEFAULT '{}'::jsonb,
            status          text NOT NULL DEFAULT 'queued'
                            CHECK (status IN ('queued', 'running', 'done', 'failed', 'cancelled')),
            progress        jsonb NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(progress) = 'array'),
            cancel_requested boolean NOT NULL DEFAULT false,
            error           text,
            result          jsonb,
            beds            integer,
            valid           boolean,
            created_by      uuid REFERENCES iam.user_account(id) ON DELETE SET NULL,
            queued_at       timestamptz NOT NULL DEFAULT now(),
            started_at      timestamptz,
            heartbeat_at    timestamptz,
            finished_at     timestamptz
        );
        CREATE INDEX camp_solve_camp_idx ON camp_solve (camp_entity_id, id DESC);
        CREATE INDEX camp_solve_queue_idx ON camp_solve (queued_at) WHERE status = 'queued';
        CREATE TRIGGER a_camp_solve_tenant BEFORE INSERT OR UPDATE ON camp_solve
            FOR EACH ROW EXECUTE FUNCTION tenant_inherit('domain:domain_id:bigint', 'entity:camp_entity_id:bigint');
        ALTER TABLE camp_solve ENABLE ROW LEVEL SECURITY;
        CREATE POLICY tenant_all ON camp_solve
            USING (organization_id = app_org() OR app_is_operator())
            WITH CHECK (organization_id = app_org() OR app_is_operator());
        GRANT SELECT, INSERT, UPDATE, DELETE ON camp_solve TO solver_app;
        GRANT USAGE, SELECT ON SEQUENCE camp_solve_id_seq TO solver_app;
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS camp_solve")
