"""0025: a parameter may be indexed by the same type twice

``snapshot_dataset`` keyed each cell by index-*type* name
(``jsonb_object_agg(t.name, e.key)``), so ``distance[location, location]``
collapsed both coordinates onto one key. Migration 0008 refused the def
rather than emit a silent wrong snapshot. The cells themselves were always
positional (``parameter_value.entity_ids``).

This revision drops that CHECK and keys a *repeated* index by position
(``"0"``, ``"1"``, ...). A uniquely-typed parameter is unchanged, so
existing dataset hashes stay put. ``bigint_array_is_distinct`` stays: the
snapshot uses it to choose which shape to emit.

Revision ID: 0025
Revises: 0024
Create Date: 2026-09-21
"""
from alembic import op

revision = "0025"
down_revision = "0024"
branch_labels = None
depends_on = None


_SNAPSHOT_DATASET_0025 = """
        CREATE OR REPLACE FUNCTION snapshot_dataset(p_model_version bigint) RETURNS bigint
        LANGUAGE plpgsql AS $$
        DECLARE
            v_problem bigint; v_domain bigint; v_ir jsonb;
            v_sets jsonb := '{}'; v_params jsonb := '{}'; v_labels jsonb := '{}';
            v_defaults jsonb := '{}';
            v_rels jsonb := '{}';
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
                    SELECT CASE
                             WHEN bigint_array_is_distinct(pd.index_type_ids)
                             THEN jsonb_object_agg(t.name, e.key)
                             ELSE jsonb_object_agg((u.ord - 1)::text, e.key)
                           END
                           || jsonb_build_object('value', trim_scale(pv.value))
                              AS row_json
                      FROM parameter_def pd
                      JOIN parameter_value pv ON pv.parameter_def_id = pd.id
                      CROSS JOIN LATERAL unnest(pv.entity_ids) WITH ORDINALITY AS u(eid, ord)
                      JOIN entity e ON e.id = u.eid
                      JOIN entity_type t ON t.id = e.entity_type_id
                     WHERE pd.domain_id = v_domain AND pd.name = v_name
                     GROUP BY pv.parameter_def_id, pv.entity_ids, pv.value, pd.index_type_ids
                    HAVING bool_and(e.active)) q;
                v_params := v_params || jsonb_build_object(v_name, v_rows);
                v_defaults := v_defaults || jsonb_build_object(v_name, (
                    SELECT trim_scale(pd.default_value) FROM parameter_def pd
                     WHERE pd.domain_id = v_domain AND pd.name = v_name));
            END LOOP;

            FOR v_name IN SELECT jsonb_array_elements_text(
                                     coalesce(v_ir -> 'relationships', '[]'::jsonb)) LOOP
                IF NOT EXISTS (SELECT 1 FROM relationship_type
                               WHERE domain_id = v_domain AND name = v_name) THEN
                    RAISE EXCEPTION 'IR relationship "%" has no relationship_type in this domain',
                          v_name;
                END IF;
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
                                         'parameter_defaults', v_defaults,
                                         'relationships', v_rels);
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
    op.execute("ALTER TABLE parameter_def DROP CONSTRAINT IF EXISTS parameter_def_index_type_ids_distinct;")
    op.execute(_SNAPSHOT_DATASET_0025)


def downgrade() -> None:
    # The 0025 snapshot is a no-op for uniquely-typed parameters. Restoring
    # the CHECK is enough; it fails if a self-indexed row exists, which is
    # the honest inverse of this revision.
    op.execute(
        """
        ALTER TABLE parameter_def
            ADD CONSTRAINT parameter_def_index_type_ids_distinct
            CHECK (bigint_array_is_distinct(index_type_ids));
        """
    )
