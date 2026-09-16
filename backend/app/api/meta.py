import datetime
import typing
import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import inspect

from app.api.deps import get_current_user
from app.crud.registry import TABLE_REGISTRY
from app.models.iam import UserAccount

router = APIRouter(prefix="/api/meta", tags=["meta"])

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
        for attr in mapper.column_attrs:
            column = attr.columns[0]
            for fk in column.foreign_keys:
                fk_table_by_field[attr.key] = fk.column.table.fullname
                break

        writable_fields = set(meta.create_schema.model_fields)

        fields = []
        for field_name, field_info in meta.read_schema.model_fields.items():
            fields.append(
                {
                    "name": field_name,
                    "type": _type_label(field_info.annotation),
                    "required": field_info.is_required(),
                    "writable": field_name in writable_fields,
                    "is_fk": field_name in fk_table_by_field,
                    "fk_table": fk_table_by_field.get(field_name),
                }
            )

        tables.append({"schema": meta.schema, "table": meta.table, "fields": fields})

    return tables
