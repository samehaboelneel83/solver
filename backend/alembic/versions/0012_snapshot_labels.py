"""0012: freeze display names with the data.

An answer in variable indices is not an answer a planner can read. `ahmed` is
a key -- a spelling the platform chose -- and `Ahmed Salah` is the person. The
roadmap's Phase 4 asks for the solution in the domain's own words, and this is
the half of it that has to happen at snapshot time: a run answers the question
as it was asked, so it must read back in the names that were current when it
was asked. Resolving names live would show today's spelling over a frozen
answer.

**Beside the set rows, not merged into them.** `sets` feeds the compiler. If
labels were merged, a domain attribute called `label` and an entity's own
label would shadow each other, and a display concern could change what is
solved. `labels` is its own map, set name to key to label, and nothing but the
reader looks at it.

Entities without a label are absent rather than null: the reader falls back to
the key, and a null would have to be checked for anyway.

Like 0011, this changes the shape every `dataset.data_hash` is taken over.
Existing datasets keep their old shape and simply have no labels, so runs made
before this read back in keys -- which is what they were shown as when they
were made.
"""

from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


# 0011's CREATE OR REPLACE statement, copied byte for byte so `downgrade()`
# restores exactly what 0011 installed. A test re-extracts it from 0011's file
# and asserts equality, so the copy cannot drift.
_SNAPSHOT_DATASET_0011 = """
        CREATE OR REPLACE FUNCTION snapshot_dataset(p_model_version bigint) RETURNS bigint
        LANGUAGE plpgsql AS $$
        DECLARE
            v_problem bigint; v_domain bigint; v_ir jsonb;
            v_sets jsonb := '{}'; v_params jsonb := '{}';
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

            v_data := jsonb_build_object('sets', v_sets, 'parameters', v_params,
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


def upgrade() -> None:
    op.execute(_SNAPSHOT_DATASET_0012)


def downgrade() -> None:
    op.execute(_SNAPSHOT_DATASET_0011)
