"""Human-readable labels for FK-dropdown options.

Used by `backend/app/api/options.py` to turn a raw row into
`{"id": ..., "label": ...}` so admin UI dropdowns don't just show UUIDs.
"""

from typing import Callable

from sqlalchemy.orm import Session

# Columns tried, in order, for the default label when a row has no
# "code — name" pair. Also reported back via meta.py's `label_field` key.
DEFAULT_LABEL_COLUMNS = ("code", "name", "username", "state_value")


def _default_label(row) -> str:
    code = getattr(row, "code", None)
    name = getattr(row, "name", None)
    if code and name:
        return f"{code} — {name}"
    for column in DEFAULT_LABEL_COLUMNS:
        value = getattr(row, column, None)
        if value:
            return str(value)
    return str(row.id)


def _hierarchy_node_label(db: Session, row) -> str:
    from app.models.domain import Entity, Hierarchy

    entity = db.get(Entity, row.entity_id)
    hierarchy = db.get(Hierarchy, row.hierarchy_id)
    entity_label = (entity.name or entity.code) if entity else str(row.entity_id)
    hierarchy_label = hierarchy.name if hierarchy else str(row.hierarchy_id)
    return f"{entity_label} in {hierarchy_label}"


def _entity_attribute_label(db: Session, row) -> str:
    from app.models.domain import AttributeDefinition, Entity

    entity = db.get(Entity, row.entity_id)
    attribute = db.get(AttributeDefinition, row.attribute_id)
    entity_label = (entity.name or entity.code) if entity else str(row.entity_id)
    attribute_label = attribute.code if attribute else str(row.attribute_id)
    return f"{entity_label}: {attribute_label}"


def _variable_dimension_label(db: Session, row) -> str:
    from app.models.problem import VariableDefinition

    variable = db.get(VariableDefinition, row.variable_id)
    variable_label = variable.code if variable else str(row.variable_id)
    return f"{variable_label} #{row.dimension_order}"


def _user_role_label(db: Session, row) -> str:
    from app.models.iam import Role, UserAccount

    user = db.get(UserAccount, row.user_id)
    role = db.get(Role, row.role_id)
    user_label = user.username if user else str(row.user_id)
    role_label = role.code if role else str(row.role_id)
    return f"{user_label} / {role_label}"


def _objective_component_label(db: Session, row) -> str:
    from app.models.problem import Objective

    if row.code:
        return row.code
    objective = db.get(Objective, row.objective_id)
    objective_label = objective.code if objective else str(row.objective_id)
    return f"{objective_label} component"


# Keyed by "schema.table". Only rows with no natural code/name label need
# an override here.
LABEL_OVERRIDES: dict[str, Callable[[Session, object], str]] = {
    "domain.hierarchy_node": _hierarchy_node_label,
    "domain.entity_attribute": _entity_attribute_label,
    "problem.variable_dimension": _variable_dimension_label,
    "iam.user_role": _user_role_label,
    "problem.objective_component": _objective_component_label,
}


def label_for(db: Session, row, schema: str, table: str) -> str:
    override = LABEL_OVERRIDES.get(f"{schema}.{table}")
    if override is not None:
        return override(db, row)
    return _default_label(row)
