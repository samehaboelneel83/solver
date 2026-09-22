"""Tenancy: every row belongs to an organization, and the database enforces it.

Target roadmap Phase 7 and defect D1: any signed-in user could list and
cancel any tenant's runs, because nothing below `iam` knew what a tenant was.

**A tenant is an `iam.organization`** (the roadmap's stated assumption), and
a domain belongs to exactly one. Every tenant table carries
`organization_id` -- principle 8, "tenancy is a column, not a convention" --
and only `domain` (and `iam.user_account`) choose it: every other row takes
its organization from its parent in a trigger, so no insert in the
application had to change, and a row whose parents belong to different
organizations is refused. Postgres checks foreign keys without row-level
security, so without that check a tenant could point a scenario at another
tenant's model version by guessing its id.

**Row-level security, for a role that is subject to it.** The application
connects as a superuser, and superusers bypass RLS. So API requests switch
to `solver_app` -- NOLOGIN, no superuser, no BYPASSRLS -- once they know who
is asking, and set `app.org_id`. Its policies show a row only when its
organization is the request's, and with no `app.org_id` it sees nothing:
the policies fail closed. System code -- the worker, the seed, migrations --
stays on the connecting role and sees every organization, which is what a
queue shared by all tenants needs.

**Global definitions stay global.** Roles, capabilities, setting keys and
templates are one vocabulary for everyone: readable by every tenant,
writable only by an operator organization (`iam.organization.is_operator`,
true for the seed `default` organization). Platform-level settings (no
organization) follow the same rule, since they govern every tenant's runs.

Backfill: every existing row belongs to the `default` organization, and so
does every user who had none.
"""

from alembic import op

revision = "0032"
down_revision = "0031"
branch_labels = None
depends_on = None

# (table, [(parent table, column, id type), ...]). The first parent that is
# set decides the organization; the rest must agree with it.
_INHERIT = [
    ("entity_type", [("domain", "domain_id", "bigint")]),
    (
        "relationship_type",
        [("domain", "domain_id", "bigint"), ("entity_type", "from_type_id", "bigint"), ("entity_type", "to_type_id", "bigint")],
    ),
    ("parameter_def", [("domain", "domain_id", "bigint")]),
    ("problem", [("domain", "domain_id", "bigint")]),
    (
        "attribute_def",
        [("entity_type", "entity_type_id", "bigint"), ("relationship_type", "relationship_type_id", "bigint")],
    ),
    ("entity", [("entity_type", "entity_type_id", "bigint")]),
    (
        "relationship",
        [("relationship_type", "relationship_type_id", "bigint"), ("entity", "from_entity_id", "bigint"), ("entity", "to_entity_id", "bigint")],
    ),
    ("parameter_value", [("parameter_def", "parameter_def_id", "bigint")]),
    ("model_version", [("problem", "problem_id", "bigint")]),
    ("scenario", [("problem", "problem_id", "bigint"), ("model_version", "model_version_id", "bigint")]),
    ("dataset", [("problem", "problem_id", "bigint")]),
    ("run", [("scenario", "scenario_id", "bigint"), ("dataset", "dataset_id", "bigint")]),
    ("solution", [("run", "run_id", "bigint")]),
    ("constraint_result", [("run", "run_id", "bigint")]),
    ("iam.user_role", [("iam.user_account", "user_id", "uuid")]),
]

# Frozen by `forbid_update()`: the backfill must pass under it once.
_IMMUTABLE = {
    "model_version": "model_version_immutable",
    "dataset": "dataset_immutable",
    "solution": "solution_immutable",
    "constraint_result": "constraint_result_immutable",
}

_TENANT_TABLES = ["domain", *[table for table, _ in _INHERIT if table != "iam.user_role"]]
_GLOBAL_TABLES = ["template", "setting_key", "iam.role", "iam.role_capability", "iam.capability"]


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE iam.organization ADD COLUMN is_operator boolean NOT NULL DEFAULT false;
        UPDATE iam.organization SET is_operator = true WHERE code = 'default';

        UPDATE iam.user_account SET organization_id = (SELECT id FROM iam.organization WHERE code = 'default')
         WHERE organization_id IS NULL;

        -- The request's organization, or NULL outside a request. `nullif`:
        -- a custom setting that was set and reset reads as '' afterwards.
        CREATE FUNCTION app_org() RETURNS uuid LANGUAGE sql STABLE AS $$
            SELECT nullif(current_setting('app.org_id', true), '')::uuid
        $$;

        -- SECURITY DEFINER so the lookup is not itself filtered by the
        -- organization policy that calls it.
        CREATE FUNCTION app_is_operator() RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER
            SET search_path = pg_catalog, public AS $$
            SELECT coalesce((SELECT is_operator FROM iam.organization WHERE id = app_org()), false)
        $$;
        """
    )

    # -- the column, backfilled parent-first ----------------------------------------
    op.execute(
        """
        ALTER TABLE domain ADD COLUMN organization_id uuid REFERENCES iam.organization(id);
        UPDATE domain SET organization_id = (SELECT id FROM iam.organization WHERE code = 'default');
        """
    )
    for table, parents in _INHERIT:
        op.execute(f"ALTER TABLE {table} ADD COLUMN organization_id uuid REFERENCES iam.organization(id)")
        trigger = _IMMUTABLE.get(table)
        if trigger:
            op.execute(f"ALTER TABLE {table} DISABLE TRIGGER {trigger}")
        for parent, column, _ in parents:
            op.execute(
                f"UPDATE {table} c SET organization_id = p.organization_id FROM {parent} p"
                f" WHERE p.id = c.{column} AND c.organization_id IS NULL"
            )
        if trigger:
            op.execute(f"ALTER TABLE {table} ENABLE TRIGGER {trigger}")
    for table in ["domain", *[t for t, _ in _INHERIT]]:
        op.execute(f"ALTER TABLE {table} ALTER COLUMN organization_id SET NOT NULL")
        op.execute(f"CREATE INDEX {table.replace('.', '_')}_organization_idx ON {table} (organization_id)")

    op.execute(
        """
        ALTER TABLE setting ADD COLUMN organization_id uuid REFERENCES iam.organization(id);
        UPDATE setting s SET organization_id = d.organization_id FROM domain d
         WHERE s.scope = 'domain' AND d.id = s.scope_id;
        UPDATE setting s SET organization_id = p.organization_id FROM problem p
         WHERE s.scope = 'problem' AND p.id = s.scope_id;
        ALTER TABLE setting ADD CONSTRAINT setting_organization_matches_scope CHECK (
            (scope = 'platform') = (organization_id IS NULL)
        );

        -- Two tenants may both call a domain "Workforce".
        ALTER TABLE domain DROP CONSTRAINT domain_name_key;
        ALTER TABLE domain ADD CONSTRAINT domain_organization_name_key UNIQUE (organization_id, name);

        ALTER TABLE iam.user_account ALTER COLUMN organization_id SET NOT NULL;
        """
    )

    # -- triggers: who a new row belongs to ------------------------------------------
    op.execute(
        """
        -- The roots. Inside a request the organization is the request's;
        -- system code that names none gets the seed organization.
        CREATE FUNCTION tenant_root() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'UPDATE' THEN
                IF NEW.organization_id IS DISTINCT FROM OLD.organization_id THEN
                    RAISE EXCEPTION 'a row cannot move to another organization' USING ERRCODE = '23514';
                END IF;
                RETURN NEW;
            END IF;
            NEW.organization_id := coalesce(
                NEW.organization_id,
                app_org(),
                (SELECT id FROM iam.organization WHERE code = 'default')
            );
            IF app_org() IS NOT NULL AND NEW.organization_id <> app_org() AND NOT app_is_operator() THEN
                RAISE EXCEPTION 'a row cannot be created in another organization' USING ERRCODE = '42501';
            END IF;
            RETURN NEW;
        END;
        $$;

        -- Everything else: the organization of its parents, which must agree.
        -- Arguments are 'table:column:idtype' triples. A parent this caller
        -- cannot see -- another tenant's, filtered out by RLS -- is reported
        -- as missing (P0002; the API answers 409, as for any missing parent), exactly as one that does not exist.
        CREATE FUNCTION tenant_inherit() RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE
            i int;
            parent text;
            col text;
            idtype text;
            ref text;
            found uuid;
            org uuid;
        BEGIN
            IF TG_OP = 'UPDATE' AND NEW.organization_id IS DISTINCT FROM OLD.organization_id THEN
                RAISE EXCEPTION 'a row cannot move to another organization' USING ERRCODE = '23514';
            END IF;
            FOR i IN 0 .. TG_NARGS - 1 LOOP
                parent := split_part(TG_ARGV[i], ':', 1);
                col := split_part(TG_ARGV[i], ':', 2);
                idtype := split_part(TG_ARGV[i], ':', 3);
                ref := to_jsonb(NEW) ->> col;
                CONTINUE WHEN ref IS NULL;
                EXECUTE format('SELECT organization_id FROM %s WHERE id = CAST($1 AS %s)', parent, idtype)
                   INTO found USING ref;
                IF found IS NULL THEN
                    RAISE EXCEPTION 'no % with id %', parent, ref USING ERRCODE = 'P0002';
                END IF;
                IF org IS NULL THEN
                    org := found;
                ELSIF found <> org THEN
                    RAISE EXCEPTION '% % belongs to another organization', parent, ref USING ERRCODE = 'P0002';
                END IF;
            END LOOP;
            IF NEW.organization_id IS NULL THEN
                NEW.organization_id := org;
            ELSIF org IS NOT NULL AND NEW.organization_id <> org THEN
                RAISE EXCEPTION 'a row must belong to its parent''s organization' USING ERRCODE = 'P0002';
            END IF;
            RETURN NEW;
        END;
        $$;

        -- A setting belongs to the organization of what it is scoped to; a
        -- platform setting to none.
        CREATE FUNCTION tenant_setting() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF NEW.scope = 'domain' THEN
                NEW.organization_id := (SELECT organization_id FROM domain WHERE id = NEW.scope_id);
            ELSIF NEW.scope = 'problem' THEN
                NEW.organization_id := (SELECT organization_id FROM problem WHERE id = NEW.scope_id);
            ELSE
                NEW.organization_id := NULL;
            END IF;
            RETURN NEW;
        END;
        $$;

        CREATE TRIGGER domain_tenant BEFORE INSERT OR UPDATE ON domain
            FOR EACH ROW EXECUTE FUNCTION tenant_root();
        CREATE TRIGGER user_account_tenant BEFORE INSERT OR UPDATE ON iam.user_account
            FOR EACH ROW EXECUTE FUNCTION tenant_root();
        -- Named to sort before `setting_scope_exists`, which reports a scope
        -- that does not exist in words; this one only fills the column.
        CREATE TRIGGER setting_a_tenant BEFORE INSERT OR UPDATE ON setting
            FOR EACH ROW EXECUTE FUNCTION tenant_setting();
        """
    )
    for table, parents in _INHERIT:
        args = ", ".join(f"'{parent}:{column}:{idtype}'" for parent, column, idtype in parents)
        # Named `a_...` so it fires before the table's own validation
        # triggers, which then see a row that already knows its tenant.
        name = f"a_{table.replace('.', '_')}_tenant"
        op.execute(
            f"CREATE TRIGGER {name} BEFORE INSERT OR UPDATE ON {table}"
            f" FOR EACH ROW EXECUTE FUNCTION tenant_inherit({args})"
        )

    # -- the request role and its policies ---------------------------------------------
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'solver_app') THEN
                CREATE ROLE solver_app NOLOGIN NOSUPERUSER NOBYPASSRLS;
            END IF;
        END;
        $$;
        GRANT solver_app TO CURRENT_USER;
        GRANT USAGE ON SCHEMA public, iam TO solver_app;
        GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO solver_app;
        GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA iam TO solver_app;
        GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public, iam TO solver_app;
        ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO solver_app;
        ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO solver_app;
        -- Not the product's: nothing a request should read or write.
        REVOKE ALL ON alembic_version, bench_result FROM solver_app;
        """
    )
    for table in [*_TENANT_TABLES, "iam.user_role"]:
        op.execute(
            f"""
            ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;
            CREATE POLICY tenant_isolation ON {table}
                USING (organization_id = app_org())
                WITH CHECK (organization_id = app_org());
            """
        )
    op.execute(
        """
        -- Operators manage every organization's people; a tenant its own.
        ALTER TABLE iam.user_account ENABLE ROW LEVEL SECURITY;
        CREATE POLICY tenant_isolation ON iam.user_account
            USING (organization_id = app_org() OR app_is_operator())
            WITH CHECK (organization_id = app_org() OR app_is_operator());
        DROP POLICY tenant_isolation ON iam.user_role;
        CREATE POLICY tenant_isolation ON iam.user_role
            USING (organization_id = app_org() OR app_is_operator())
            WITH CHECK (organization_id = app_org() OR app_is_operator());

        -- Read and write are separate policies wherever they differ: a
        -- DELETE needs only the row to be visible, so one policy that let a
        -- tenant SEE its organization or a platform setting would also let
        -- it delete them.
        ALTER TABLE iam.organization ENABLE ROW LEVEL SECURITY;
        CREATE POLICY tenant_read ON iam.organization FOR SELECT
            USING (id = app_org() OR app_is_operator());
        CREATE POLICY written_by_operators ON iam.organization FOR ALL
            USING (app_is_operator()) WITH CHECK (app_is_operator());

        -- Platform settings: read by all, written by operators only.
        ALTER TABLE setting ENABLE ROW LEVEL SECURITY;
        CREATE POLICY tenant_read ON setting FOR SELECT
            USING (organization_id IS NULL OR organization_id = app_org());
        CREATE POLICY tenant_write ON setting FOR ALL
            USING ((organization_id IS NULL AND app_is_operator()) OR organization_id = app_org())
            WITH CHECK ((organization_id IS NULL AND app_is_operator()) OR organization_id = app_org());
        """
    )
    for table in _GLOBAL_TABLES:
        op.execute(
            f"""
            ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;
            CREATE POLICY read_by_all ON {table} FOR SELECT USING (true);
            CREATE POLICY written_by_operators ON {table} FOR ALL
                USING (app_is_operator()) WITH CHECK (app_is_operator());
            """
        )


def downgrade() -> None:
    for table in _GLOBAL_TABLES:
        op.execute(
            f"DROP POLICY written_by_operators ON {table}; DROP POLICY read_by_all ON {table};"
            f" ALTER TABLE {table} DISABLE ROW LEVEL SECURITY;"
        )
    for table in [*_TENANT_TABLES, "iam.user_role", "iam.user_account"]:
        op.execute(f"DROP POLICY tenant_isolation ON {table}; ALTER TABLE {table} DISABLE ROW LEVEL SECURITY;")
    op.execute(
        "DROP POLICY tenant_read ON setting; DROP POLICY tenant_write ON setting;"
        " ALTER TABLE setting DISABLE ROW LEVEL SECURITY;"
        " DROP POLICY tenant_read ON iam.organization; DROP POLICY written_by_operators ON iam.organization;"
        " ALTER TABLE iam.organization DISABLE ROW LEVEL SECURITY;"
    )
    for table, _ in _INHERIT:
        op.execute(f"DROP TRIGGER a_{table.replace('.', '_')}_tenant ON {table}")
    op.execute(
        """
        DROP TRIGGER domain_tenant ON domain;
        DROP TRIGGER user_account_tenant ON iam.user_account;
        DROP TRIGGER setting_a_tenant ON setting;
        DROP FUNCTION tenant_root();
        DROP FUNCTION tenant_inherit();
        DROP FUNCTION tenant_setting();
        ALTER TABLE iam.user_account ALTER COLUMN organization_id DROP NOT NULL;
        ALTER TABLE domain DROP CONSTRAINT domain_organization_name_key;
        ALTER TABLE domain ADD CONSTRAINT domain_name_key UNIQUE (name);
        ALTER TABLE setting DROP CONSTRAINT setting_organization_matches_scope;
        ALTER TABLE setting DROP COLUMN organization_id;
        """
    )
    for table in ["domain", *[t for t, _ in _INHERIT]]:
        op.execute(f"ALTER TABLE {table} DROP COLUMN organization_id")
    op.execute(
        """
        DROP FUNCTION app_is_operator();
        DROP FUNCTION app_org();
        ALTER TABLE iam.organization DROP COLUMN is_operator;
        REVOKE ALL ON ALL TABLES IN SCHEMA public, iam FROM solver_app;
        REVOKE ALL ON ALL SEQUENCES IN SCHEMA public, iam FROM solver_app;
        REVOKE USAGE ON SCHEMA public, iam FROM solver_app;
        ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON TABLES FROM solver_app;
        ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON SEQUENCES FROM solver_app;
        """
    )
