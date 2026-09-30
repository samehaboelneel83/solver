"""0094: a default reaches the records made before it.

An attribute's default was written into a record only when that record was
saved (the validate triggers, migrations 0006 and 0024), so a default set on
an attribute after its records existed reached none of them. A model reading
the attribute as a number was then refused -- "employee 'ahmed' has no
'hours_per_week'" -- with a default in plain sight. Setting a default now
fills it into every record without a value (app.api.entity_types.fill_default);
this does the same, once, for the defaults already set. A value someone
entered is never overwritten.

A record the checks already refuse (a required value missing, say) is left as
it is rather than failing the whole fill: `fill_attribute_default` updates
record by record and skips one the validate trigger rejects. The migration and
the API both call it.
"""

from alembic import op

revision = "0094"
down_revision = "0093"
branch_labels = None
depends_on = None

_FILL = """
CREATE OR REPLACE FUNCTION fill_attribute_default(p_attribute bigint) RETURNS integer
LANGUAGE plpgsql AS $$
DECLARE d attribute_def; r bigint; filled integer := 0;
BEGIN
    SELECT * INTO d FROM attribute_def WHERE id = p_attribute;
    IF NOT FOUND OR d.default_value IS NULL THEN
        RETURN 0;
    END IF;
    IF d.entity_type_id IS NOT NULL THEN
        FOR r IN SELECT id FROM entity
                  WHERE entity_type_id = ANY (entity_type_family(d.entity_type_id))
                    AND coalesce(attrs -> d.name, 'null'::jsonb) = 'null'::jsonb LOOP
            BEGIN
                UPDATE entity SET attrs = attrs || jsonb_build_object(d.name, d.default_value) WHERE id = r;
                filled := filled + 1;
            EXCEPTION WHEN check_violation OR raise_exception THEN
                NULL;  -- already invalid for another reason: left for its owner to fix
            END;
        END LOOP;
    ELSIF d.relationship_type_id IS NOT NULL THEN
        FOR r IN SELECT id FROM relationship
                  WHERE relationship_type_id = d.relationship_type_id
                    AND coalesce(attrs -> d.name, 'null'::jsonb) = 'null'::jsonb LOOP
            BEGIN
                UPDATE relationship SET attrs = attrs || jsonb_build_object(d.name, d.default_value) WHERE id = r;
                filled := filled + 1;
            EXCEPTION WHEN check_violation OR raise_exception THEN
                NULL;
            END;
        END LOOP;
    END IF;
    RETURN filled;
END $$;
"""


def upgrade() -> None:
    op.execute(_FILL)
    op.execute("SELECT fill_attribute_default(id) FROM attribute_def WHERE default_value IS NOT NULL")


def downgrade() -> None:
    # The filled values are indistinguishable from entered ones; only the function goes.
    op.execute("DROP FUNCTION IF EXISTS fill_attribute_default(bigint)")
