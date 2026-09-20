from dataclasses import dataclass
from typing import Type

from pydantic import BaseModel


@dataclass
class TableMeta:
    schema: str
    table: str
    model: Type
    create_schema: Type[BaseModel]
    read_schema: Type[BaseModel]
    creatable: bool = True
    updatable: bool = True
    deletable: bool = True


TABLE_REGISTRY: list[TableMeta] = []


def register_table(
    schema: str,
    table: str,
    model: Type,
    create_schema: Type[BaseModel],
    read_schema: Type[BaseModel],
    creatable: bool = True,
    updatable: bool = True,
    deletable: bool = True,
) -> None:
    TABLE_REGISTRY.append(
        TableMeta(
            schema=schema,
            table=table,
            model=model,
            create_schema=create_schema,
            read_schema=read_schema,
            creatable=creatable,
            updatable=updatable,
            deletable=deletable,
        )
    )
