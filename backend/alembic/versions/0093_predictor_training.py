"""0093: a predictor trains in the background (operator trial F31).

Training ran inside the web request: nine records took ten seconds with only
"Training..." shown, and a large set risked a proxy timeout. A training is now
a row here that the request answers at once; the page asks after it until it
is done (with the predictor it made) or failed (with why).
"""

from alembic import op

revision = "0093"
down_revision = "0092"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE predictor_training (
            id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            organization_id uuid NOT NULL REFERENCES iam.organization(id),
            domain_id       bigint NOT NULL REFERENCES domain(id) ON DELETE CASCADE,
            request         jsonb NOT NULL CHECK (jsonb_typeof(request) = 'object'),
            state           text NOT NULL DEFAULT 'running' CHECK (state IN ('running', 'done', 'failed')),
            predictor_id    bigint REFERENCES predictor(id) ON DELETE SET NULL,
            error           text CHECK (error IS NULL OR length(error) <= 4000),
            created_by      uuid REFERENCES iam.user_account(id) ON DELETE SET NULL,
            created_at      timestamptz NOT NULL DEFAULT now(),
            finished_at     timestamptz,
            CHECK ((state = 'running') = (finished_at IS NULL)),
            CHECK (state <> 'failed' OR error IS NOT NULL)
        );
        CREATE INDEX predictor_training_domain_idx ON predictor_training (domain_id, id DESC);
        CREATE TRIGGER a_predictor_training_tenant BEFORE INSERT OR UPDATE ON predictor_training
            FOR EACH ROW EXECUTE FUNCTION tenant_inherit('domain:domain_id:bigint');
        ALTER TABLE predictor_training ENABLE ROW LEVEL SECURITY;
        CREATE POLICY tenant_all ON predictor_training
            USING (organization_id = app_org() OR app_is_operator())
            WITH CHECK (organization_id = app_org() OR app_is_operator());
        GRANT SELECT, INSERT, UPDATE ON predictor_training TO solver_app;
        GRANT USAGE, SELECT ON SEQUENCE predictor_training_id_seq TO solver_app;
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS predictor_training")
