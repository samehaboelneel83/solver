"""`spatial.internet_basemaps` is off by default: the platform is an isolated, stand-alone install first.

Since 0099 the maps offered two internet backgrounds (Esri World Imagery, OpenStreetMap) unless an organization
turned them off. On a host with no public egress they fail silently, and on one with egress they send the area
being looked at outside. The default is now false: the maps show the installation's own tilesets, or no
background, until an operator turns internet imagery on. An organization that set the value itself keeps it
(only the key's default changes).
"""

import sqlalchemy as sa
from alembic import op

revision = "0122"
down_revision = "0121"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.get_bind().execute(sa.text(
        "UPDATE setting_key SET default_value = CAST('false' AS jsonb),"
        " description = 'Offer internet imagery (Esri, OpenStreetMap) as a map background when no tile index is"
        " named. Off by default: an isolated installation reaches nothing outside, and the area being viewed"
        " stays inside; turn on only where the browser has internet and that is wanted'"
        " WHERE key = 'spatial.internet_basemaps'"))


def downgrade() -> None:
    op.get_bind().execute(sa.text(
        "UPDATE setting_key SET default_value = CAST('true' AS jsonb) WHERE key = 'spatial.internet_basemaps'"))
