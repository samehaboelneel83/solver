"""snapshot defaults, domain integrity rules and type colours

Three things, two of them direct user decisions.

Part 1 -- parameter defaults in the dataset snapshot (Ruling 28)
----------------------------------------------------------------
`parameter_value` is stored sparsely: a cell equal to its parameter's
`default_value` is not stored (Task 8). `snapshot_dataset()` (0007) emitted
only stored rows, so the frozen dataset could not say what an absent cell
meant. The user chose to keep sparse storage and have the snapshot carry
the defaults beside the unchanged `parameters` object:

    {"sets": {...}, "parameters": {...},
     "parameter_defaults": {"<name>": <int>, ...}}

one entry per parameter the IR's `parameters` object references -- exactly
the set the `parameters` loop already resolves, scoped to the problem's
domain the same way. The solver's rule is "look the cell up; if absent,
use the default". `sets` and `parameters` are byte-for-byte unchanged.
Because the defaults are inside `data`, two snapshots differing only in a
default hash differently, which is the point; it also means a snapshot
taken after this migration never dedups onto one taken before it.

`downgrade()` drops the function and re-runs 0007's CREATE FUNCTION
statement verbatim (`_SNAPSHOT_DATASET_0007` below is a byte copy of it,
and `test_v1_integrity_rules.py` asserts that it still is).

Part 2 -- the eight domain integrity rules (Ruling 32)
------------------------------------------------------
Task 15's seed writes straight to the database, so every rule lives here
rather than (only) in a router. A CHECK or a constraint is used wherever
one can express the rule; a trigger only where the rule is about an
array's elements or another table.

1. CHECK `attribute_def_enum_values_not_empty` -- an enum with no values
   could never be satisfied. A NULL member is refused too: it makes
   `entity_validate`'s `v = ANY (enum_values)` NULL rather than false for
   every non-member, and `IF NOT ok` then accepts *any* string.
2. CHECK `entity_key_not_blank` -- `key ~ '[^[:space:]]'`: not empty and
   not whitespace-only. Keys surface as `"id"` in every snapshot row.
3. Composite FKs `relationship_type_{from,to}_type_same_domain_fkey`,
   `(from_type_id, domain_id)` / `(to_type_id, domain_id)` ->
   `entity_type (id, domain_id)`, backed by `UNIQUE (id, domain_id)` on
   `entity_type`. A constraint, not a trigger: it also refuses moving a
   referenced entity type to another domain (the NO ACTION update side),
   and it is safe under concurrency, which a trigger is not. ON DELETE
   CASCADE, matching the 0006 single-column FKs it sits beside.
4. Trigger `parameter_def_validate`, kind **`index_type_domain`** -- every
   id in `index_type_ids` exists and belongs to the parameter's own
   `domain_id` (a NULL element is refused too). Array elements cannot
   carry a foreign key. The referenced types are locked FOR KEY SHARE, so
   a concurrent delete or move of one of them waits for this transaction
   and then meets rule 5.
5. Trigger `entity_type_guard`, kind **`index_type_in_use`** -- an entity
   type named by some `parameter_def.index_type_ids` cannot be deleted
   (refused, not cascaded) or moved to another domain. The one exception
   is a cascade from its own `domain`: that statement deletes the
   parameters too, so nothing is left dangling, and refusing it would make
   every domain with a parameter undeletable.
6. Trigger `parameter_def_validate`, kind **`parameter_reindex`** --
   `index_type_ids` cannot change while the parameter has stored
   `parameter_value` rows (they were validated against the old index, and
   `parameter_value_validate` never revisits them).
7. `UNIQUE (id, problem_id)` on `model_version` plus the composite FK
   `scenario_version_same_problem_fkey` `(model_version_id, problem_id)
   REFERENCES model_version (id, problem_id)` -- Task 9's mutant D2.
8. CHECK `attribute_def_default_value_matches_type`, via the IMMUTABLE
   `attr_value_matches_type(attr_type, text[], jsonb)`: a non-NULL default
   must be a value `entity_validate` would accept for that `data_type`
   (the same judgement, restated as a function; a test runs both over the
   same candidates). jsonb `'null'` is refused as a default: it is not a
   value of any type, and Ruling 18 showed it only ever arrives by mistake.
   Because it is a CHECK it is re-judged when `data_type` or
   `enum_values` change, so a default cannot be orphaned that way either.

Both triggers follow amendment (a) from 0006: ERRCODE '23514' and a JSON
DETAIL carrying `kind` and `field` (here always `'index_type_ids'`), so
`translate_db_error` answers with a 422 naming the field. The CHECK- and
FK-backed rules arrive as `translate_db_error`'s 409 with a string detail,
as every plain constraint does (Ruling 16).

Part 3 -- `colour` on entity_type and relationship_type (user request (B))
---------------------------------------------------------------------------
`colour text NULL` with `CHECK (colour ~ '^#[0-9a-f]{6}$')`: lowercase
six-digit hex only, so every consumer can rely on one format. NULL means
"not chosen"; the UI assigns a deterministic fallback, so there is no
default. (Postgres's `$` does not match before a trailing newline, unlike
Python's `re`, so `'#a1b2c3\\n'` is refused.)

Upgrading fails if existing rows already break a rule. None can in a
database built by this chain and written only through the routers, except
through the gaps this migration closes (raw SQL); the test and e2e
databases are rebuilt from scratch.

`downgrade()` removes everything above. It is lossy for Part 3: stored
colours are dropped with their columns.

Revision ID: 0009
Revises: 0008
Create Date: 2026-09-19

"""
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


# 0007's CREATE FUNCTION statement for snapshot_dataset(), copied byte for
# byte (it is not retyped). Used only by downgrade(), which drops the 0009
# version and runs this. Do not edit it: it is the 0007 contract.
_SNAPSHOT_DATASET_0007 = """
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


# Part 1: 0007's body plus `v_defaults`. The three added lines are marked.
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


def upgrade() -> None:
    # -- Part 1: snapshot defaults ----------------------------------------
    op.execute(_SNAPSHOT_DATASET_0009)

    # -- Part 2: rules 1, 2 and 8 -- single-row CHECKs ---------------------
    op.execute(
        """
        ALTER TABLE attribute_def
            ADD CONSTRAINT attribute_def_enum_values_not_empty
            CHECK (enum_values IS NULL
                   OR (cardinality(enum_values) >= 1
                       AND array_position(enum_values, NULL) IS NULL));

        ALTER TABLE entity
            ADD CONSTRAINT entity_key_not_blank
            CHECK (key ~ '[^[:space:]]');

        -- entity_validate's judgement of one attribute value, as a function
        -- a CHECK may call. The integer branch is a nested CASE rather than
        -- an AND so the ::numeric cast can never be reached for a
        -- non-number, whatever order the planner evaluates in.
        CREATE FUNCTION attr_value_matches_type(p_type attr_type, p_enum_values text[], p_value jsonb)
        RETURNS boolean LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
            SELECT coalesce(CASE p_type::text
                WHEN 'integer' THEN CASE WHEN jsonb_typeof(p_value) = 'number'
                                         THEN (p_value #>> '{}')::numeric % 1 = 0
                                         ELSE false END
                WHEN 'number'  THEN jsonb_typeof(p_value) = 'number'
                WHEN 'boolean' THEN jsonb_typeof(p_value) = 'boolean'
                WHEN 'enum'    THEN jsonb_typeof(p_value) = 'string'
                                    AND (p_value #>> '{}') = ANY (p_enum_values)
                ELSE                jsonb_typeof(p_value) = 'string'
            END, false)
        $$;

        ALTER TABLE attribute_def
            ADD CONSTRAINT attribute_def_default_value_matches_type
            CHECK (default_value IS NULL
                   OR attr_value_matches_type(data_type, enum_values, default_value));
        """
    )

    # -- Part 2: rules 3 and 7 -- composite foreign keys -------------------
    op.execute(
        """
        ALTER TABLE entity_type
            ADD CONSTRAINT entity_type_id_domain_id_key UNIQUE (id, domain_id);

        ALTER TABLE relationship_type
            ADD CONSTRAINT relationship_type_from_type_same_domain_fkey
            FOREIGN KEY (from_type_id, domain_id)
            REFERENCES entity_type (id, domain_id) ON DELETE CASCADE,
            ADD CONSTRAINT relationship_type_to_type_same_domain_fkey
            FOREIGN KEY (to_type_id, domain_id)
            REFERENCES entity_type (id, domain_id) ON DELETE CASCADE;

        ALTER TABLE model_version
            ADD CONSTRAINT model_version_id_problem_id_key UNIQUE (id, problem_id);

        ALTER TABLE scenario
            ADD CONSTRAINT scenario_version_same_problem_fkey
            FOREIGN KEY (model_version_id, problem_id)
            REFERENCES model_version (id, problem_id);
        """
    )

    # -- Part 2: rules 4 and 6 -- parameter_def_validate -------------------
    op.execute(
        """
        CREATE FUNCTION parameter_def_validate() RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE v_type bigint; v_stored bigint;
        BEGIN
            -- rule 6: no re-index while cells are stored
            IF TG_OP = 'UPDATE' AND NEW.index_type_ids IS DISTINCT FROM OLD.index_type_ids THEN
                SELECT count(*) INTO v_stored FROM parameter_value WHERE parameter_def_id = NEW.id;
                IF v_stored > 0 THEN
                    RAISE EXCEPTION
                        'parameter "%": index types cannot change while % value(s) are stored',
                        NEW.name, v_stored
                        USING ERRCODE = '23514',
                              DETAIL  = jsonb_build_object(
                                  'kind',   'parameter_reindex',
                                  'field',  'index_type_ids',
                                  'record', NEW.name,
                                  'stored', v_stored)::text;
                END IF;
            END IF;

            -- rule 4: every index type exists, in this parameter's domain.
            -- Lock them first, so a concurrent delete or move of one waits
            -- for this transaction and then meets entity_type_guard.
            PERFORM 1 FROM entity_type WHERE id = ANY (NEW.index_type_ids) FOR KEY SHARE;
            SELECT u.id INTO v_type
              FROM unnest(NEW.index_type_ids) WITH ORDINALITY AS u(id, ord)
             WHERE NOT EXISTS (SELECT 1 FROM entity_type t
                                WHERE t.id = u.id AND t.domain_id = NEW.domain_id)
             ORDER BY u.ord
             LIMIT 1;
            IF FOUND THEN
                RAISE EXCEPTION
                    'parameter "%": index type % is not an entity type of this domain',
                    NEW.name, coalesce(v_type::text, 'NULL')
                    USING ERRCODE = '23514',
                          DETAIL  = jsonb_build_object(
                              'kind',          'index_type_domain',
                              'field',         'index_type_ids',
                              'record',        NEW.name,
                              'index_type_id', v_type,
                              'domain_id',     NEW.domain_id)::text;
            END IF;
            RETURN NEW;
        END $$;

        CREATE TRIGGER parameter_def_validate
            BEFORE INSERT OR UPDATE OF index_type_ids, domain_id ON parameter_def
            FOR EACH ROW EXECUTE FUNCTION parameter_def_validate();
        """
    )

    # -- Part 2: rule 5 -- entity_type_guard -------------------------------
    op.execute(
        """
        CREATE FUNCTION entity_type_guard() RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE v_params text[];
        BEGIN
            IF TG_OP = 'UPDATE' AND NEW.domain_id IS NOT DISTINCT FROM OLD.domain_id THEN
                RETURN NEW;
            END IF;
            -- A cascade from `domain`: the domain row is already gone, and
            -- the same statement deletes its parameters (rule 4 keeps every
            -- referencing parameter in this domain), so nothing dangles.
            IF TG_OP = 'DELETE' AND NOT EXISTS (SELECT 1 FROM domain WHERE id = OLD.domain_id) THEN
                RETURN OLD;
            END IF;
            SELECT array_agg(pd.name ORDER BY pd.name) INTO v_params
              FROM parameter_def pd
             WHERE OLD.id = ANY (pd.index_type_ids);
            IF v_params IS NOT NULL THEN
                RAISE EXCEPTION
                    'entity type "%" is an index type of parameter %; delete or re-index % first',
                    OLD.name, array_to_string(v_params, ', '),
                    CASE WHEN cardinality(v_params) = 1 THEN 'it' ELSE 'them' END
                    USING ERRCODE = '23514',
                          DETAIL  = jsonb_build_object(
                              'kind',       'index_type_in_use',
                              'field',      'index_type_ids',
                              'record',     OLD.name,
                              'parameters', to_jsonb(v_params))::text;
            END IF;
            IF TG_OP = 'DELETE' THEN
                RETURN OLD;
            END IF;
            RETURN NEW;
        END $$;

        CREATE TRIGGER entity_type_guard
            BEFORE DELETE OR UPDATE OF domain_id ON entity_type
            FOR EACH ROW EXECUTE FUNCTION entity_type_guard();
        """
    )

    # -- Part 3: colour ----------------------------------------------------
    op.execute(
        """
        ALTER TABLE entity_type
            ADD COLUMN colour text,
            ADD CONSTRAINT entity_type_colour_hex CHECK (colour ~ '^#[0-9a-f]{6}$');

        ALTER TABLE relationship_type
            ADD COLUMN colour text,
            ADD CONSTRAINT relationship_type_colour_hex CHECK (colour ~ '^#[0-9a-f]{6}$');
        """
    )


def downgrade() -> None:
    # Part 3 (lossy: stored colours go with their columns; the CHECKs go
    # with them too).
    op.execute(
        """
        ALTER TABLE relationship_type DROP COLUMN IF EXISTS colour;
        ALTER TABLE entity_type DROP COLUMN IF EXISTS colour;
        """
    )

    # Part 2
    op.execute(
        """
        DROP TRIGGER IF EXISTS entity_type_guard ON entity_type;
        DROP FUNCTION IF EXISTS entity_type_guard();
        DROP TRIGGER IF EXISTS parameter_def_validate ON parameter_def;
        DROP FUNCTION IF EXISTS parameter_def_validate();

        ALTER TABLE scenario DROP CONSTRAINT IF EXISTS scenario_version_same_problem_fkey;
        ALTER TABLE model_version DROP CONSTRAINT IF EXISTS model_version_id_problem_id_key;
        ALTER TABLE relationship_type
            DROP CONSTRAINT IF EXISTS relationship_type_to_type_same_domain_fkey,
            DROP CONSTRAINT IF EXISTS relationship_type_from_type_same_domain_fkey;
        ALTER TABLE entity_type DROP CONSTRAINT IF EXISTS entity_type_id_domain_id_key;

        ALTER TABLE attribute_def DROP CONSTRAINT IF EXISTS attribute_def_default_value_matches_type;
        DROP FUNCTION IF EXISTS attr_value_matches_type(attr_type, text[], jsonb);
        ALTER TABLE entity DROP CONSTRAINT IF EXISTS entity_key_not_blank;
        ALTER TABLE attribute_def DROP CONSTRAINT IF EXISTS attribute_def_enum_values_not_empty;
        """
    )

    # Part 1: back to 0007's snapshot_dataset(), verbatim.
    op.execute("DROP FUNCTION IF EXISTS snapshot_dataset(bigint)")
    op.execute(_SNAPSHOT_DATASET_0007)
