"""Schema v1 -- DOMAIN half.

Mirrors the eight tables created by migration `0006_schema_v1_domain`:
domain, entity_type, attribute_def, entity, relationship_type,
relationship, parameter_def, parameter_value.

Everything lives in the `public` schema (only the four `iam` tables keep a
schema qualifier) and every surrogate key is
`bigint GENERATED ALWAYS AS IDENTITY` -- there are no UUIDs in v1.

The tables, their CHECK constraints and their validation triggers are
created by raw DDL in the migration, not by `Base.metadata.create_all`.
These classes exist so application code can query them through the ORM;
the two enums are therefore declared with `create_type=False`, since the
migration already created them.
"""

from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    ARRAY,
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Identity,
    Integer,
    PrimaryKeyConstraint,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ENUM, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

# Created by the migration; `create_type=False` keeps SQLAlchemy from
# trying to emit CREATE TYPE again.
ENTITY_ROLE = ENUM(
    "agent",
    "resource",
    "time",
    "location",
    "task",
    "org",
    "other",
    name="entity_role",
    create_type=False,
)

ATTR_TYPE = ENUM(
    "integer",
    "number",
    "text",
    "boolean",
    "enum",
    "time",
    "date",
    name="attr_type",
    create_type=False,
)


class Domain(Base):
    __tablename__ = "domain"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class EntityType(Base):
    __tablename__ = "entity_type"
    __table_args__ = (
        UniqueConstraint("domain_id", "name"),
        # Migration 0009: redundant as a key (id is the primary key), but it
        # is what relationship_type's same-domain composite FKs reference.
        UniqueConstraint("id", "domain_id", name="entity_type_id_domain_id_key"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    domain_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("domain.id", ondelete="CASCADE"), nullable=False
    )
    # Used verbatim in IR expressions, hence the ^[a-z][a-z0-9_]*$ CHECK in the DDL.
    name: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = mapped_column(ENTITY_ROLE, nullable=False, server_default="other")
    # Migration 0009: lowercase '#rrggbb' (CHECK entity_type_colour_hex);
    # NULL means "not chosen", and the UI assigns a fallback.
    colour: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Migration 0010. Maintained by the `entity_type_set_updated_at`
    # trigger, never by this application: `server_default` plus
    # `server_onupdate` would only describe what the database does, and
    # the ORM must re-read it rather than predict it, which is why every
    # write path calls `db.refresh()` already.
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.clock_timestamp()
    )


class AttributeDef(Base):
    __tablename__ = "attribute_def"
    __table_args__ = (UniqueConstraint("entity_type_id", "name"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    entity_type_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("entity_type.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    data_type: Mapped[str] = mapped_column(ATTR_TYPE, nullable=False)
    required: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    unit: Mapped[str | None] = mapped_column(Text, nullable=True)
    # NOT NULL exactly when data_type = 'enum' (CHECK in the DDL).
    enum_values: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True)
    # none_as_null=True is load-bearing, not tidiness. SQLAlchemy's JSONB
    # persists an explicit Python None as jsonb 'null', which is NOT NULL --
    # and `entity_validate` materialises a default whenever
    # `default_value IS NOT NULL`. Without this, every attribute_def created
    # through the API (the router passes `**model_dump()`, so the key is
    # always present and explicitly None) would carry a jsonb 'null'
    # default, and every entity of that type would get `{"<attr>": null}`
    # materialised into `attrs` -- which then flows into the solver's data
    # contract via snapshot_dataset()'s `jsonb_build_object('id', e.key) ||
    # e.attrs`. "No default" has to be expressible through the API.
    default_value: Mapped[Any | None] = mapped_column(JSONB(none_as_null=True), nullable=True)


class Entity(Base):
    __tablename__ = "entity"
    __table_args__ = (UniqueConstraint("entity_type_id", "key"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    entity_type_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("entity_type.id", ondelete="CASCADE"), nullable=False
    )
    # Stable human id: 'ahmed', 'mon'.
    key: Mapped[str] = mapped_column(Text, nullable=False)
    label: Mapped[str | None] = mapped_column(Text, nullable=True)
    # mon..sun, morning..night
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    # Validated against attribute_def by the `entity_validate` trigger, which
    # also materialises attribute_def.default_value into this object on write.
    attrs: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    # Migration 0010 -- see EntityType.updated_at.
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.clock_timestamp()
    )


class RelationshipType(Base):
    __tablename__ = "relationship_type"
    __table_args__ = (
        UniqueConstraint("domain_id", "name"),
        # Migration 0009, rule 3: both endpoint types belong to this
        # relationship type's own domain.
        ForeignKeyConstraint(
            ["from_type_id", "domain_id"],
            ["entity_type.id", "entity_type.domain_id"],
            name="relationship_type_from_type_same_domain_fkey",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["to_type_id", "domain_id"],
            ["entity_type.id", "entity_type.domain_id"],
            name="relationship_type_to_type_same_domain_fkey",
            ondelete="CASCADE",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    domain_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("domain.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    from_type_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("entity_type.id", ondelete="CASCADE"), nullable=False
    )
    to_type_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("entity_type.id", ondelete="CASCADE"), nullable=False
    )
    # one_to_one | one_to_many | many_to_one | many_to_many (CHECK in the DDL).
    cardinality: Mapped[str] = mapped_column(
        Text, nullable=False, server_default="many_to_many"
    )
    # A hierarchy reads as: from_entity is the PARENT of to_entity. Requires
    # from_type_id = to_type_id and cardinality = 'one_to_many'.
    is_hierarchy: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    # Migration 0009: lowercase '#rrggbb' (CHECK relationship_type_colour_hex);
    # NULL means "not chosen", and the UI assigns a fallback.
    colour: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Migration 0010 -- see EntityType.updated_at.
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.clock_timestamp()
    )


class Relationship(Base):
    __tablename__ = "relationship"
    __table_args__ = (
        UniqueConstraint("relationship_type_id", "from_entity_id", "to_entity_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    relationship_type_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("relationship_type.id", ondelete="CASCADE"), nullable=False
    )
    from_entity_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("entity.id", ondelete="CASCADE"), nullable=False
    )
    to_entity_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("entity.id", ondelete="CASCADE"), nullable=False
    )
    attrs: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    valid_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    valid_to: Mapped[date | None] = mapped_column(Date, nullable=True)


class ParameterDef(Base):
    __tablename__ = "parameter_def"
    __table_args__ = (UniqueConstraint("domain_id", "name"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    domain_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("domain.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    # entity_type ids, in index order: demand[day, shift, location].
    index_type_ids: Mapped[list[int]] = mapped_column(ARRAY(BigInteger), nullable=False)
    default_value: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    unit: Mapped[str | None] = mapped_column(Text, nullable=True)


class ParameterValue(Base):
    __tablename__ = "parameter_value"
    __table_args__ = (PrimaryKeyConstraint("parameter_def_id", "entity_ids"),)

    parameter_def_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("parameter_def.id", ondelete="CASCADE"), nullable=False
    )
    # Same order as parameter_def.index_type_ids. Arrays cannot carry foreign
    # keys, so the `parameter_value_validate` trigger checks them instead, and
    # `parameter_value_cleanup` deletes rows whose entities are deleted.
    entity_ids: Mapped[list[int]] = mapped_column(ARRAY(BigInteger), nullable=False)
    value: Mapped[int] = mapped_column(Integer, nullable=False)


__all__ = [
    "ATTR_TYPE",
    "ENTITY_ROLE",
    "AttributeDef",
    "Domain",
    "Entity",
    "EntityType",
    "ParameterDef",
    "ParameterValue",
    "Relationship",
    "RelationshipType",
]
