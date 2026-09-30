"""0095: the app may ask which migration the database is at.

The Health page (app.api.health) says whether the database's migrations are
the ones this version of the platform expects. The app's own login may not
read `alembic_version` (0032, 0037: nothing a request should read or write),
and should not start to. This function returns the version string and nothing
else, running as the table's owner -- the same shape as `app_is_operator`.
"""

from alembic import op

revision = "0095"
down_revision = "0094"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE FUNCTION schema_version() RETURNS text
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS
        $$ SELECT version_num FROM alembic_version LIMIT 1 $$;
        REVOKE ALL ON FUNCTION schema_version() FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION schema_version() TO solver_app;
        """
    )


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS schema_version()")
