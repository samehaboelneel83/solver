"""schema v1 PROBLEM + RUN halves: template, problem, model_version,
scenario, dataset, run, solution, constraint_result

Builds on 0006, which dropped both v0 schemas and created the eight v1
DOMAIN tables in `public`. This migration adds the remaining eight v1
tables, the `run_status` enum, the hashing / immutability / versioning
triggers, `snapshot_dataset()` and the `run_overview` view.

The DDL is taken from `docs/schema/2026-09-18-schema-v1.sql` with the one
amendment in this half's scope, per the design spec (§3):

  (b) `next_model_version()` takes a transaction-scoped advisory lock on
      the problem before reading `max(version)`. Without it two concurrent
      inserts for one problem compute the same number and collide on
      UNIQUE (problem_id, version). The single-argument
      `pg_advisory_xact_lock(bigint)` form is used so `problem_id` goes in
      as-is; the two-argument `(int, int)` form would need a lossy
      downcast. This is the only advisory lock in the schema, so there is
      no key space to share yet -- any later one must document one.

Amendments (a) and (c) applied to the DOMAIN validation triggers and were
made in 0006. The triggers created here (`set_hash`, `forbid_update`,
`next_model_version`) and `snapshot_dataset()` are unamended: their
`RAISE EXCEPTION`s stay bare P0001, because none of them reports a
user-correctable *field* -- an immutability violation is a bug in the
caller, not bad input, and a snapshot failure names an IR set or
parameter that has no counterpart in the domain.

Four tables are immutable by trigger: `model_version`, `dataset`,
`solution`, `constraint_result`. `app.models.v1_problem.IMMUTABLE_TABLES`
mirrors that set for the API layer.

The `iam` schema is untouched.

Revision ID: 0007
Revises: 0006
Create Date: 2026-09-19

"""
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # -- PROBLEM ---------------------------------------------------------
    op.execute(
        """
        -- A template is seed data: the types/params to create plus a starting IR.
        CREATE TABLE template (
            id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            name         text  NOT NULL UNIQUE,
            ir_version   text  NOT NULL,
            domain_seed  jsonb NOT NULL DEFAULT '{}',
            default_ir   jsonb NOT NULL
        );

        CREATE TABLE problem (
            id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            domain_id    bigint NOT NULL REFERENCES domain ON DELETE CASCADE,
            template_id  bigint REFERENCES template,
            name         text   NOT NULL,
            owner        text,
            created_at   timestamptz NOT NULL DEFAULT now(),
            UNIQUE (domain_id, name)
        );

        -- Immutable. Editing a model = inserting the next version.
        CREATE TABLE model_version (
            id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            problem_id  bigint NOT NULL REFERENCES problem ON DELETE CASCADE,
            version     int    NOT NULL,
            ir          jsonb  NOT NULL,
            ir_hash     text   NOT NULL,             -- set by trigger
            note        text,
            created_at  timestamptz NOT NULL DEFAULT now(),
            UNIQUE (problem_id, version)
        );

        -- What-if = a patch over one model version. Shape matches
        -- ProblemIR.patched():
        --   {"disable": ["c_x"], "harden": ["c_y"], "soften": {"c_z": 100}}
        CREATE TABLE scenario (
            id                bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            problem_id        bigint NOT NULL REFERENCES problem ON DELETE CASCADE,
            model_version_id  bigint NOT NULL REFERENCES model_version,
            name              text   NOT NULL,
            patch             jsonb  NOT NULL DEFAULT '{}',
            created_at        timestamptz NOT NULL DEFAULT now(),
            UNIQUE (problem_id, name)
        );
        """
    )

    # -- RUNS ------------------------------------------------------------
    op.execute(
        """
        -- Frozen copy of the domain data, in exactly the JSON shape
        -- psp/data.py reads.
        CREATE TABLE dataset (
            id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            problem_id  bigint NOT NULL REFERENCES problem ON DELETE CASCADE,
            data        jsonb  NOT NULL,
            data_hash   text   NOT NULL,             -- set by trigger
            created_at  timestamptz NOT NULL DEFAULT now(),
            UNIQUE (problem_id, data_hash)           -- identical snapshots are shared
        );

        CREATE TYPE run_status AS ENUM
            ('queued', 'running', 'optimal', 'feasible', 'infeasible', 'unknown', 'error');

        CREATE TABLE run (
            id                bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            scenario_id       bigint NOT NULL REFERENCES scenario ON DELETE CASCADE,
            dataset_id        bigint NOT NULL REFERENCES dataset,
            status            run_status NOT NULL DEFAULT 'queued',
            solver            text NOT NULL DEFAULT 'cp-sat',
            solver_version    text,
            compiler_version  text,
            params            jsonb NOT NULL DEFAULT '{}',   -- time_limit, workers...
            seed              int   NOT NULL DEFAULT 1,
            objective         bigint,
            wall_time_s       double precision,
            -- infeasible: [{"constraint_id": "...", "instance": [...]}]
            conflict          jsonb,
            conflict_minimal  boolean,
            error             text,
            queued_at         timestamptz NOT NULL DEFAULT now(),
            started_at        timestamptz,
            finished_at       timestamptz
        );
        CREATE INDEX run_scenario_idx ON run (scenario_id, queued_at DESC);
        CREATE INDEX run_queue_idx    ON run (queued_at) WHERE status = 'queued';

        CREATE TABLE solution (
            run_id       bigint PRIMARY KEY REFERENCES run ON DELETE CASCADE,
            -- {"assign": [["ahmed","mon","morning","hq"], ...]}
            assignments  jsonb NOT NULL
        );

        -- Normalized on purpose: this is what you query ACROSS runs.
        CREATE TABLE constraint_result (
            run_id           bigint  NOT NULL REFERENCES run ON DELETE CASCADE,
            constraint_id    text    NOT NULL,
            label            text    NOT NULL,
            hard             boolean NOT NULL,
            satisfied        boolean NOT NULL,
            total_violation  int     NOT NULL DEFAULT 0,
            penalty_paid     bigint  NOT NULL DEFAULT 0,
            -- [{"instance": [...], "amount": 1}]
            violations       jsonb   NOT NULL DEFAULT '[]',
            PRIMARY KEY (run_id, constraint_id)
        );
        CREATE INDEX constraint_result_violated_idx
            ON constraint_result (constraint_id) WHERE NOT satisfied;
        """
    )

    # -- hashing + immutability ------------------------------------------
    op.execute(
        """
        CREATE FUNCTION set_hash() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_TABLE_NAME = 'model_version' THEN
                NEW.ir_hash := encode(sha256(convert_to(NEW.ir::text, 'UTF8')), 'hex');
            ELSE
                NEW.data_hash := encode(sha256(convert_to(NEW.data::text, 'UTF8')), 'hex');
            END IF;
            RETURN NEW;
        END $$;
        CREATE TRIGGER model_version_hash BEFORE INSERT ON model_version
            FOR EACH ROW EXECUTE FUNCTION set_hash();
        CREATE TRIGGER dataset_hash       BEFORE INSERT ON dataset
            FOR EACH ROW EXECUTE FUNCTION set_hash();

        CREATE FUNCTION forbid_update() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION '% rows are immutable; insert a new row instead', TG_TABLE_NAME;
        END $$;
        CREATE TRIGGER model_version_immutable     BEFORE UPDATE ON model_version
            FOR EACH ROW EXECUTE FUNCTION forbid_update();
        CREATE TRIGGER dataset_immutable           BEFORE UPDATE ON dataset
            FOR EACH ROW EXECUTE FUNCTION forbid_update();
        CREATE TRIGGER solution_immutable          BEFORE UPDATE ON solution
            FOR EACH ROW EXECUTE FUNCTION forbid_update();
        CREATE TRIGGER constraint_result_immutable BEFORE UPDATE ON constraint_result
            FOR EACH ROW EXECUTE FUNCTION forbid_update();
        """
    )

    # Amendment (b): serialise concurrent inserts for one problem, so two
    # transactions cannot both read the same max(version).
    op.execute(
        """
        CREATE FUNCTION next_model_version() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF NEW.version IS NULL THEN
                PERFORM pg_advisory_xact_lock(NEW.problem_id);
                SELECT coalesce(max(version), 0) + 1 INTO NEW.version
                  FROM model_version WHERE problem_id = NEW.problem_id;
            END IF;
            RETURN NEW;
        END $$;
        CREATE TRIGGER model_version_number BEFORE INSERT ON model_version
            FOR EACH ROW EXECUTE FUNCTION next_model_version();
        """
    )

    # -- snapshot: live domain tables -> frozen dataset -------------------
    # Reads the set and parameter names from the IR and resolves them against
    # the problem's domain. Returns an existing dataset id if nothing changed.
    op.execute(
        """
        CREATE FUNCTION snapshot_dataset(p_model_version bigint) RETURNS bigint
        LANGUAGE plpgsql AS $$
        DECLARE
            v_problem bigint; v_domain bigint; v_ir jsonb;
            v_sets jsonb := '{}'; v_params jsonb := '{}';
            v_name text; v_rows jsonb; v_data jsonb; v_id bigint; v_hash text;
        BEGIN
            SELECT mv.problem_id, p.domain_id, mv.ir INTO v_problem, v_domain, v_ir
              FROM model_version mv JOIN problem p ON p.id = mv.problem_id
             WHERE mv.id = p_model_version;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'model_version % not found', p_model_version;
            END IF;

            FOR v_name IN SELECT jsonb_array_elements_text(v_ir -> 'sets') LOOP
                IF NOT EXISTS (SELECT 1 FROM entity_type
                               WHERE domain_id = v_domain AND name = v_name) THEN
                    RAISE EXCEPTION 'IR set "%" has no entity_type in this domain', v_name;
                END IF;
                SELECT coalesce(jsonb_agg(jsonb_build_object('id', e.key) || e.attrs
                                          ORDER BY e.sort_order, e.key), '[]')
                  INTO v_rows
                  FROM entity e JOIN entity_type t ON t.id = e.entity_type_id
                 WHERE t.domain_id = v_domain AND t.name = v_name AND e.active;
                v_sets := v_sets || jsonb_build_object(v_name, v_rows);
            END LOOP;

            FOR v_name IN SELECT jsonb_object_keys(coalesce(v_ir -> 'parameters', '{}')) LOOP
                IF NOT EXISTS (SELECT 1 FROM parameter_def
                               WHERE domain_id = v_domain AND name = v_name) THEN
                    RAISE EXCEPTION 'IR parameter "%" has no parameter_def in this domain', v_name;
                END IF;
                SELECT coalesce(jsonb_agg(row_json ORDER BY row_json::text), '[]')
                  INTO v_rows FROM (
                    SELECT jsonb_object_agg(t.name, e.key)
                           || jsonb_build_object('value', pv.value) AS row_json
                      FROM parameter_def pd
                      JOIN parameter_value pv ON pv.parameter_def_id = pd.id
                      CROSS JOIN LATERAL unnest(pv.entity_ids) AS u(eid)
                      JOIN entity e ON e.id = u.eid
                      JOIN entity_type t ON t.id = e.entity_type_id
                     WHERE pd.domain_id = v_domain AND pd.name = v_name
                     GROUP BY pv.parameter_def_id, pv.entity_ids, pv.value
                    HAVING bool_and(e.active)) q;
                v_params := v_params || jsonb_build_object(v_name, v_rows);
            END LOOP;

            v_data := jsonb_build_object('sets', v_sets, 'parameters', v_params);
            v_hash := encode(sha256(convert_to(v_data::text, 'UTF8')), 'hex');
            SELECT id INTO v_id FROM dataset
             WHERE problem_id = v_problem AND data_hash = v_hash;
            IF v_id IS NULL THEN
                INSERT INTO dataset (problem_id, data) VALUES (v_problem, v_data)
                RETURNING id INTO v_id;
            END IF;
            RETURN v_id;
        END $$;
        """
    )

    # -- convenience views -----------------------------------------------
    op.execute(
        """
        CREATE VIEW run_overview AS
        SELECT r.id AS run_id, p.name AS problem, s.name AS scenario,
               mv.version AS model_version,
               r.dataset_id, r.status, r.objective, r.wall_time_s, r.finished_at,
               (SELECT count(*) FROM constraint_result c
                 WHERE c.run_id = r.id AND NOT c.satisfied) AS violated,
               (SELECT coalesce(sum(penalty_paid), 0) FROM constraint_result c
                 WHERE c.run_id = r.id) AS penalty
          FROM run r
          JOIN scenario s       ON s.id  = r.scenario_id
          JOIN model_version mv ON mv.id = s.model_version_id
          JOIN problem p        ON p.id  = s.problem_id;
        """
    )


def downgrade() -> None:
    # Destructive by design (spec §8), like 0006: downgrading drops the v1
    # PROBLEM and RUN tables and everything in them. Runs, solutions and the
    # frozen dataset snapshots they were reproducible from are unrecoverable
    # -- restore from a database backup if you need them.
    op.execute(
        """
        DROP VIEW IF EXISTS run_overview;

        DROP TRIGGER IF EXISTS model_version_number ON model_version;
        DROP TRIGGER IF EXISTS constraint_result_immutable ON constraint_result;
        DROP TRIGGER IF EXISTS solution_immutable ON solution;
        DROP TRIGGER IF EXISTS dataset_immutable ON dataset;
        DROP TRIGGER IF EXISTS model_version_immutable ON model_version;
        DROP TRIGGER IF EXISTS dataset_hash ON dataset;
        DROP TRIGGER IF EXISTS model_version_hash ON model_version;

        DROP FUNCTION IF EXISTS snapshot_dataset(bigint);
        DROP FUNCTION IF EXISTS next_model_version();
        DROP FUNCTION IF EXISTS forbid_update();
        DROP FUNCTION IF EXISTS set_hash();

        DROP TABLE IF EXISTS constraint_result;
        DROP TABLE IF EXISTS solution;
        DROP TABLE IF EXISTS run;
        DROP TABLE IF EXISTS dataset;
        DROP TABLE IF EXISTS scenario;
        DROP TABLE IF EXISTS model_version;
        DROP TABLE IF EXISTS problem;
        DROP TABLE IF EXISTS template;

        DROP TYPE IF EXISTS run_status;
        """
    )
