# Models are imported here as each schema group is implemented, so that
# Alembic's env.py (which imports this package) sees the full metadata.
#
# schema v1: the four `iam` tables are unchanged; the v0 `domain.*` and
# `problem.*` models were dropped by migration 0006 along with their
# schemas. `v1_domain` holds the eight DOMAIN tables; `v1_problem` holds
# the four PROBLEM and four RUN tables.
from app.models.iam import Organization, Role, RoleCapability, UserAccount, UserRole  # noqa: F401
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
from app.models.v1_problem import (  # noqa: F401
    IMMUTABLE_TABLES,
    ConstraintResult,
    Dataset,
    ModelVersion,
    Problem,
    Run,
    Scenario,
    Solution,
    Template,
)
