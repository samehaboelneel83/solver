"""Setting `spatial.tiles_index`: where the maps find their basemaps (GIS 9).

The address of a TileJSON index -- the list a tile server publishes, one
TileJSON per tileset (`http://localhost:8080/index.json` for the Egypt
tilesets). The partition map offers its picture tilesets as backgrounds; a
tileset with an `encoding` (terrain-RGB) is elevation data, not a picture.
Empty by default: no basemap until one is named. The browser fetches the
index and the tiles itself, so the address is one the viewer's browser can
reach.
"""

import sqlalchemy as sa
from alembic import op

revision = "0050"
down_revision = "0049"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.get_bind().execute(
        sa.text(
            "INSERT INTO setting_key (key, value_type, default_value, description)"
            " VALUES ('spatial.tiles_index', 'string', CAST('\"\"' AS jsonb),"
            "         'The address of a TileJSON index whose tilesets the maps may show as a background')"
        )
    )


def downgrade() -> None:
    op.execute("DELETE FROM setting WHERE key = 'spatial.tiles_index'")
    op.execute("DELETE FROM setting_key WHERE key = 'spatial.tiles_index'")
