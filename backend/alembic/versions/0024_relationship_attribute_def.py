"""0024: attribute_def may belong to a relationship type

``attribute_def`` was entity-type-only, so ``relationship.attrs`` had
nothing to validate against and the graph panel edited it as raw JSON.
This revision lets the same row belong to a ``relationship_type`` instead
(exactly one owner). A type with no defs still accepts free-form attrs;
once a def exists, ``relationship_attrs_validate`` applies the same
kinds as ``entity_validate``.

Revision ID: 0024
Revises: 0023
Create Date: 2026-09-21
"""
from alembic import op

revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE attribute_def
            ALTER COLUMN entity_type_id DROP NOT NULL,
            ADD COLUMN relationship_type_id bigint REFERENCES relationship_type(id) ON DELETE CASCADE;

        ALTER TABLE attribute_def
            DROP CONSTRAINT IF EXISTS attribute_def_entity_type_id_name_key;

        ALTER TABLE attribute_def
            ADD CONSTRAINT attribute_def_one_owner CHECK (
                (entity_type_id IS NOT NULL) <> (relationship_type_id IS NOT NULL)
            );

        CREATE UNIQUE INDEX attribute_def_entity_type_id_name_key
            ON attribute_def (entity_type_id, name)
            WHERE entity_type_id IS NOT NULL;

        CREATE UNIQUE INDEX attribute_def_relationship_type_id_name_key
            ON attribute_def (relationship_type_id, name)
            WHERE relationship_type_id IS NOT NULL;

        CREATE FUNCTION relationship_attrs_validate() RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE d attribute_def; v jsonb; k text;
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM attribute_def WHERE relationship_type_id = NEW.relationship_type_id
            ) THEN
                RETURN NEW;
            END IF;
            FOR k IN SELECT jsonb_object_keys(NEW.attrs) LOOP
                IF NOT EXISTS (
                    SELECT 1 FROM attribute_def
                     WHERE relationship_type_id = NEW.relationship_type_id AND name = k
                ) THEN
                    RAISE EXCEPTION 'relationship %: unknown attribute "%"', NEW.id, k
                        USING ERRCODE = '23514',
                              DETAIL  = jsonb_build_object(
                                  'kind',   'unknown_attribute',
                                  'field',  k,
                                  'record', NEW.id)::text;
                END IF;
            END LOOP;
            FOR d IN SELECT * FROM attribute_def
                      WHERE relationship_type_id = NEW.relationship_type_id LOOP
                v := NEW.attrs -> d.name;
                IF v IS NULL AND d.default_value IS NOT NULL THEN
                    NEW.attrs := NEW.attrs || jsonb_build_object(d.name, d.default_value);
                    v := d.default_value;
                END IF;
                IF v IS NULL OR v = 'null' THEN
                    IF d.required THEN
                        RAISE EXCEPTION 'relationship %: attribute "%" is required', NEW.id, d.name
                            USING ERRCODE = '23514',
                                  DETAIL  = jsonb_build_object(
                                      'kind',   'required_attribute',
                                      'field',  d.name,
                                      'record', NEW.id)::text;
                    END IF;
                    CONTINUE;
                END IF;
                IF NOT attr_value_matches_type(d.data_type, d.enum_values, v) THEN
                    RAISE EXCEPTION 'relationship %: attribute "%" must be %', NEW.id, d.name, d.data_type
                        USING ERRCODE = '23514',
                              DETAIL  = jsonb_build_object(
                                  'kind',     'attribute_type',
                                  'field',    d.name,
                                  'record',   NEW.id,
                                  'expected', d.data_type::text)::text;
                END IF;
            END LOOP;
            RETURN NEW;
        END $$;

        CREATE TRIGGER relationship_attrs_validate
            BEFORE INSERT OR UPDATE ON relationship
            FOR EACH ROW EXECUTE FUNCTION relationship_attrs_validate();
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TRIGGER IF EXISTS relationship_attrs_validate ON relationship;
        DROP FUNCTION IF EXISTS relationship_attrs_validate();

        DELETE FROM attribute_def WHERE relationship_type_id IS NOT NULL;

        DROP INDEX IF EXISTS attribute_def_relationship_type_id_name_key;
        DROP INDEX IF EXISTS attribute_def_entity_type_id_name_key;

        ALTER TABLE attribute_def DROP CONSTRAINT IF EXISTS attribute_def_one_owner;
        ALTER TABLE attribute_def DROP COLUMN IF EXISTS relationship_type_id;
        ALTER TABLE attribute_def ALTER COLUMN entity_type_id SET NOT NULL;
        ALTER TABLE attribute_def
            ADD CONSTRAINT attribute_def_entity_type_id_name_key UNIQUE (entity_type_id, name);
        """
    )
