"""0015: parameters become decimals, so a model can be continuous.

This is the schema decision the roadmap's Phase 2 said had to be taken before
any continuous solver was written, and it is the single thing standing between
this platform and linear programming. `parameter_value.value` and
`parameter_def.default_value` were `int` deliberately, for CP-SAT (spec §2).
The cost of that was not a missing feature but a missing *choice*: with one
expressible model class, the solver-selection policy had exactly one candidate
in every case and could not be wrong in a way anyone would notice.

**Why `numeric(15, 6)` and not `double precision`.** Two reasons, and both are
about being able to answer "why did I get this number".

- A dataset is content-hashed and a run is meant to be reproducible. Binary
  floating point does not round-trip through JSON identically across
  platforms, so `0.1` stored today could hash differently tomorrow. Decimal
  does not have that problem.
- Fifteen significant digits is exactly what an IEEE-754 double round-trips
  without loss. Solvers take doubles, so the conversion happens at that
  boundary whatever we store; choosing a precision the boundary preserves
  means the number the solver sees is the number that was typed. A wider
  `numeric` would silently lose digits there instead.

Six decimal places is a judgement: money, rates, hours and proportions need a
handful, and a quantity needing more is one no solver will honour anyway.

**Why CP-SAT is not broken by this.** It is not weakened at all -- it still
requires integers, and it still gets them. What changes is that a model whose
data is fractional now *legitimately does not fit it*, and the backend
registry already knows what to do with that: `needs` gains `fractional-data`,
CP-SAT does not provide it, and the run goes to a backend that does, with the
reason recorded. The selection policy built in Phase 2 starts doing real work
here rather than confirming a foregone conclusion.

**Three more columns move with them**, because a number that arrives fractional
must not be stored rounded. `run.objective` was `bigint`: a linear program's
optimum is fractional almost always, and rounding it would make the recorded
answer disagree with the solution beside it. `constraint_result`'s
`total_violation` and `penalty_paid` likewise -- a soft constraint in a
continuous model can be short by half a unit, and an integer column would
either round the breach or force the compiler to mint an integer violation
variable and overcharge for it.

**`snapshot_dataset()` trims the scale.** `numeric(15, 6)` writes 3 as
3.000000, and a frozen dataset carrying that would hash differently from the
identical one taken yesterday -- for no change in what it means. `trim_scale`
keeps an integer an integer and 2.5 as 2.5, so this migration changes no
existing dataset's hash at all. The function is copied from 0012 and amended
in two places; the downgrade restores 0012's byte for byte.

`run_overview` reads two of those columns, and Postgres refuses to alter a
column a view depends on, so the view is dropped and recreated. Its text is a
byte-for-byte copy of 0007's, and a test re-extracts 0007's own to compare --
the discipline 0011 and 0012 use for `snapshot_dataset()`, for the same
reason: a migration that quietly installs a view nobody wrote is worse than
one that fails.

Existing integer rows are unaffected: every integer is exactly representable
as a decimal, so this widens without converting.
"""

from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


# 0007's CREATE VIEW, copied byte for byte. A test re-extracts it from
# 0007's file and asserts equality, so the copy cannot drift.
_RUN_OVERVIEW_0007 = """
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


# 0012's CREATE OR REPLACE, copied byte for byte so `downgrade()` restores
# exactly what 0012 installed. A test re-extracts it and asserts equality.
_SNAPSHOT_DATASET_0012 = """
        CREATE OR REPLACE FUNCTION snapshot_dataset(p_model_version bigint) RETURNS bigint
        LANGUAGE plpgsql AS $$
        DECLARE
            v_problem bigint; v_domain bigint; v_ir jsonb;
            v_sets jsonb := '{}'; v_params jsonb := '{}'; v_labels jsonb := '{}';
            v_defaults jsonb := '{}';  -- 0009
            v_rels jsonb := '{}';      -- 0011
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
                -- Display names, kept *beside* the set rather than merged
                -- into it. Merging would let a domain attribute called
                -- `label` and an entity's own label shadow each other, and
                -- the compiler reads those rows: a display concern must not
                -- be able to change what is solved.
                SELECT coalesce(jsonb_object_agg(e.key, e.label), '{}')
                  INTO v_rows
                  FROM entity e JOIN entity_type t ON t.id = e.entity_type_id
                 WHERE t.domain_id = v_domain AND t.name = v_name AND e.active
                   AND e.label IS NOT NULL;
                v_labels := v_labels || jsonb_build_object(v_name, v_rows);
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
                v_defaults := v_defaults || jsonb_build_object(v_name, (  -- 0009
                    SELECT pd.default_value FROM parameter_def pd
                     WHERE pd.domain_id = v_domain AND pd.name = v_name));
            END LOOP;

            -- 0011: the domain's relationships, frozen with everything else.
            -- Every type of the domain, not only the ones the IR names: no
            -- term can reference an edge yet, so there is nothing to declare
            -- against. Step 2 (traversal terms) narrows this to declared
            -- types. Both endpoints must be active, matching how `sets`
            -- excludes inactive entities -- an edge naming a key that appears
            -- in no set would be unresolvable.
            FOR v_name IN SELECT rt.name FROM relationship_type rt
                           WHERE rt.domain_id = v_domain ORDER BY rt.name LOOP
                SELECT coalesce(jsonb_agg(row_json ORDER BY row_json::text), '[]')
                  INTO v_rows FROM (
                    SELECT jsonb_build_object('from', ef.key, 'to', et.key)
                           || CASE WHEN r.valid_from IS NULL THEN '{}'::jsonb
                                   ELSE jsonb_build_object('valid_from', r.valid_from) END
                           || CASE WHEN r.valid_to IS NULL THEN '{}'::jsonb
                                   ELSE jsonb_build_object('valid_to', r.valid_to) END
                           || CASE WHEN r.attrs = '{}'::jsonb THEN '{}'::jsonb
                                   ELSE jsonb_build_object('attrs', r.attrs) END AS row_json
                      FROM relationship r
                      JOIN relationship_type rt ON rt.id = r.relationship_type_id
                      JOIN entity ef ON ef.id = r.from_entity_id
                      JOIN entity et ON et.id = r.to_entity_id
                     WHERE rt.domain_id = v_domain AND rt.name = v_name
                       AND ef.active AND et.active) q;
                v_rels := v_rels || jsonb_build_object(v_name, v_rows);
            END LOOP;

            v_data := jsonb_build_object('labels', v_labels)
                      || jsonb_build_object('sets', v_sets, 'parameters', v_params,
                                         'parameter_defaults', v_defaults,  -- 0009
                                         'relationships', v_rels);          -- 0011
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


_SNAPSHOT_DATASET_0015 = """
        CREATE OR REPLACE FUNCTION snapshot_dataset(p_model_version bigint) RETURNS bigint
        LANGUAGE plpgsql AS $$
        DECLARE
            v_problem bigint; v_domain bigint; v_ir jsonb;
            v_sets jsonb := '{}'; v_params jsonb := '{}'; v_labels jsonb := '{}';
            v_defaults jsonb := '{}';  -- 0009
            v_rels jsonb := '{}';      -- 0011
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
                -- Display names, kept *beside* the set rather than merged
                -- into it. Merging would let a domain attribute called
                -- `label` and an entity's own label shadow each other, and
                -- the compiler reads those rows: a display concern must not
                -- be able to change what is solved.
                SELECT coalesce(jsonb_object_agg(e.key, e.label), '{}')
                  INTO v_rows
                  FROM entity e JOIN entity_type t ON t.id = e.entity_type_id
                 WHERE t.domain_id = v_domain AND t.name = v_name AND e.active
                   AND e.label IS NOT NULL;
                v_labels := v_labels || jsonb_build_object(v_name, v_rows);
            END LOOP;

            FOR v_name IN SELECT jsonb_object_keys(coalesce(v_ir -> 'parameters', '{}')) LOOP
                IF NOT EXISTS (SELECT 1 FROM parameter_def
                               WHERE domain_id = v_domain AND name = v_name) THEN
                    RAISE EXCEPTION 'IR parameter "%" has no parameter_def in this domain', v_name;
                END IF;
                SELECT coalesce(jsonb_agg(row_json ORDER BY row_json::text), '[]')
                  INTO v_rows FROM (
                    SELECT jsonb_object_agg(t.name, e.key)
                           -- trim_scale, or numeric(15, 6) writes 3 as
                           -- 3.000000 and every dataset a model already has
                           -- would hash differently for no change in its
                           -- meaning. An integer stays an integer; 2.5
                           -- stays 2.5.
                           || jsonb_build_object('value', trim_scale(pv.value))
                              AS row_json
                      FROM parameter_def pd
                      JOIN parameter_value pv ON pv.parameter_def_id = pd.id
                      CROSS JOIN LATERAL unnest(pv.entity_ids) AS u(eid)
                      JOIN entity e ON e.id = u.eid
                      JOIN entity_type t ON t.id = e.entity_type_id
                     WHERE pd.domain_id = v_domain AND pd.name = v_name
                     GROUP BY pv.parameter_def_id, pv.entity_ids, pv.value
                    HAVING bool_and(e.active)) q;
                v_params := v_params || jsonb_build_object(v_name, v_rows);
                v_defaults := v_defaults || jsonb_build_object(v_name, (  -- 0009
                    SELECT trim_scale(pd.default_value) FROM parameter_def pd
                     WHERE pd.domain_id = v_domain AND pd.name = v_name));
            END LOOP;

            -- 0011: the domain's relationships, frozen with everything else.
            -- Every type of the domain, not only the ones the IR names: no
            -- term can reference an edge yet, so there is nothing to declare
            -- against. Step 2 (traversal terms) narrows this to declared
            -- types. Both endpoints must be active, matching how `sets`
            -- excludes inactive entities -- an edge naming a key that appears
            -- in no set would be unresolvable.
            FOR v_name IN SELECT rt.name FROM relationship_type rt
                           WHERE rt.domain_id = v_domain ORDER BY rt.name LOOP
                SELECT coalesce(jsonb_agg(row_json ORDER BY row_json::text), '[]')
                  INTO v_rows FROM (
                    SELECT jsonb_build_object('from', ef.key, 'to', et.key)
                           || CASE WHEN r.valid_from IS NULL THEN '{}'::jsonb
                                   ELSE jsonb_build_object('valid_from', r.valid_from) END
                           || CASE WHEN r.valid_to IS NULL THEN '{}'::jsonb
                                   ELSE jsonb_build_object('valid_to', r.valid_to) END
                           || CASE WHEN r.attrs = '{}'::jsonb THEN '{}'::jsonb
                                   ELSE jsonb_build_object('attrs', r.attrs) END AS row_json
                      FROM relationship r
                      JOIN relationship_type rt ON rt.id = r.relationship_type_id
                      JOIN entity ef ON ef.id = r.from_entity_id
                      JOIN entity et ON et.id = r.to_entity_id
                     WHERE rt.domain_id = v_domain AND rt.name = v_name
                       AND ef.active AND et.active) q;
                v_rels := v_rels || jsonb_build_object(v_name, v_rows);
            END LOOP;

            v_data := jsonb_build_object('labels', v_labels)
                      || jsonb_build_object('sets', v_sets, 'parameters', v_params,
                                         'parameter_defaults', v_defaults,  -- 0009
                                         'relationships', v_rels);          -- 0011
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


def upgrade() -> None:
    op.execute("DROP VIEW run_overview")
    op.execute(
        """
        ALTER TABLE parameter_value
            ALTER COLUMN value TYPE numeric(15, 6);

        ALTER TABLE parameter_def
            ALTER COLUMN default_value TYPE numeric(15, 6),
            ALTER COLUMN default_value SET DEFAULT 0;

        ALTER TABLE run
            ALTER COLUMN objective TYPE numeric(15, 6);

        ALTER TABLE constraint_result
            ALTER COLUMN total_violation TYPE numeric(15, 6),
            ALTER COLUMN total_violation SET DEFAULT 0,
            ALTER COLUMN penalty_paid TYPE numeric(15, 6),
            ALTER COLUMN penalty_paid SET DEFAULT 0;
        """
    )
    op.execute(_RUN_OVERVIEW_0007)
    op.execute(_SNAPSHOT_DATASET_0015)


def downgrade() -> None:
    # Rounds rather than refuses: a downgrade of a database that has used
    # decimals cannot keep them, and failing here would leave no way back at
    # all. The rounding is the cost of having gone forwards.
    op.execute("DROP VIEW run_overview")
    op.execute(
        """
        ALTER TABLE parameter_value
            ALTER COLUMN value TYPE integer USING round(value)::integer;

        ALTER TABLE parameter_def
            ALTER COLUMN default_value TYPE integer USING round(default_value)::integer,
            ALTER COLUMN default_value SET DEFAULT 0;

        ALTER TABLE run
            ALTER COLUMN objective TYPE bigint USING round(objective)::bigint;

        ALTER TABLE constraint_result
            ALTER COLUMN total_violation TYPE integer USING round(total_violation)::integer,
            ALTER COLUMN total_violation SET DEFAULT 0,
            ALTER COLUMN penalty_paid TYPE bigint USING round(penalty_paid)::bigint,
            ALTER COLUMN penalty_paid SET DEFAULT 0;
        """
    )
    op.execute(_RUN_OVERVIEW_0007)
    op.execute(_SNAPSHOT_DATASET_0012)
