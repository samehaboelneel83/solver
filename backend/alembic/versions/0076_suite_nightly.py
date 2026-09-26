"""0076: suite_nightly (queue R32) -- each night's re-ask of every acceptance case.

A row is one case asked of the problem's published version on one night, with the result cache
off. The nightly job writes them; the Checks panel marks a case red when it passed the previous
night and fails tonight.
"""

from alembic import op

revision = "0076"
down_revision = "0075"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE suite_nightly (
            id                 bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            night              date NOT NULL,
            problem_id         bigint NOT NULL REFERENCES problem(id) ON DELETE CASCADE,
            model_version_id   bigint NOT NULL REFERENCES model_version(id) ON DELETE CASCADE,
            case_id            bigint NOT NULL REFERENCES suite_case(id) ON DELETE CASCADE,
            status             text,
            objective          numeric(15, 6),
            seconds            double precision,
            passed             boolean NOT NULL,
            reasons            jsonb NOT NULL DEFAULT '[]'::jsonb
                               CHECK (jsonb_typeof(reasons) = 'array'),
            organization_id    uuid NOT NULL REFERENCES iam.organization(id),
            UNIQUE (night, case_id, model_version_id)
        );
        CREATE INDEX suite_nightly_night_idx ON suite_nightly (night);
        CREATE INDEX suite_nightly_case_idx ON suite_nightly (case_id, model_version_id, night DESC);
        CREATE TRIGGER a_suite_nightly_tenant BEFORE INSERT OR UPDATE ON suite_nightly
            FOR EACH ROW EXECUTE FUNCTION tenant_inherit('problem:problem_id:bigint');
        ALTER TABLE suite_nightly ENABLE ROW LEVEL SECURITY;
        CREATE POLICY tenant_isolation ON suite_nightly
            USING (organization_id = app_org())
            WITH CHECK (organization_id = app_org());
        GRANT SELECT, INSERT, UPDATE, DELETE ON suite_nightly TO solver_app;
        GRANT USAGE, SELECT ON SEQUENCE suite_nightly_id_seq TO solver_app;
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE suite_nightly")
