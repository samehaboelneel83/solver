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


def _user_role_label(db: Session, row) -> str:
    from app.models.iam import Role, UserAccount

    user = db.get(UserAccount, row.user_id)
    role = db.get(Role, row.role_id)
    user_label = user.username if user else str(row.user_id)
    role_label = role.code if role else str(row.role_id)
    return f"{user_label} / {role_label}"


def _capability_label(_db: Session, row) -> str:
    description = getattr(row, "description", None)
    if description:
        return f"{row.code} — {description}"
    return str(row.code)


def _role_capability_label(db: Session, row) -> str:
    from app.models.iam import Role

    role = db.get(Role, row.role_id)
    role_label = role.code if role else str(row.role_id)
    return f"{role_label} / {row.capability_code}"


# Keyed by "schema.table". Only rows with no natural code/name label need
# an override here.
LABEL_OVERRIDES: dict[str, Callable[[Session, object], str]] = {
    "iam.user_role": _user_role_label,
    "iam.role_capability": _role_capability_label,
    "iam.capability": _capability_label,
    # schema v1: the domain.*/problem.* overrides went with their tables in
    # migration 0006. v1's own composite-key rows (parameter_value) are not
    # exposed as FK dropdown options, so nothing replaces them here yet.
}


def label_for(db: Session, row, schema: str, table: str) -> str:
    override = LABEL_OVERRIDES.get(f"{schema}.{table}")
    if override is not None:
        return override(db, row)
    return _default_label(row)
