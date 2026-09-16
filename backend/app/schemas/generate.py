import datetime
import uuid
from typing import Any, Optional, Type

from pydantic import BaseModel, ConfigDict, create_model
from sqlalchemy import inspect

_TYPE_MAP: dict[str, type] = {
    "UUID": uuid.UUID,
    "VARCHAR": str,
    "TEXT": str,
    "INTEGER": int,
    "BIGINT": int,
    "NUMERIC": float,
    "BOOLEAN": bool,
    "DATE": datetime.date,
    "TIMESTAMP": datetime.datetime,
    "JSON": Any,
    "JSONB": Any,
}


def _python_type(column) -> type:
    type_name = column.type.__class__.__name__.upper()
    return _TYPE_MAP.get(type_name, str)


def make_crud_schemas(
    model: Type,
    *,
    name: str,
    readonly: frozenset = frozenset({"id"}),
    server_default: frozenset = frozenset(),
) -> tuple[Type[BaseModel], Type[BaseModel], Type[BaseModel]]:
    """Derive (Create, Update, Read) Pydantic schemas from a SQLAlchemy model.

    readonly: fields never accepted on create or update (e.g. primary key).
    server_default: fields optional on create because the database fills
        them in (e.g. created_at via `server_default=func.now()`).
    """
    mapper = inspect(model)
    create_fields: dict[str, tuple] = {}
    update_fields: dict[str, tuple] = {}
    read_fields: dict[str, tuple] = {}

    # Iterate column_attrs (Python attribute names), not mapper.columns (DB
    # column names) — they diverge whenever a column is aliased, which we
    # do for any column named "metadata" (reserved by SQLAlchemy's
    # DeclarativeBase). Keying on the attribute name keeps
    # `model(**payload.model_dump())` and `Read.model_validate(row)`
    # correct in both the common case and the aliased case.
    for attr in mapper.column_attrs:
        col = attr.columns[0]
        field_name = attr.key
        py_type = _python_type(col)
        optional_on_create = col.nullable or field_name in server_default

        if col.nullable:
            read_fields[field_name] = (Optional[py_type], None)
        else:
            read_fields[field_name] = (py_type, ...)

        if field_name in readonly:
            continue

        if optional_on_create:
            create_fields[field_name] = (Optional[py_type], None)
        else:
            create_fields[field_name] = (py_type, ...)

        update_fields[field_name] = (Optional[py_type], None)

    cfg = ConfigDict(from_attributes=True)
    create_schema = create_model(f"{name}Create", __config__=cfg, **create_fields)
    update_schema = create_model(f"{name}Update", __config__=cfg, **update_fields)
    read_schema = create_model(f"{name}Read", __config__=cfg, **read_fields)
    return create_schema, update_schema, read_schema
