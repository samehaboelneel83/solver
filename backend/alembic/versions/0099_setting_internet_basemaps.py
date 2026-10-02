"""Setting `spatial.internet_basemaps`: may the maps offer internet imagery?

When no tile index is named (`spatial.tiles_index`), the camp editor, map data viewer and field
view fall back to two built-in backgrounds on the internet -- Esri World Imagery and OpenStreetMap.
The browser then sends the area being looked at to those services. For an installation meant to
run offline, or whose sites should not leave it, setting this to false drops them: the maps show
the organization's own tilesets, or no background. True by default, as before.
"""

import sqlalchemy as sa
from alembic import op

revision = "0099"
down_revision = "0098"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.get_bind().execute(
        sa.text(
            "INSERT INTO setting_key (key, value_type, default_value, description)"
            " VALUES ('spatial.internet_basemaps', 'boolean', CAST('true' AS jsonb),"
            "         'Offer internet imagery (Esri, OpenStreetMap) as a map background when no tile index is named;"
            " false keeps the area being viewed inside the installation')"
        )
    )


def downgrade() -> None:
    op.execute("DELETE FROM setting WHERE key = 'spatial.internet_basemaps'")
    op.execute("DELETE FROM setting_key WHERE key = 'spatial.internet_basemaps'")
