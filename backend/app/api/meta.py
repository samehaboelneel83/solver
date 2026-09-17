import datetime
import typing
import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import inspect

from app.api.deps import get_current_user
from app.crud.labels import DEFAULT_LABEL_COLUMNS
from app.crud.registry import TABLE_REGISTRY
from app.models.iam import UserAccount

router = APIRouter(prefix="/api/meta", tags=["meta"])

# Curated free-text "type" choices, keyed by (table, field) with a
# (None, field) fallback shared across tables that use the same field
# name (e.g. every `status` column). Hints only -- the CRUD routes still
# accept any value.
CHOICES: dict[tuple[str | None, str], list[str]] = {
    (None, "status"): ["DRAFT", "ACTIVE", "ARCHIVED"],
    (None, "severity"): ["error", "warning", "info"],
    (None, "objective_type"): ["minimize", "maximize"],
    (None, "variable_type"): ["binary", "integer", "continuous"],
    (None, "dimension_type"): ["entity", "time", "set"],
    (None, "cardinality"): ["one_to_one", "one_to_many", "many_to_many"],
    (None, "problem_type"): ["scheduling", "assignment", "routing", "other"],
    (None, "data_type"): ["string", "number", "boolean", "date", "datetime", "json"],
    ("attribute_definition", "data_type"): [
        "string",
        "number",
        "boolean",
        "date",
        "datetime",
        "json",
    ],
}


def _choices_for(table: str, field: str) -> list[str] | None:
    return CHOICES.get((table, field)) or CHOICES.get((None, field))


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
                    "is_fk": field_name in fk_table_by_field,
                    "fk_table": fk_table_by_field.get(field_name),
                    "default": default_by_field.get(field_name),
                    "choices": _choices_for(meta.table, field_name),
                    "label_field": field_name in DEFAULT_LABEL_COLUMNS,
                }
            )

        tables.append({"schema": meta.schema, "table": meta.table, "fields": fields})

    return tables
