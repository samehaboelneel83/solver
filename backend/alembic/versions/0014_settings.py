"""0014: settings as data, at three levels.

Today the numbers that govern a solve are scattered: a time limit hardcoded
in the API's default, a solver chosen by the registry's rank, a thread count
fixed at 8 in the worker. Changing any of them is a deployment, which is the
opposite of what a platform is for -- and it means every domain gets the same
answer to a question that is properly per-domain. A scheduling model that
needs ninety seconds and a rostering model that needs three should not have
to share a number.

**Three levels, each overriding the last: platform, domain, problem.** The
most specific setting that exists wins, and where none exists the built-in
default does. That is the whole resolution rule, and it is deliberately the
simplest one that is useful: no inheritance graph, no priorities, no merge.

**Keys are rows, like capabilities (0013).** `setting.key` references
`setting_key`, so a typo is a foreign-key violation rather than a setting
nobody reads. Each key carries its type and the built-in default, so
resolution has somewhere to bottom out and a UI has something to render
without hardcoding the list.

**`scope_id` is polymorphic and therefore checked by a trigger**, not a
foreign key: it names a domain for `domain` and a problem for `problem`, and
nothing at all for `platform`. A CHECK pins which of those may be null; the
trigger pins that the row it names exists. Without it, a setting could point
at a deleted domain and quietly govern nothing -- and a second trigger
deletes a scope's settings when the scope goes, because an orphan here is
invisible rather than noisy.

The unique key uses `NULLS NOT DISTINCT`, so the platform level can hold one
row per key rather than any number of them: Postgres would otherwise treat
every `NULL` scope_id as different from every other.
"""

import sqlalchemy as sa
from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


# The starting vocabulary. `value` is jsonb so a setting can be a number, a
# string or a boolean without a column per type.
_KEYS = [
    ("solve.time_limit_s", "number", "10", "How long a solve may run before it reports the best it has"),
    ("solve.solver", "string", "null", "Which solver to use; null lets the platform choose and record why"),
    ("solve.workers", "number", "8", "Threads a solve may use"),
    ("solve.seed", "number", "1", "Random seed, so two runs of the same question agree"),
    ("run.retention_days", "number", "365", "How long answers are kept"),
]


def upgrade() -> None:
    op.execute(
        """
        CREATE TYPE setting_scope AS ENUM ('platform', 'domain', 'problem');

        CREATE TABLE setting_key (
            key           text PRIMARY KEY,
            value_type    text  NOT NULL CHECK (value_type IN ('number', 'string', 'boolean')),
            default_value jsonb NOT NULL,
            description   text  NOT NULL
        );

        CREATE TABLE setting (
            id         bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            scope      setting_scope NOT NULL,
            -- A domain id, a problem id, or nothing for the platform level.
            scope_id   bigint,
            key        text  NOT NULL REFERENCES setting_key(key) ON DELETE CASCADE,
            value      jsonb NOT NULL,
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT setting_scope_id_matches_scope CHECK (
                (scope = 'platform' AND scope_id IS NULL)
                OR (scope <> 'platform' AND scope_id IS NOT NULL)
            )
        );

        -- NULLS NOT DISTINCT, or the platform level could hold any number of
        -- rows for one key and "the setting" would be whichever was read.
        CREATE UNIQUE INDEX setting_one_per_scope
            ON setting (scope, scope_id, key) NULLS NOT DISTINCT;

        CREATE FUNCTION setting_scope_exists() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF NEW.scope = 'domain'
               AND NOT EXISTS (SELECT 1 FROM domain WHERE id = NEW.scope_id) THEN
                RAISE EXCEPTION 'setting scope domain % does not exist', NEW.scope_id
                    USING ERRCODE = '23503';
            ELSIF NEW.scope = 'problem'
               AND NOT EXISTS (SELECT 1 FROM problem WHERE id = NEW.scope_id) THEN
                RAISE EXCEPTION 'setting scope problem % does not exist', NEW.scope_id
                    USING ERRCODE = '23503';
            END IF;
            RETURN NEW;
        END;
        $$;

        CREATE TRIGGER setting_scope_exists
            BEFORE INSERT OR UPDATE ON setting
            FOR EACH ROW EXECUTE FUNCTION setting_scope_exists();

        -- A polymorphic scope_id gets no ON DELETE CASCADE, so the cascade is
        -- written out. An orphaned setting governs nothing and says nothing.
        CREATE FUNCTION setting_forget_scope() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            DELETE FROM setting
             WHERE scope = TG_ARGV[0]::setting_scope AND scope_id = OLD.id;
            RETURN OLD;
        END;
        $$;

        CREATE TRIGGER setting_forget_domain
            AFTER DELETE ON domain
            FOR EACH ROW EXECUTE FUNCTION setting_forget_scope('domain');

        CREATE TRIGGER setting_forget_problem
            AFTER DELETE ON problem
            FOR EACH ROW EXECUTE FUNCTION setting_forget_scope('problem');
        """
    )

    op.get_bind().execute(
        sa.text(
            "INSERT INTO setting_key (key, value_type, default_value, description)"
            " VALUES (:key, :value_type, CAST(:default_value AS jsonb), :description)"
        ),
        [
            {"key": k, "value_type": t, "default_value": d, "description": desc}
            for k, t, d, desc in _KEYS
        ],
    )


    # Changing what governs everyone's runs is its own decision, so it is its
    # own capability -- and a new capability is an INSERT, which is the point
    # of 0013 making the vocabulary a table.
    op.execute(
        """
        INSERT INTO iam.capability (code, "group", description)
        VALUES ('settings.edit', 'platform',
                'Change platform, domain and problem settings');

        INSERT INTO iam.role_capability (role_id, capability_code)
        SELECT id, 'settings.edit' FROM iam.role WHERE code IN ('admin', 'modeller');
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TRIGGER setting_forget_problem ON problem;
        DROP TRIGGER setting_forget_domain ON domain;
        DROP FUNCTION setting_forget_scope();
        DROP TRIGGER setting_scope_exists ON setting;
        DROP FUNCTION setting_scope_exists();
        DROP TABLE setting;
        DROP TABLE setting_key;
        DROP TYPE setting_scope;
        DELETE FROM iam.role_capability WHERE capability_code = 'settings.edit';
        DELETE FROM iam.capability WHERE code = 'settings.edit';
        """
    )
