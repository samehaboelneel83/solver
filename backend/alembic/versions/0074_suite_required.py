"""0074: the gate (queue R30) -- setting `suite.required`.

A problem with acceptance cases (0073) puts a new model version into use -- points a scenario at a
version no scenario of it uses yet -- only once that version has passed every case. `suite.required`
(boolean, on by default) is how a problem or domain turns the gate off; a problem with no cases has
no gate either way.
"""

from alembic import op

revision = "0074"
down_revision = "0073"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "INSERT INTO setting_key (key, value_type, default_value, description)"
        " VALUES ('suite.required', 'boolean', CAST('true' AS jsonb),"
        "         'A new model version is put into use only once it passes every acceptance case of its problem')"
    )


def downgrade() -> None:
    op.execute("DELETE FROM setting WHERE key = 'suite.required'")
    op.execute("DELETE FROM setting_key WHERE key = 'suite.required'")
