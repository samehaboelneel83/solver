"""0027: attributes have an order someone chose.

Until now an entity type's attributes were listed alphabetically, everywhere:
the type's attribute table, the entity form, the graph's node panel. That is a
stable order, but not a meaningful one. A form reading `full_name, grade,
hired_on, hourly_rate, hours_per_week, on_call` puts the name first by luck
and the hours after the rate by spelling. The person who designed the type
knows what belongs together; the alphabet does not.

`attribute_def.sort_order` is that choice, stored. Lower comes first, and
`name` breaks ties, so two attributes left at the same number still list
predictably rather than in whatever order the planner returns them.

**Backfilled to today's order.** Existing attributes are numbered 1, 2, 3...
by name within their owner, so nothing on any screen moves when this runs.
The order changes only when someone changes it.

**Numbered per owner**, an entity type or a relationship type (migration
0024 lets either own attributes), because an order only means something among
the attributes that are shown together.

No uniqueness constraint on `(owner, sort_order)`. Reordering rewrites every
position in one statement (`PUT .../attribute-order`), and a unique index
would have to be deferred for that to work. What the constraint would protect,
two attributes sharing a number, is harmless given the name tie-break.
"""

from alembic import op

revision = "0027"
down_revision = "0026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE attribute_def
            ADD COLUMN sort_order integer NOT NULL DEFAULT 0;

        -- Today's order, made explicit: alphabetical within each owner.
        UPDATE attribute_def a
           SET sort_order = numbered.position
          FROM (SELECT id,
                       row_number() OVER (
                           PARTITION BY entity_type_id, relationship_type_id
                           ORDER BY name
                       ) AS position
                  FROM attribute_def) numbered
         WHERE numbered.id = a.id;

        CREATE INDEX attribute_def_entity_type_order
            ON attribute_def (entity_type_id, sort_order, name)
            WHERE entity_type_id IS NOT NULL;
        CREATE INDEX attribute_def_relationship_type_order
            ON attribute_def (relationship_type_id, sort_order, name)
            WHERE relationship_type_id IS NOT NULL;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP INDEX attribute_def_relationship_type_order;
        DROP INDEX attribute_def_entity_type_order;
        ALTER TABLE attribute_def DROP COLUMN sort_order;
        """
    )
