# Models are imported here as each schema group is implemented, so that
# Alembic's env.py (which imports this package) sees the full metadata.
from app.models.iam import Organization, Role, UserAccount, UserRole  # noqa: F401
from app.models.domain import (  # noqa: F401
    AttributeDefinition,
    Entity,
    EntityAttribute,
    EntityType,
    Relationship,
    RelationshipType,
)
