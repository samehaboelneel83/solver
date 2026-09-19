# Models are imported here as each schema group is implemented, so that
# Alembic's env.py (which imports this package) sees the full metadata.
#
# schema v1: the four `iam` tables are unchanged; the v0 `domain.*` and
# `problem.*` models were dropped by migration 0006 along with their
# schemas. `v1_domain` holds the eight DOMAIN tables; `v1_problem` (the
# PROBLEM + RUN tables) is added alongside it in Task 2.
from app.models.iam import Organization, Role, UserAccount, UserRole  # noqa: F401
from app.models.v1_domain import (  # noqa: F401
    AttributeDef,
    Domain,
    Entity,
    EntityType,
    ParameterDef,
    ParameterValue,
    Relationship,
    RelationshipType,
)
