"""0094: a default reaches the records made before it.

An attribute's default was written into a record only when that record was
saved (the validate triggers, migrations 0006 and 0024), so a default set on
an attribute after its records existed reached none of them. A model reading
the attribute as a number was then refused -- "employee 'ahmed' has no
'hours_per_week'" -- with a default in plain sight. Setting a default now
fills it into every record without a value (app.api.entity_types.fill_default);
this does the same, once, for the defaults already set. A value someone
entered is never overwritten.
"""

import json

from alembic import op
from sqlalchemy import text

revision = "0094"
down_revision = "0093"
branch_labels = None
depends_on = None

_MISSING = "coalesce(attrs -> :name, 'null'::jsonb) = 'null'::jsonb"


def upgrade() -> None:
    conn = op.get_bind()
    defaults = conn.execute(
        text(
            "SELECT name, default_value, entity_type_id, relationship_type_id "
            "FROM attribute_def WHERE default_value IS NOT NULL"
        )
    ).all()
    for name, value, entity_type_id, relationship_type_id in defaults:
        params = {"name": name, "value": json.dumps(value)}
        if entity_type_id is not None:
            conn.execute(
                text(
                    "UPDATE entity SET attrs = attrs || jsonb_build_object(:name, CAST(:value AS jsonb)) "
                    f"WHERE entity_type_id = ANY (entity_type_family(:owner)) AND {_MISSING}"
                ),
                {**params, "owner": entity_type_id},
            )
        elif relationship_type_id is not None:
            conn.execute(
                text(
                    "UPDATE relationship SET attrs = attrs || jsonb_build_object(:name, CAST(:value AS jsonb)) "
                    f"WHERE relationship_type_id = :owner AND {_MISSING}"
                ),
                {**params, "owner": relationship_type_id},
            )


def downgrade() -> None:
    # The filled values are indistinguishable from entered ones; nothing to undo.
    pass
