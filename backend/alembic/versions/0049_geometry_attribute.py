"""The `geometry` attribute type (GeoJSON), and the domain setting `spatial.crs`.

A geometry is a GeoJSON Point, Polygon or MultiPolygon stored in `attrs` as
given. The database judges its shape coarsely (an object of one of the three
types with an array of coordinates); `app.spatial.geometry` judges it fully
on every API write, naming the ring or position at fault.

`entity_validate` now asks `attr_value_matches_type` (migration 0009) rather
than repeating its own CASE, so entities, relationships and defaults cannot
disagree about what a value of a type is.

Downgrade: refused while any geometry attribute exists. Postgres cannot drop
a value from an enum, so `geometry` stays in `attr_type`, unused.
"""

import sqlalchemy as sa
from alembic import op

revision = "0049"
down_revision = "0048"
branch_labels = None
depends_on = None

_GEOMETRY_CASE = """
                WHEN 'geometry' THEN jsonb_typeof(p_value) = 'object'
                                     AND (p_value ->> 'type') IN ('Point', 'Polygon', 'MultiPolygon')
                                     AND jsonb_typeof(p_value -> 'coordinates') = 'array'"""


def _matches(with_geometry: bool) -> str:
    return f"""
        CREATE OR REPLACE FUNCTION attr_value_matches_type(p_type attr_type, p_enum_values text[], p_value jsonb)
        RETURNS boolean LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
            SELECT coalesce(CASE p_type::text
                WHEN 'integer' THEN CASE WHEN jsonb_typeof(p_value) = 'number'
                                         THEN (p_value #>> '{{}}')::numeric % 1 = 0
                                         ELSE false END
                WHEN 'number'  THEN jsonb_typeof(p_value) = 'number'
                WHEN 'boolean' THEN jsonb_typeof(p_value) = 'boolean'
                WHEN 'enum'    THEN jsonb_typeof(p_value) = 'string'
                                    AND (p_value #>> '{{}}') = ANY (p_enum_values){_GEOMETRY_CASE if with_geometry else ""}
                ELSE                jsonb_typeof(p_value) = 'string'
            END, false)
        $$;
    """


_ENTITY_VALIDATE = """
    CREATE OR REPLACE FUNCTION entity_validate() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE d attribute_def; v jsonb; k text;
    BEGIN
        FOR k IN SELECT jsonb_object_keys(NEW.attrs) LOOP
            IF NOT EXISTS (SELECT 1 FROM attribute_def
                           WHERE entity_type_id = NEW.entity_type_id AND name = k) THEN
                RAISE EXCEPTION 'entity %: unknown attribute "%"', NEW.key, k
                    USING ERRCODE = '23514',
                          DETAIL  = jsonb_build_object('kind', 'unknown_attribute', 'field', k, 'record', NEW.key)::text;
            END IF;
        END LOOP;
        FOR d IN SELECT * FROM attribute_def WHERE entity_type_id = NEW.entity_type_id LOOP
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
        END LOOP;
        RETURN NEW;
    END $$;
"""


def upgrade() -> None:
    # A new enum value cannot be used in the transaction that adds it; the
    # functions below only name it as text, resolved when they run.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE attr_type ADD VALUE IF NOT EXISTS 'geometry'")
    op.execute(_matches(with_geometry=True))
    op.execute(_ENTITY_VALIDATE)
    op.get_bind().execute(
        sa.text(
            "INSERT INTO setting_key (key, value_type, default_value, description) VALUES"
            " ('spatial.crs', 'number', CAST('4326' AS jsonb),"
            "  'The EPSG code of the coordinates this domain''s geometry is written in')"
        )
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM attribute_def WHERE data_type::text = 'geometry') THEN
                RAISE EXCEPTION 'geometry attributes exist; delete them before downgrading 0049';
            END IF;
        END $$;
        """
    )
    op.execute("DELETE FROM setting WHERE key = 'spatial.crs'")
    op.execute("DELETE FROM setting_key WHERE key = 'spatial.crs'")
    op.execute(_matches(with_geometry=False))
    op.execute(_ENTITY_VALIDATE)
