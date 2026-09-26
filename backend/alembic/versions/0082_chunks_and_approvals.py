"""0082: chunked solution amounts + approved plans (OAAS Phase 5).

When a run's continuous/integer amounts exceed the inline cap, rows are stored
in `solution_amount_chunk` instead of being discarded. An approved plan is a
business acceptance of a specific immutable run result — distinct from solver
proof and from model publication.
"""

from alembic import op

revision = "0082"
down_revision = "0081"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE solution_amount_chunk (
            run_id          bigint NOT NULL REFERENCES run(id) ON DELETE CASCADE,
            variable        text NOT NULL,
            chunk_index     integer NOT NULL CHECK (chunk_index >= 0),
            organization_id uuid NOT NULL REFERENCES iam.organization(id),
            rows            jsonb NOT NULL,
            cell_count      integer NOT NULL CHECK (cell_count >= 0),
            PRIMARY KEY (run_id, variable, chunk_index)
        );
        CREATE INDEX solution_amount_chunk_run_idx ON solution_amount_chunk (run_id);
        ALTER TABLE solution_amount_chunk ENABLE ROW LEVEL SECURITY;
        CREATE POLICY tenant_all ON solution_amount_chunk
            USING (organization_id = app_org() OR app_is_operator())
            WITH CHECK (organization_id = app_org() OR app_is_operator());
        GRANT SELECT, INSERT, UPDATE, DELETE ON solution_amount_chunk TO solver_app;

        CREATE TABLE approved_plan (
            id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            organization_id uuid NOT NULL REFERENCES iam.organization(id),
            run_id          bigint NOT NULL REFERENCES run(id),
            problem_id      bigint NOT NULL REFERENCES problem(id),
            reason          text NOT NULL,
            approved_by     uuid,
            approved_at     timestamptz NOT NULL DEFAULT now(),
            effective_from  date,
            effective_to    date,
            superseded_by   bigint REFERENCES approved_plan(id),
            UNIQUE (run_id)
        );
        CREATE INDEX approved_plan_problem_idx ON approved_plan (problem_id)
            WHERE superseded_by IS NULL;
        ALTER TABLE approved_plan ENABLE ROW LEVEL SECURITY;
        CREATE POLICY tenant_all ON approved_plan
            USING (organization_id = app_org() OR app_is_operator())
            WITH CHECK (organization_id = app_org() OR app_is_operator());
        GRANT SELECT, INSERT, UPDATE, DELETE ON approved_plan TO solver_app;
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS approved_plan")
    op.execute("DROP TABLE IF EXISTS solution_amount_chunk")
