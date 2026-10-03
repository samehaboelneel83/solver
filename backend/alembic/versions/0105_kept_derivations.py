"""0105: a kind keeps the number fields made from its other fields, to fill them on records added later.

Date parts made from a date were blank on rows imported afterwards (benchmark round 4): the fields
were made once, on the records there were. Each `date_parts`, `categories` and `from_link` made is
kept here, as it was asked for, and an import fills the fields on its records.
"""
from alembic import op

revision = "0105"
down_revision = "0104"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE entity_type ADD COLUMN derivations jsonb NOT NULL DEFAULT '[]'::jsonb")


def downgrade() -> None:
    op.execute("ALTER TABLE entity_type DROP COLUMN derivations")
