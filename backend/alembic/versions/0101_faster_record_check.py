"""0101: the record check reads a kind's fields once per record, not once per field.

`entity_validate` worked out the kind's lineage (the kind and those it inherits from) again for
every field a record names and again to list its fields. With ten fields, 2,880 rows spent about
ten seconds in this trigger alone (benchmark, October 2026: an upload that looked as if it wrote
nothing). The checks and their messages are unchanged; the lineage is read once, and the fields a
record names are checked in one query.
"""
from alembic import op

revision = "0101"
down_revision = "0100"
branch_labels = None
depends_on = None

NEW = r"""
CREATE OR REPLACE FUNCTION entity_validate() RETURNS trigger LANGUAGE plpgsql AS $$
    -- Migration 0101 (benchmark, October 2026): the same checks, with the type's lineage and its
    -- fields read once per row rather than once per field -- 2,880 rows took seconds in this trigger.
    DECLARE d attribute_def; v jsonb; k text; lineage bigint[];
    BEGIN
        IF (SELECT is_abstract FROM entity_type WHERE id = NEW.entity_type_id) THEN
            RAISE EXCEPTION 'entity %: its type is abstract and holds no entities of its own; use one of the types that inherit from it', NEW.key
                USING ERRCODE = '23514',
                      DETAIL  = jsonb_build_object('kind', 'abstract_type', 'field', 'entity_type_id', 'record', NEW.key)::text;
        END IF;
        lineage := entity_type_lineage(NEW.entity_type_id);
        SELECT key INTO k FROM jsonb_object_keys(NEW.attrs) AS key
         WHERE NOT EXISTS (SELECT 1 FROM attribute_def a WHERE a.entity_type_id = ANY (lineage) AND a.name = key)
         LIMIT 1;
        IF k IS NOT NULL THEN
            RAISE EXCEPTION 'entity %: unknown attribute "%"', NEW.key, k
                USING ERRCODE = '23514',
                      DETAIL  = jsonb_build_object('kind', 'unknown_attribute', 'field', k, 'record', NEW.key)::text;
        END IF;
        FOR d IN SELECT * FROM attribute_def WHERE entity_type_id = ANY (lineage) LOOP
            v := NEW.attrs -> d.name;
            IF v IS NULL AND d.default_value IS NOT NULL THEN
                NEW.attrs := NEW.attrs || jsonb_build_object(d.name, d.default_value);
                v := d.default_value;
            END IF;
            IF v IS NULL OR v = 'null' THEN
                IF d.required THEN
                    RAISE EXCEPTION 'entity %: attribute "%" is required', NEW.key, d.name
                        USING ERRCODE = '23514',
                              DETAIL  = jsonb_build_object('kind', 'required_attribute', 'field', d.name, 'record', NEW.key)::text;
                END IF;
                CONTINUE;
            END IF;
            IF NOT attr_value_matches_type(d.data_type, d.enum_values, v) THEN
                RAISE EXCEPTION 'entity %: attribute "%" must be %', NEW.key, d.name, d.data_type
                    USING ERRCODE = '23514',
                          DETAIL  = jsonb_build_object('kind', 'attribute_type', 'field', d.name,
                                                       'record', NEW.key, 'expected', d.data_type::text)::text;
            END IF;
            IF d.data_type::text = 'reference' AND NOT EXISTS (
                SELECT 1 FROM entity e JOIN relationship_type rt ON rt.id = d.references_id
                 WHERE e.key = v #>> '{}' AND entity_type_is_a(e.entity_type_id, rt.to_type_id)) THEN
                RAISE EXCEPTION 'entity %: attribute "%" names "%", which is not an entity it can refer to', NEW.key, d.name, v #>> '{}'
                    USING ERRCODE = '23514',
                          DETAIL  = jsonb_build_object('kind', 'reference_unknown', 'field', d.name,
                                                       'record', NEW.key)::text;
            END IF;
        END LOOP;
        RETURN NEW;
    END $$;
"""

OLD = r"""
CREATE OR REPLACE FUNCTION public.entity_validate()
 RETURNS trigger
 LANGUAGE plpgsql
AS $function$
    DECLARE d attribute_def; v jsonb; k text;
    BEGIN
        IF (SELECT is_abstract FROM entity_type WHERE id = NEW.entity_type_id) THEN
            RAISE EXCEPTION 'entity %: its type is abstract and holds no entities of its own; use one of the types that inherit from it', NEW.key
                USING ERRCODE = '23514',
                      DETAIL  = jsonb_build_object('kind', 'abstract_type', 'field', 'entity_type_id', 'record', NEW.key)::text;
        END IF;
        FOR k IN SELECT jsonb_object_keys(NEW.attrs) LOOP
            IF NOT EXISTS (SELECT 1 FROM attribute_def
                           WHERE entity_type_id = ANY (entity_type_lineage(NEW.entity_type_id)) AND name = k) THEN
                RAISE EXCEPTION 'entity %: unknown attribute "%"', NEW.key, k
                    USING ERRCODE = '23514',
                          DETAIL  = jsonb_build_object('kind', 'unknown_attribute', 'field', k, 'record', NEW.key)::text;
            END IF;
        END LOOP;
        FOR d IN SELECT * FROM attribute_def WHERE entity_type_id = ANY (entity_type_lineage(NEW.entity_type_id)) LOOP
            v := NEW.attrs -> d.name;
            IF v IS NULL AND d.default_value IS NOT NULL THEN
                NEW.attrs := NEW.attrs || jsonb_build_object(d.name, d.default_value);
                v := d.default_value;
            END IF;
            IF v IS NULL OR v = 'null' THEN
                IF d.required THEN
                    RAISE EXCEPTION 'entity %: attribute "%" is required', NEW.key, d.name
                        USING ERRCODE = '23514',
                              DETAIL  = jsonb_build_object('kind', 'required_attribute', 'field', d.name, 'record', NEW.key)::text;
                END IF;
                CONTINUE;
            END IF;
            IF NOT attr_value_matches_type(d.data_type, d.enum_values, v) THEN
                RAISE EXCEPTION 'entity %: attribute "%" must be %', NEW.key, d.name, d.data_type
                    USING ERRCODE = '23514',
                          DETAIL  = jsonb_build_object('kind', 'attribute_type', 'field', d.name,
                                                       'record', NEW.key, 'expected', d.data_type::text)::text;
            END IF;
            -- Migration 0067 (queue R20a): a reference names an entity of its target type (or one
            -- inheriting from it) by key.
            IF d.data_type::text = 'reference' AND NOT EXISTS (
                SELECT 1 FROM entity e JOIN relationship_type rt ON rt.id = d.references_id
                 WHERE e.key = v #>> '{}' AND entity_type_is_a(e.entity_type_id, rt.to_type_id)) THEN
                RAISE EXCEPTION 'entity %: attribute "%" names "%", which is not an entity it can refer to', NEW.key, d.name, v #>> '{}'
                    USING ERRCODE = '23514',
                          DETAIL  = jsonb_build_object('kind', 'reference_unknown', 'field', d.name,
                                                       'record', NEW.key)::text;
            END IF;
        END LOOP;
        RETURN NEW;
    END $function$;
"""


def upgrade() -> None:
    op.execute(NEW)


def downgrade() -> None:
    op.execute(OLD)
