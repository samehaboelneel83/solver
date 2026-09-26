"""0073: a problem's acceptance cases (queue R29) -- `suite_case`.

A case is a question with a known answer: a frozen dataset (an immutable `dataset` row), a scenario
patch, and what the answer must be -- `expect`: `status`, `objective` within `tolerance_abs` /
`tolerance_rel`, cells that `must_hold` in it, and `max_seconds`. Made from any answered run in one
step (its answer becomes the expectation, which a person may loosen). A case run is a `run` with
`purpose = 'suite'` on the case's dataset; its `verdict` says passed or failed, and why.

A tenant's table: its organization is its problem's (`tenant_inherit`), under row-level security.
"""

from alembic import op

revision = "0073"
down_revision = "0072"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE suite_case (
            id                  bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            problem_id          bigint NOT NULL REFERENCES problem(id) ON DELETE CASCADE,
            name                text NOT NULL CHECK (length(name) BETWEEN 1 AND 200),
            dataset_id          bigint NOT NULL REFERENCES dataset(id) ON DELETE CASCADE,
            patch               jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(patch) = 'object'),
            expect              jsonb NOT NULL CHECK (jsonb_typeof(expect) = 'object'),
            created_from_run_id bigint REFERENCES run(id) ON DELETE SET NULL,
            created_by          text,
            created_at          timestamptz NOT NULL DEFAULT now(),
            organization_id     uuid NOT NULL REFERENCES iam.organization(id),
            UNIQUE (problem_id, name)
        );
        CREATE INDEX suite_case_organization_idx ON suite_case (organization_id);
        CREATE TRIGGER a_suite_case_tenant BEFORE INSERT OR UPDATE ON suite_case
            FOR EACH ROW EXECUTE FUNCTION tenant_inherit('problem:problem_id:bigint');
        ALTER TABLE suite_case ENABLE ROW LEVEL SECURITY;
        CREATE POLICY tenant_isolation ON suite_case
            USING (organization_id = app_org())
            WITH CHECK (organization_id = app_org());
        GRANT SELECT, INSERT, UPDATE, DELETE ON suite_case TO solver_app;
        GRANT USAGE, SELECT ON SEQUENCE suite_case_id_seq TO solver_app;
    """)


def downgrade() -> None:
    op.execute("DELETE FROM run WHERE purpose = 'suite'")
    op.execute("DROP TABLE suite_case")
