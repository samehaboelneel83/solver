"""0077: append-only audit log (queue R34).

`iam.audit_event` records who did what to which object. Rows are insert-only:
UPDATE and DELETE are refused unless the session sets ``app.audit_prune=1``
for the nightly retention job. Retention defaults to 400 days
(``audit.retention_days``).
"""

from alembic import op

revision = "0077"
down_revision = "0076"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE iam.audit_event (
            id               bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            at               timestamptz NOT NULL DEFAULT now(),
            organization_id  uuid NOT NULL REFERENCES iam.organization(id),
            actor_id         uuid,
            api_key_id       uuid,
            action           text NOT NULL,
            object_type      text,
            object_id        text,
            before_hash      text,
            after_hash       text,
            ip               inet
        );
        CREATE INDEX audit_event_org_at_idx ON iam.audit_event (organization_id, at DESC);
        CREATE INDEX audit_event_action_idx ON iam.audit_event (action, at DESC);
        CREATE INDEX audit_event_object_idx ON iam.audit_event (object_type, object_id);

        CREATE FUNCTION iam.audit_append_only() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'DELETE' AND current_setting('app.audit_prune', true) = '1' THEN
                RETURN OLD;
            END IF;
            RAISE EXCEPTION 'audit_event rows are append-only';
        END $$;
        CREATE TRIGGER audit_event_append_only
            BEFORE UPDATE OR DELETE ON iam.audit_event
            FOR EACH ROW EXECUTE FUNCTION iam.audit_append_only();

        ALTER TABLE iam.audit_event ENABLE ROW LEVEL SECURITY;
        CREATE POLICY tenant_read ON iam.audit_event FOR SELECT
            USING (organization_id = app_org() OR app_is_operator());
        CREATE POLICY tenant_insert ON iam.audit_event FOR INSERT
            WITH CHECK (organization_id = app_org() OR app_is_operator());
        CREATE POLICY tenant_delete ON iam.audit_event FOR DELETE
            USING (app_is_operator() OR current_setting('app.audit_prune', true) = '1');

        GRANT SELECT, INSERT, DELETE ON iam.audit_event TO solver_app;
        GRANT USAGE, SELECT ON SEQUENCE iam.audit_event_id_seq TO solver_app;

        INSERT INTO setting_key (key, value_type, default_value, description)
        VALUES (
            'audit.retention_days',
            'number',
            CAST('400' AS jsonb),
            'Days to keep audit_event rows; the nightly prune removes older ones and records itself'
        );
        """
    )


def downgrade() -> None:
    op.execute("DELETE FROM setting WHERE key = 'audit.retention_days'")
    op.execute("DELETE FROM setting_key WHERE key = 'audit.retention_days'")
    op.execute("DROP TABLE iam.audit_event")
    op.execute("DROP FUNCTION IF EXISTS iam.audit_append_only()")
