"""0067: reference attributes (queue R20a) -- an entity as an attribute's value.

An attribute of type `reference` names an entity of its target type (or of a
type inheriting from it) by key. `attrs` holds the key -- so a form, a table,
a filter and a CSV see an ordinary value -- and a trigger mirrors it into a
many-to-one relationship named after the attribute, which the API creates
with it (`attribute_def.references_id`). The mirror is what makes `via`,
R19's edge reads and the relationship checks apply to a reference.

- `entity_validate` refuses a key that names no entity it can refer to.
- `entity_reference_sync` rewrites the mirror edge on every write of `attrs`
  or `key`, and follows a renamed target into whoever refers to it.
- `entity_reference_release` clears an optional reference when its target is
  deleted, and refuses the delete when the reference is required.
- `relationship_reference_guard` refuses writing a mirror edge directly.

Downgrade: refused while a reference attribute exists. `reference` stays in
`attr_type`, unused (Postgres cannot drop an enum value).
"""

import sqlalchemy as sa
from alembic import op

revision = "0067"
down_revision = "0066"
branch_labels = None
depends_on = None

_ENTITY_VALIDATE = 'CREATE OR REPLACE FUNCTION public.entity_validate()\n RETURNS trigger\n LANGUAGE plpgsql\nAS $function$\n    DECLARE d attribute_def; v jsonb; k text;\n    BEGIN\n        IF (SELECT is_abstract FROM entity_type WHERE id = NEW.entity_type_id) THEN\n            RAISE EXCEPTION \'entity %: its type is abstract and holds no entities of its own; use one of the types that inherit from it\', NEW.key\n                USING ERRCODE = \'23514\',\n                      DETAIL  = jsonb_build_object(\'kind\', \'abstract_type\', \'field\', \'entity_type_id\', \'record\', NEW.key)::text;\n        END IF;\n        FOR k IN SELECT jsonb_object_keys(NEW.attrs) LOOP\n            IF NOT EXISTS (SELECT 1 FROM attribute_def\n                           WHERE entity_type_id = ANY (entity_type_lineage(NEW.entity_type_id)) AND name = k) THEN\n                RAISE EXCEPTION \'entity %: unknown attribute "%"\', NEW.key, k\n                    USING ERRCODE = \'23514\',\n                          DETAIL  = jsonb_build_object(\'kind\', \'unknown_attribute\', \'field\', k, \'record\', NEW.key)::text;\n            END IF;\n        END LOOP;\n        FOR d IN SELECT * FROM attribute_def WHERE entity_type_id = ANY (entity_type_lineage(NEW.entity_type_id)) LOOP\n            v := NEW.attrs -> d.name;\n            IF v IS NULL AND d.default_value IS NOT NULL THEN\n                NEW.attrs := NEW.attrs || jsonb_build_object(d.name, d.default_value);\n                v := d.default_value;\n            END IF;\n            IF v IS NULL OR v = \'null\' THEN\n                IF d.required THEN\n                    RAISE EXCEPTION \'entity %: attribute "%" is required\', NEW.key, d.name\n                        USING ERRCODE = \'23514\',\n                              DETAIL  = jsonb_build_object(\'kind\', \'required_attribute\', \'field\', d.name, \'record\', NEW.key)::text;\n                END IF;\n                CONTINUE;\n            END IF;\n            IF NOT attr_value_matches_type(d.data_type, d.enum_values, v) THEN\n                RAISE EXCEPTION \'entity %: attribute "%" must be %\', NEW.key, d.name, d.data_type\n                    USING ERRCODE = \'23514\',\n                          DETAIL  = jsonb_build_object(\'kind\', \'attribute_type\', \'field\', d.name,\n                                                       \'record\', NEW.key, \'expected\', d.data_type::text)::text;\n            END IF;\n            -- Migration 0067 (queue R20a): a reference names an entity of its target type (or one\n            -- inheriting from it) by key.\n            IF d.data_type::text = \'reference\' AND NOT EXISTS (\n                SELECT 1 FROM entity e JOIN relationship_type rt ON rt.id = d.references_id\n                 WHERE e.key = v #>> \'{}\' AND entity_type_is_a(e.entity_type_id, rt.to_type_id)) THEN\n                RAISE EXCEPTION \'entity %: attribute "%" names "%", which is not an entity it can refer to\', NEW.key, d.name, v #>> \'{}\'\n                    USING ERRCODE = \'23514\',\n                          DETAIL  = jsonb_build_object(\'kind\', \'reference_unknown\', \'field\', d.name,\n                                                       \'record\', NEW.key)::text;\n            END IF;\n        END LOOP;\n        RETURN NEW;\n    END $function$'

_ENTITY_VALIDATE_0066 = 'CREATE OR REPLACE FUNCTION public.entity_validate()\n RETURNS trigger\n LANGUAGE plpgsql\nAS $function$\n    DECLARE d attribute_def; v jsonb; k text;\n    BEGIN\n        IF (SELECT is_abstract FROM entity_type WHERE id = NEW.entity_type_id) THEN\n            RAISE EXCEPTION \'entity %: its type is abstract and holds no entities of its own; use one of the types that inherit from it\', NEW.key\n                USING ERRCODE = \'23514\',\n                      DETAIL  = jsonb_build_object(\'kind\', \'abstract_type\', \'field\', \'entity_type_id\', \'record\', NEW.key)::text;\n        END IF;\n        FOR k IN SELECT jsonb_object_keys(NEW.attrs) LOOP\n            IF NOT EXISTS (SELECT 1 FROM attribute_def\n                           WHERE entity_type_id = ANY (entity_type_lineage(NEW.entity_type_id)) AND name = k) THEN\n                RAISE EXCEPTION \'entity %: unknown attribute "%"\', NEW.key, k\n                    USING ERRCODE = \'23514\',\n                          DETAIL  = jsonb_build_object(\'kind\', \'unknown_attribute\', \'field\', k, \'record\', NEW.key)::text;\n            END IF;\n        END LOOP;\n        FOR d IN SELECT * FROM attribute_def WHERE entity_type_id = ANY (entity_type_lineage(NEW.entity_type_id)) LOOP\n            v := NEW.attrs -> d.name;\n            IF v IS NULL AND d.default_value IS NOT NULL THEN\n                NEW.attrs := NEW.attrs || jsonb_build_object(d.name, d.default_value);\n                v := d.default_value;\n            END IF;\n            IF v IS NULL OR v = \'null\' THEN\n                IF d.required THEN\n                    RAISE EXCEPTION \'entity %: attribute "%" is required\', NEW.key, d.name\n                        USING ERRCODE = \'23514\',\n                              DETAIL  = jsonb_build_object(\'kind\', \'required_attribute\', \'field\', d.name, \'record\', NEW.key)::text;\n                END IF;\n                CONTINUE;\n            END IF;\n            IF NOT attr_value_matches_type(d.data_type, d.enum_values, v) THEN\n                RAISE EXCEPTION \'entity %: attribute "%" must be %\', NEW.key, d.name, d.data_type\n                    USING ERRCODE = \'23514\',\n                          DETAIL  = jsonb_build_object(\'kind\', \'attribute_type\', \'field\', d.name,\n                                                       \'record\', NEW.key, \'expected\', d.data_type::text)::text;\n            END IF;\n        END LOOP;\n        RETURN NEW;\n    END $function$'

_SYNC = '\nCREATE OR REPLACE FUNCTION entity_reference_sync() RETURNS trigger LANGUAGE plpgsql AS $$\n    -- The attribute is the record; the relationship is its mirror, so `via`, edge reads and the\n    -- relationship checks apply. Written with solver.reference_sync on, which the guard allows.\n    DECLARE d attribute_def; target bigint; r record;\n    BEGIN\n        PERFORM set_config(\'solver.reference_sync\', \'on\', true);\n        FOR d IN SELECT * FROM attribute_def\n                  WHERE entity_type_id = ANY (entity_type_lineage(NEW.entity_type_id))\n                    AND data_type::text = \'reference\' LOOP\n            DELETE FROM relationship WHERE relationship_type_id = d.references_id AND from_entity_id = NEW.id;\n            IF NEW.attrs ? d.name AND NEW.attrs -> d.name <> \'null\' THEN\n                SELECT e.id INTO target FROM entity e JOIN relationship_type rt ON rt.id = d.references_id\n                 WHERE e.key = NEW.attrs ->> d.name AND entity_type_is_a(e.entity_type_id, rt.to_type_id)\n                 LIMIT 1;\n                INSERT INTO relationship (relationship_type_id, from_entity_id, to_entity_id)\n                VALUES (d.references_id, NEW.id, target);\n            END IF;\n        END LOOP;\n        -- A renamed target: whoever refers to it now names the new key.\n        IF TG_OP = \'UPDATE\' AND OLD.key IS DISTINCT FROM NEW.key THEN\n            FOR r IN SELECT rel.from_entity_id AS source, ad.name AS attribute\n                       FROM relationship rel JOIN attribute_def ad ON ad.references_id = rel.relationship_type_id\n                      WHERE rel.to_entity_id = NEW.id LOOP\n                UPDATE entity SET attrs = jsonb_set(attrs, ARRAY[r.attribute], to_jsonb(NEW.key))\n                 WHERE id = r.source;\n            END LOOP;\n        END IF;\n        PERFORM set_config(\'solver.reference_sync\', \'off\', true);\n        RETURN NULL;\n    END $$;\n\nCREATE TRIGGER entity_reference_sync AFTER INSERT OR UPDATE OF attrs, key ON entity\n    FOR EACH ROW EXECUTE FUNCTION entity_reference_sync();\n\nCREATE OR REPLACE FUNCTION entity_reference_release() RETURNS trigger LANGUAGE plpgsql AS $$\n    -- An entity others refer to is deleted: a required reference refuses; an optional one is cleared.\n    DECLARE r record;\n    BEGIN\n        -- The target\'s whole type is going (a type or a domain deleted): so is everything that\n        -- could refer to it, and the cascade settles the edges.\n        IF NOT EXISTS (SELECT 1 FROM entity_type WHERE id = OLD.entity_type_id) THEN\n            RETURN OLD;\n        END IF;\n        FOR r IN SELECT rel.from_entity_id AS source, ad.name AS attribute, ad.required, src.key AS source_key\n                   FROM relationship rel\n                   JOIN attribute_def ad ON ad.references_id = rel.relationship_type_id\n                   JOIN entity src ON src.id = rel.from_entity_id\n                  WHERE rel.to_entity_id = OLD.id AND rel.from_entity_id <> OLD.id LOOP\n            IF r.required THEN\n                RAISE EXCEPTION \'entity %: % refers to it through the required attribute "%"; change that first\', OLD.key, r.source_key, r.attribute\n                    USING ERRCODE = \'23514\',\n                          DETAIL  = jsonb_build_object(\'kind\', \'reference_required\', \'field\', r.attribute,\n                                                       \'record\', OLD.key)::text;\n            END IF;\n            UPDATE entity SET attrs = attrs - r.attribute WHERE id = r.source;\n        END LOOP;\n        RETURN OLD;\n    END $$;\n\nCREATE TRIGGER entity_reference_release BEFORE DELETE ON entity\n    FOR EACH ROW EXECUTE FUNCTION entity_reference_release();\n\nCREATE OR REPLACE FUNCTION relationship_reference_guard() RETURNS trigger LANGUAGE plpgsql AS $$\n    -- A reference attribute\'s relationship is written through the attribute, never directly.\n    DECLARE row_ relationship; name_ text;\n    BEGIN\n        IF coalesce(current_setting(\'solver.reference_sync\', true), \'\') = \'on\' THEN\n            RETURN NULL;\n        END IF;\n        row_ := CASE WHEN TG_OP = \'DELETE\' THEN OLD ELSE NEW END;\n        SELECT ad.name INTO name_ FROM attribute_def ad WHERE ad.references_id = row_.relationship_type_id;\n        IF name_ IS NULL OR NOT EXISTS (SELECT 1 FROM relationship_type WHERE id = row_.relationship_type_id) THEN\n            RETURN NULL;\n        END IF;\n        -- Deleting the source entity takes its edges with it, and an attribute already cleared has\n        -- nothing left to disagree with.\n        IF TG_OP = \'DELETE\' AND NOT EXISTS (SELECT 1 FROM entity WHERE id = row_.from_entity_id AND attrs ? name_) THEN\n            RETURN NULL;\n        END IF;\n        RAISE EXCEPTION \'relationship "%" is the reference attribute "%"; set it on the entity instead\', name_, name_\n            USING ERRCODE = \'23514\',\n                  DETAIL  = jsonb_build_object(\'kind\', \'reference_relationship\', \'field\', name_)::text;\n    END $$;\n\nCREATE TRIGGER relationship_reference_guard AFTER INSERT OR UPDATE OR DELETE ON relationship\n    FOR EACH ROW EXECUTE FUNCTION relationship_reference_guard();\n'


def upgrade() -> None:
    # A new enum value cannot be used in the transaction that adds it; the
    # checks and functions below only name it as text.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE attr_type ADD VALUE IF NOT EXISTS 'reference'")
    op.execute("""
        ALTER TABLE attribute_def
            ADD COLUMN references_id bigint REFERENCES relationship_type (id) ON DELETE CASCADE,
            ADD CONSTRAINT attribute_def_reference_pairing
                CHECK ((data_type::text = 'reference') = (references_id IS NOT NULL)),
            ADD CONSTRAINT attribute_def_reference_on_entity_type
                CHECK (references_id IS NULL OR entity_type_id IS NOT NULL),
            ADD CONSTRAINT attribute_def_reference_no_default
                CHECK (references_id IS NULL OR default_value IS NULL);
        CREATE UNIQUE INDEX attribute_def_references_id_key ON attribute_def (references_id)
            WHERE references_id IS NOT NULL;
    """)
    op.execute(_ENTITY_VALIDATE)
    op.execute(_SYNC)


def downgrade() -> None:
    if op.get_bind().execute(sa.text("SELECT 1 FROM attribute_def WHERE references_id IS NOT NULL LIMIT 1")).first():
        raise RuntimeError("reference attributes exist; delete them before downgrading past 0067")
    op.execute("""
        DROP TRIGGER IF EXISTS relationship_reference_guard ON relationship;
        DROP FUNCTION IF EXISTS relationship_reference_guard();
        DROP TRIGGER IF EXISTS entity_reference_release ON entity;
        DROP FUNCTION IF EXISTS entity_reference_release();
        DROP TRIGGER IF EXISTS entity_reference_sync ON entity;
        DROP FUNCTION IF EXISTS entity_reference_sync();
        DROP INDEX IF EXISTS attribute_def_references_id_key;
        ALTER TABLE attribute_def
            DROP CONSTRAINT IF EXISTS attribute_def_reference_no_default,
            DROP CONSTRAINT IF EXISTS attribute_def_reference_on_entity_type,
            DROP CONSTRAINT IF EXISTS attribute_def_reference_pairing,
            DROP COLUMN IF EXISTS references_id;
    """)
    op.execute(_ENTITY_VALIDATE_0066)
