"""The role the running app logs in as: not a superuser.

The API and the worker used to connect as the database's superuser -- the
owner every migration runs as. Tenant isolation (0032) holds against the
app's own bugs, but a SQL injection would still have run with superuser
rights: DDL, turning row-level security or the tenancy triggers off,
creating roles, reading the server's files.

`solver_runtime` is what they connect as instead:

* NOSUPERUSER, NOCREATEDB, NOCREATEROLE, and it owns nothing -- so it can
  neither change a table nor switch off a policy or a trigger on one.
* Reads and writes every product table, and may `SET ROLE solver_app`,
  which is how a request enters its tenant.
* BYPASSRLS. System code -- the worker's queue, which every tenant shares;
  signing in, before the tenant is known; the start-up seed -- sees every
  organization by design (0032). Once a request has switched to
  `solver_app`, the policies apply as before: row-level security follows
  the current role, not the one that logged in.

What this does NOT close: `RESET ROLE` needs no privilege, so a statement
injected into a request could step back from `solver_app` to this role and
read or write every tenant. Removing that needs API requests to log in as a
role without BYPASSRLS, with the lookups made before the tenant is known
(signing in, API keys) done another way; it is its own item in the
execution queue. This one removes what only a superuser could do.

Created NOLOGIN: a password does not belong in the repository.
`scripts/runtime_role.sh` gives it one at deploy time and writes the URL
the app uses to `.env.runtime`; migrations keep running as the owner.
Roles are cluster-wide, so the downgrade takes back what this database
granted and leaves the role for any other database that uses it -- as
0032 does with `solver_app`.
"""

from alembic import op

revision = "0037"
down_revision = "0036"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'solver_runtime') THEN
                CREATE ROLE solver_runtime NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
                    NOREPLICATION BYPASSRLS;
            END IF;
        END;
        $$;
        GRANT solver_app TO solver_runtime;
        GRANT USAGE ON SCHEMA public, iam TO solver_runtime;
        GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public, iam TO solver_runtime;
        GRANT USAGE, SELECT, UPDATE ON ALL SEQUENCES IN SCHEMA public, iam TO solver_runtime;
        ALTER DEFAULT PRIVILEGES IN SCHEMA public, iam
            GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO solver_runtime;
        ALTER DEFAULT PRIVILEGES IN SCHEMA public, iam
            GRANT USAGE, SELECT, UPDATE ON SEQUENCES TO solver_runtime;
        -- Which migration the schema is at is the owner's business.
        REVOKE ALL ON alembic_version FROM solver_runtime;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER DEFAULT PRIVILEGES IN SCHEMA public, iam REVOKE ALL ON TABLES FROM solver_runtime;
        ALTER DEFAULT PRIVILEGES IN SCHEMA public, iam REVOKE ALL ON SEQUENCES FROM solver_runtime;
        REVOKE ALL ON ALL TABLES IN SCHEMA public, iam FROM solver_runtime;
        REVOKE ALL ON ALL SEQUENCES IN SCHEMA public, iam FROM solver_runtime;
        REVOKE USAGE ON SCHEMA public, iam FROM solver_runtime;
        REVOKE solver_app FROM solver_runtime;
        """
    )
