import datetime
import typing
import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import inspect
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.db import get_db
from app.crud.labels import DEFAULT_LABEL_COLUMNS
from app.crud.registry import TABLE_REGISTRY
from app.ir.contract import IR_VERSION
from app.models.iam import UserAccount

router = APIRouter(prefix="/api/meta", tags=["meta"])

# Hints only -- the CRUD routes still accept any value. The v0 shared
# lists (`status`, `data_type`, …) never attached to a factory field and
# are gone; the one leftover that does is the IR version a template stores.
CHOICES: dict[tuple[str | None, str], list[str]] = {
    ("template", "ir_version"): [str(IR_VERSION)],
}


def _choices_for(table: str, field: str) -> list[str] | None:
    return CHOICES.get((table, field)) or CHOICES.get((None, field))


# Human-readable field labels for the schema-driven UI (Task 3 consumes
# these), keyed by (table, field) with a (None, field) fallback shared
# across tables that use the same field name -- same shape as CHOICES
# above. Only fields whose plain-English label isn't what humanise()
# would produce need an entry here (e.g. "entity_type_id" would
# otherwise humanise to "Entity type", which reads oddly as a field
# label on the entity/hierarchy/etc. rows that carry it).
FIELD_LABELS: dict[tuple[str | None, str], str] = {
    # v1's relationship table names these from_entity_id/to_entity_id (v0
    # was source_entity_id/target_entity_id).
    (None, "from_entity_id"): "From",
    (None, "to_entity_id"): "To",
    (None, "entity_type_id"): "Type",
    (None, "organization_id"): "Organization",
    ("role_capability", "capability_code"): "Capability",
}

# Table labels (singular, plural) for tables whose plural isn't just
# humanise(table) + "s". Every one of v1's 16 tables was checked; only
# "entity" needs an override -- the rest (including "parameter_def",
# "scenario", "constraint_result") pluralise correctly with a trailing
# "s". v0's "hierarchy" table has no v1 equivalent (hierarchies are now
# `relationship` rows with `is_hierarchy=true`), so that override is gone
# rather than retargeted.
TABLE_LABELS: dict[str, tuple[str, str]] = {
    "entity": ("Entity", "Entities"),
    "role_capability": ("Role capability", "Role capabilities"),
    "capability": ("Capability", "Capabilities"),
}


def humanise(name: str) -> str:
    """Fallback label for a table or field with no explicit override:
    strip a single trailing "_id", drop an "is_" prefix so boolean
    columns read as the thing they describe ("is_active" -> "Active")
    rather than as a question, replace underscores with spaces, and
    capitalise only the first character -- leaving the rest of the
    string (and any already-upper-case acronym) untouched. Trailing
    underscores are stripped too: columns whose name collides with a
    SQLAlchemy attribute are aliased that way (e.g. "metadata_"), and
    the alias should never reach the user as a stray space."""
    if name.endswith("_id"):
        name = name[: -len("_id")]
    if name.startswith("is_"):
        name = name[len("is_") :]
    name = name.rstrip("_").replace("_", " ")
    if not name:
        return name
    return name[0].upper() + name[1:]


def _field_label(table: str, field: str) -> str:
    return FIELD_LABELS.get((table, field)) or FIELD_LABELS.get((None, field)) or humanise(field)


def _table_labels(table: str) -> tuple[str, str]:
    override = TABLE_LABELS.get(table)
    if override is not None:
        return override
    singular = humanise(table)
    return singular, f"{singular}s"


def _scalar_default(column):
    """The client-side ORM default's value, when it's a plain scalar
    (str/int/bool/float) rather than a callable like uuid.uuid4."""
    default = getattr(column, "default", None)
    if default is None:
        return None
    arg = getattr(default, "arg", None)
    if callable(arg):
        return None
    if isinstance(arg, (str, int, bool, float)):
        return arg
    return None

_TYPE_LABELS: dict[type, str] = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
    datetime.date: "date",
    datetime.datetime: "datetime",
    uuid.UUID: "uuid",
}


def _type_label(annotation) -> str:
    """Unwrap Optional[...] and map to a simple label the frontend
    renders directly (falls back to "json" for JSONB/Any columns)."""
    args = typing.get_args(annotation)
    base = args[0] if args else annotation
    return _TYPE_LABELS.get(base, "json")


@router.get("/schema")
def get_schema(_: UserAccount = Depends(get_current_user)) -> list[dict]:
    tables = []
    for meta in TABLE_REGISTRY:
        mapper = inspect(meta.model)
        fk_table_by_field: dict[str, str] = {}
        nullable_by_field: dict[str, bool] = {}
        has_client_default_by_field: dict[str, bool] = {}
        default_by_field: dict[str, object] = {}
        for attr in mapper.column_attrs:
            column = attr.columns[0]
            nullable_by_field[attr.key] = column.nullable
            has_client_default_by_field[attr.key] = column.default is not None
            default_by_field[attr.key] = _scalar_default(column)
            for fk in column.foreign_keys:
                fk_table_by_field[attr.key] = fk.column.table.fullname
                break

        writable_fields = set(meta.create_schema.model_fields)

        fields = []
        for field_name, field_info in meta.read_schema.model_fields.items():
            is_writable = field_name in writable_fields
            create_field = meta.create_schema.model_fields.get(field_name)

            # "required" describes what the client must supply when creating a
            # row, so it comes from the Create schema. Reading it off the Read
            # schema (as this endpoint originally did) reports every NOT NULL
            # column as required even when it has a default the client may
            # omit -- which would make the form demand a value for e.g.
            # is_active. Fall back to the Read schema for fields that aren't
            # on Create at all (e.g. the primary key).
            is_required = (
                create_field.is_required() if create_field is not None else field_info.is_required()
            )

            if is_writable:
                column_nullable = nullable_by_field.get(field_name, True)
                # NOT NULL at the DB level but still optional on create
                # means it's server-generated (server_default, e.g.
                # created_at) -- not writable by the client. Optional on
                # create because the *column* is nullable (e.g.
                # description) is genuinely writable, just not required.
                # A column with a client-side ORM default (e.g. is_active)
                # is also optional on create, but the client may absolutely
                # set it, so it stays writable.
                if (
                    not column_nullable
                    and not create_field.is_required()
                    and not has_client_default_by_field.get(field_name, False)
                ):
                    is_writable = False

            fields.append(
                {
                    "name": field_name,
                    "type": _type_label(field_info.annotation),
                    "required": is_required,
                    "writable": is_writable,
                    "write_only": False,
                    "is_fk": field_name in fk_table_by_field,
                    "fk_table": fk_table_by_field.get(field_name),
                    "default": default_by_field.get(field_name),
                    "choices": _choices_for(meta.table, field_name),
                    "label_field": field_name in DEFAULT_LABEL_COLUMNS,
                    "label": _field_label(meta.table, field_name),
                }
            )

        # Write-only fields live on Create (and maybe Update) but never on
        # Read — `password` on user_account is the one case. The form must
        # still render them; the table must not, because there is nothing
        # to show.
        for field_name, field_info in meta.create_schema.model_fields.items():
            if field_name in meta.read_schema.model_fields:
                continue
            fields.append(
                {
                    "name": field_name,
                    "type": "password" if field_name == "password" else _type_label(field_info.annotation),
                    "required": field_info.is_required(),
                    "writable": True,
                    "write_only": True,
                    "is_fk": False,
                    "fk_table": None,
                    "default": None,
                    "choices": _choices_for(meta.table, field_name),
                    "label_field": False,
                    "label": _field_label(meta.table, field_name),
                }
            )

        label, label_plural = _table_labels(meta.table)
        tables.append(
            {
                "schema": meta.schema,
                "table": meta.table,
                "label": label,
                "label_plural": label_plural,
                "fields": fields,
                "creatable": meta.creatable,
                "updatable": meta.updatable,
                "deletable": meta.deletable,
                "write_capability": meta.write_capability,
            }
        )

    return tables


@router.get("/counts")
def get_counts(
    db: Session = Depends(get_db), _: UserAccount = Depends(get_current_user)
) -> list[dict]:
    """One row count per registered table, so the dashboard can render
    every table's total from a single request instead of firing one
    request per table (A-1/A-2 from the audit)."""
    counts = []
    for meta in TABLE_REGISTRY:
        _, label_plural = _table_labels(meta.table)
        total = db.query(meta.model).count()
        counts.append(
            {
                "schema": meta.schema,
                "table": meta.table,
                "label_plural": label_plural,
                "total": total,
            }
        )
    return counts
