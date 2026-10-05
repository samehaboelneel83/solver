"""0109: the Assistant's conversations kept on the server.

Until now the browser held the conversation and sent all of it back with every message: the brief,
every tool call and result, and the attached files' rows. A layout problem's history passed 1 MB and the
web server refused the request ("413 Request Entity Too Large", October 2026). Now the browser sends only
the new message and the conversation's id; the history, the attached files and the turn count live here.

One row per conversation, owned by the person (`owner_id`); a tenant table, its organization inherited
from the owner. `messages` is the history as the model is sent it (summarized when long, app.agent.compact);
`files` the attached files as read. Kept as long as the person keeps the conversation: a new chat is a new
id, and old ones are swept after 30 days (app.agent.store.sweep).
"""

from alembic import op

revision = "0109"
down_revision = "0108"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE agent_conversation (
            id              text PRIMARY KEY CHECK (id ~ '^[A-Za-z0-9_-]{1,64}$'),
            organization_id uuid NOT NULL REFERENCES iam.organization(id),
            owner_id        uuid NOT NULL REFERENCES iam.user_account(id) ON DELETE CASCADE,
            mode            text NOT NULL DEFAULT 'assistant',
            messages        jsonb NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(messages) = 'array'),
            files           jsonb NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(files) = 'array'),
            turns           integer NOT NULL DEFAULT 0,
            created_at      timestamptz NOT NULL DEFAULT clock_timestamp(),
            updated_at      timestamptz NOT NULL DEFAULT clock_timestamp()
        );
        CREATE INDEX agent_conversation_owner_idx ON agent_conversation (owner_id, updated_at DESC);
        CREATE INDEX agent_conversation_organization_idx ON agent_conversation (organization_id);
        CREATE TRIGGER agent_conversation_set_updated_at BEFORE UPDATE ON agent_conversation
            FOR EACH ROW EXECUTE FUNCTION set_updated_at();
        CREATE TRIGGER a_agent_conversation_tenant BEFORE INSERT OR UPDATE ON agent_conversation
            FOR EACH ROW EXECUTE FUNCTION tenant_inherit('iam.user_account:owner_id:uuid');
        ALTER TABLE agent_conversation ENABLE ROW LEVEL SECURITY;
        CREATE POLICY tenant_all ON agent_conversation
            USING (organization_id = app_org() OR app_is_operator())
            WITH CHECK (organization_id = app_org() OR app_is_operator());
        GRANT SELECT, INSERT, UPDATE, DELETE ON agent_conversation TO solver_app;
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS agent_conversation")
