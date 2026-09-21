"""0016: snapshot_dataset freezes the relationships the IR declares, and only those

Revision ID: 0016
Revises: 0015
Create Date: 2026-09-21

**Step 2 of two**, and 0011 named it in advance: *"the edges are emitted and
nothing can reference them yet. That is deliberate. ... step 2 adds the term
forms and narrows this emission to the types an IR declares."* The term forms
land in the same change as this migration; this is the data half of it.

0011 froze **every** relationship type of the domain, because no term could
name one and so there was nothing to declare against. That reason has gone: a
`via` binding now walks a named type, and the contract makes a model declare
which ones it walks -- `relationships`, optional, exactly parallel to `sets`.
Freezing a type no term can name would put data in an immutable hashed
document for no reason, and worse, would make the dataset depend on the
domain's shape rather than on the model's, so adding an unrelated edge type to
a domain would change the hash of a snapshot nothing about the model had
changed.

So the loop mirrors `sets` in all three respects: it reads the IR, it refuses
a name the domain does not have, and it emits nothing for a model that
declares nothing. The refusal is `RAISE EXCEPTION` for the same reason
`sets`'s is -- the backstop for a domain that loses a relationship type
*after* a version was frozen. At submit time the router gets there first, and
`relationship_not_in_domain` is a 422 naming the element.

**This changes the hash of any dataset taken before it**, for models that do
not declare relationships: they used to carry every type of the domain and now
carry none. That is the point, and it is why this lands now rather than later
-- `dataset` holds three rows today, all of the seeded demo, and each is
immutable and still readable. The runs pointing at them are unaffected; the
next snapshot of the same version simply produces a new row. Every day this
waits, the number of rows that argument has to cover goes up.

`_SNAPSHOT_DATASET_0015` below is 0015's statement copied byte for byte, so
`downgrade()` restores exactly what 0015 installed -- the discipline 0011,
0012 and 0015 each use, with a test that re-extracts the original and compares
rather than trusting the copy.
"""

from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


# 0015's CREATE OR REPLACE, copied byte for byte. A test re-extracts it from
# 0015's file and asserts equality, so the copy cannot drift.
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


# 0016: as 0015, with the relationship loop reading the IR instead of the
# domain.
_SNAPSHOT_DATASET_0016 = """
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

            -- 0016: the relationships the IR declares, and only those. 0011
            -- froze every type of the domain because no term could name one;
            -- a `via` binding names one now, so the model says which it
            -- walks and the dataset stops depending on the domain's shape.
            -- Mirrors `sets` throughout, refusal included. Both endpoints
            -- must be active, matching how `sets` excludes inactive
            -- entities -- an edge naming a key that appears in no set would
            -- be unresolvable.
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
    op.execute(_SNAPSHOT_DATASET_0016)


def downgrade() -> None:
    op.execute(_SNAPSHOT_DATASET_0015)
