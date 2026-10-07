"""0112: parameter values written in bulk are checked once per statement, not once per value.

The general-purpose evaluation (October 2026) found a 60 x 400 transportation model spending ~19 s of its build
writing 24,000 cost cells, against a 0.5 s solve: about 0.85 ms a value. Disabling the triggers one at a time put
~85% of it in `parameter_value_validate`, which, for every row, read the parameter twice, joined the row's records
and asked each index position's type lineage.

An INSERT is now checked by one statement-level trigger over the inserted rows (a transition table): the same
tests, set-based, comparing a record's own kind directly and asking the lineage only for an inherited kind. The
first offending row raises the same error, with the same code and detail, as before. An UPDATE keeps the row
trigger (a cell edited in place is one row).
"""

from alembic import op

revision = "0112"
down_revision = "0111"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(r"""
    CREATE OR REPLACE FUNCTION parameter_value_validate_inserted() RETURNS trigger LANGUAGE plpgsql AS $function$
    DECLARE bad record; pair record;
    BEGIN
        -- A row with the wrong number of indices.
        SELECT n.entity_ids, d.index_type_ids AS want INTO bad
          FROM inserted n JOIN parameter_def d ON d.id = n.parameter_def_id
         WHERE cardinality(n.entity_ids) IS DISTINCT FROM cardinality(d.index_type_ids)
         LIMIT 1;
        IF NOT FOUND THEN
            -- Each (record, wanted kind) pair once: 24,000 cells over 60 x 400 records are 460 pairs, so the
            -- check costs what the records do, not what the cells do -- and is quick whatever the planner knows
            -- of records written a moment ago in this same build.
            WITH pairs AS MATERIALIZED (
                SELECT DISTINCT u.id, u.want_type
                  FROM inserted n JOIN parameter_def d ON d.id = n.parameter_def_id
                 CROSS JOIN LATERAL unnest(n.entity_ids, d.index_type_ids) AS u(id, want_type))
            SELECT p.id, p.want_type INTO pair
              FROM pairs p LEFT JOIN entity e ON e.id = p.id
             WHERE e.id IS NULL
                OR NOT (e.entity_type_id = p.want_type OR entity_type_is_a(e.entity_type_id, p.want_type))
             LIMIT 1;
            IF FOUND THEN
                SELECT n.entity_ids, d.index_type_ids AS want INTO bad
                  FROM inserted n JOIN parameter_def d ON d.id = n.parameter_def_id
                 WHERE EXISTS (SELECT 1 FROM unnest(n.entity_ids, d.index_type_ids) AS u(id, want_type)
                                WHERE u.id = pair.id AND u.want_type = pair.want_type)
                 LIMIT 1;
            END IF;
        END IF;
        IF FOUND THEN
            RAISE EXCEPTION
                'parameter_value: index % does not match parameter index types', bad.entity_ids
                USING ERRCODE = '23514',
                      DETAIL  = jsonb_build_object(
                          'kind',     'parameter_index',
                          'field',    'entity_ids',
                          'record',   bad.entity_ids,
                          'expected', bad.want)::text;
        END IF;
        -- Migration 0068: a parameter's value is a number, or -- when it declares a value type -- an entity of
        -- that type (or one inheriting from it).
        SELECT n.entity_ids INTO bad
          FROM inserted n JOIN parameter_def d ON d.id = n.parameter_def_id
         WHERE d.value_type_id IS NULL AND (n.value IS NULL OR n.value_entity_id IS NOT NULL)
         LIMIT 1;
        IF FOUND THEN
            RAISE EXCEPTION 'parameter_value: this parameter holds a number'
                USING ERRCODE = '23514',
                      DETAIL  = jsonb_build_object('kind', 'parameter_value_kind', 'field', 'value',
                                                   'record', bad.entity_ids)::text;
        END IF;
        SELECT n.entity_ids INTO bad
          FROM inserted n JOIN parameter_def d ON d.id = n.parameter_def_id
          LEFT JOIN entity v ON v.id = n.value_entity_id
         WHERE d.value_type_id IS NOT NULL
           AND (n.value IS NOT NULL OR n.value_entity_id IS NULL OR v.id IS NULL
                OR NOT (v.entity_type_id = d.value_type_id OR entity_type_is_a(v.entity_type_id, d.value_type_id)))
         LIMIT 1;
        IF FOUND THEN
            RAISE EXCEPTION 'parameter_value: this parameter holds an entity of its value type'
                USING ERRCODE = '23514',
                      DETAIL  = jsonb_build_object('kind', 'parameter_value_kind', 'field', 'value_entity_id',
                                                   'record', bad.entity_ids)::text;
        END IF;
        RETURN NULL;
    END $function$;

    DROP TRIGGER IF EXISTS parameter_value_validate ON parameter_value;
    CREATE TRIGGER parameter_value_validate BEFORE UPDATE ON parameter_value
        FOR EACH ROW EXECUTE FUNCTION parameter_value_validate();
    CREATE TRIGGER parameter_value_validate_inserted AFTER INSERT ON parameter_value
        REFERENCING NEW TABLE AS inserted
        FOR EACH STATEMENT EXECUTE FUNCTION parameter_value_validate_inserted();
    """)


def downgrade() -> None:
    op.execute("""
    DROP TRIGGER IF EXISTS parameter_value_validate_inserted ON parameter_value;
    DROP FUNCTION IF EXISTS parameter_value_validate_inserted();
    DROP TRIGGER IF EXISTS parameter_value_validate ON parameter_value;
    CREATE TRIGGER parameter_value_validate BEFORE INSERT OR UPDATE ON parameter_value
        FOR EACH ROW EXECUTE FUNCTION parameter_value_validate();
    """)
