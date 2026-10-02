"""0103: a geometry field holds a line too -- a road, a canal, a pipe -- not only a point or an area.

Lines imported from a map were kept as their length and a point halfway along (benchmark,
October 2026: canals and roads shown as dots, no road could be tested against a construction
zone). `attr_value_matches_type` now accepts LineString and MultiLineString; the app checks each
position as it does for the others (`app.spatial.geometry`).
"""
from alembic import op

revision = "0103"
down_revision = "0102"
branch_labels = None
depends_on = None

NEW = r"""
CREATE OR REPLACE FUNCTION public.attr_value_matches_type(p_type attr_type, p_enum_values text[], p_value jsonb)
 RETURNS boolean
 LANGUAGE sql
 IMMUTABLE PARALLEL SAFE
AS $function$
            SELECT coalesce(CASE p_type::text
                WHEN 'integer' THEN CASE WHEN jsonb_typeof(p_value) = 'number'
                                         THEN (p_value #>> '{}')::numeric % 1 = 0
                                         ELSE false END
                WHEN 'number'  THEN jsonb_typeof(p_value) = 'number'
                WHEN 'boolean' THEN jsonb_typeof(p_value) = 'boolean'
                WHEN 'enum'    THEN jsonb_typeof(p_value) = 'string'
                                    AND (p_value #>> '{}') = ANY (p_enum_values)
                WHEN 'geometry' THEN jsonb_typeof(p_value) = 'object'
                                     AND (p_value ->> 'type') IN ('Point', 'LineString', 'MultiLineString', 'Polygon', 'MultiPolygon')
                                     AND jsonb_typeof(p_value -> 'coordinates') = 'array'
                ELSE                jsonb_typeof(p_value) = 'string'
            END, false)
        $function$;
"""

OLD = r"""
CREATE OR REPLACE FUNCTION public.attr_value_matches_type(p_type attr_type, p_enum_values text[], p_value jsonb)
 RETURNS boolean
 LANGUAGE sql
 IMMUTABLE PARALLEL SAFE
AS $function$
            SELECT coalesce(CASE p_type::text
                WHEN 'integer' THEN CASE WHEN jsonb_typeof(p_value) = 'number'
                                         THEN (p_value #>> '{}')::numeric % 1 = 0
                                         ELSE false END
                WHEN 'number'  THEN jsonb_typeof(p_value) = 'number'
                WHEN 'boolean' THEN jsonb_typeof(p_value) = 'boolean'
                WHEN 'enum'    THEN jsonb_typeof(p_value) = 'string'
                                    AND (p_value #>> '{}') = ANY (p_enum_values)
                WHEN 'geometry' THEN jsonb_typeof(p_value) = 'object'
                                     AND (p_value ->> 'type') IN ('Point', 'Polygon', 'MultiPolygon')
                                     AND jsonb_typeof(p_value -> 'coordinates') = 'array'
                ELSE                jsonb_typeof(p_value) = 'string'
            END, false)
        $function$;
"""


def upgrade() -> None:
    op.execute(NEW)


def downgrade() -> None:
    op.execute(OLD)
