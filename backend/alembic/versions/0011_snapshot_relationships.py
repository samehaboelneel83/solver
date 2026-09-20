"""snapshot_dataset: freeze the domain's relationships too

Revision ID: 0011
Revises: 0010
Create Date: 2026-09-20

The frozen dataset a run reads carried entities and parameters and **no
relationships at all**, so no term could refer to an edge and traversal was
not expressible -- recorded as *derived, not chosen* in the IR contract (§9)
and argued out in `docs/plans/2026-09-20-traversal-decision.md`.

This is **step 1 of two**: the edges are emitted and nothing can reference
them yet. That is deliberate. A term algebra without traversal is not a
smaller version of one with it, so the editor about to be built should be
designed against a document that already carries the data; step 2 adds the
term forms and narrows this emission to the types an IR declares.

`entity_descendants(bigint, bigint)` has existed since 0006, tested and used
by nothing, because the snapshot it was built to feed had no edges.

Shape, per relationship type of the domain:

    "relationships": {
      "reports_to": [{"from": "head_office", "to": "north_region"}, ...],
      "works_in":   [{"from": "ahmed", "to": "north_depot",
                      "valid_from": "2026-01-01"}]
    }

`valid_from`/`valid_to` travel when set, and `attrs` when non-empty: an edge
frozen without its validity dates would quietly commit the platform to
ignoring them, which is a modelling decision nobody took. Keys are entity
`key`s, the vocabulary `sets` already uses.

Both endpoints must be `active`. `sets` excludes inactive entities, so an
edge naming an inactive one would reference a key present in no set.

Every `dataset` row's `data_hash` changes shape-wise from here. That is free
today -- `dataset` holds zero rows -- and gets more expensive with every run,
which is why this lands before the editor rather than after.
"""

from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


# 0009's CREATE OR REPLACE statement, copied byte for byte so `downgrade()`
# restores exactly what 0009 installed. A test re-extracts it from 0009's
# file and asserts equality, so the copy cannot drift.
_SNAPSHOT_DATASET_0009 = """
        CREATE OR REPLACE FUNCTION snapshot_dataset(p_model_version bigint) RETURNS bigint
        LANGUAGE plpgsql AS $$
        DECLARE
            v_problem bigint; v_domain bigint; v_ir jsonb;
            v_sets jsonb := '{}'; v_params jsonb := '{}';
            v_defaults jsonb := '{}';  -- 0009
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

            v_data := jsonb_build_object('sets', v_sets, 'parameters', v_params,
                                         'parameter_defaults', v_defaults);  -- 0009
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

# 0011: as 0009, plus the `relationships` key.
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


def upgrade() -> None:
    op.execute(_SNAPSHOT_DATASET_0011)


def downgrade() -> None:
    op.execute(_SNAPSHOT_DATASET_0009)
