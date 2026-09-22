"""`entity_type.icon`: the picture the Graph View draws a type's entities with.

One nullable text column holding either

* a **gallery key** -- the name of one of the frontend's bundled icons
  (`hotel`, `bus_stop`), same shape as every other name here; or
* an **uploaded image** as a base64 `data:` URI, PNG, SVG or WebP, at most
  200 KB decoded.

NULL means "not chosen", exactly like `colour` (0009): the frontend picks a
default from the type's name and role, so a type called `hotel` looks like
a hotel without anybody writing that down, and follows its name until
somebody chooses otherwise. No existing row is touched.

A data URI rather than a `bytea` column and a file route: the canvas loads
images without the session's bearer token, so a protected file route would
answer 401, and an unprotected one would publish every tenant's uploads.
Carried in the payload it needs no route at all. 200 KB decoded is 273,068
base64 characters; the CHECK allows the prefix on top.

The CHECK is the backstop for writers other than the API (the seed, psql).
The request layer (`app.api.validation.validate_icon`) is stricter: it
decodes the payload, checks the bytes are what the MIME type says, and
refuses an SVG that could run script or fetch anything.
"""

from alembic import op

revision = "0031"
down_revision = "0030"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE entity_type ADD COLUMN icon text")
    op.execute(
        r"""
        ALTER TABLE entity_type ADD CONSTRAINT entity_type_icon_form CHECK (
            icon IS NULL
            OR icon ~ '^[a-z][a-z0-9_]{0,39}$'
            OR (
                length(icon) <= 273200
                AND icon ~ '^data:image/(png|webp|svg\+xml);base64,[A-Za-z0-9+/]+={0,2}$'
            )
        )
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE entity_type DROP CONSTRAINT entity_type_icon_form")
    op.execute("ALTER TABLE entity_type DROP COLUMN icon")
