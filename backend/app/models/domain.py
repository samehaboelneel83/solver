import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Numeric, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.base import UUIDPKMixin


class EntityType(UUIDPKMixin, Base):
    __tablename__ = "entity_type"
    __table_args__ = {"schema": "domain"}

    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("iam.organization.id"), nullable=True
    )
    code: Mapped[str] = mapped_column(String(100), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(String, nullable=True)
    parent_type_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("domain.entity_type.id"), nullable=True
    )
    is_abstract: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Entity(UUIDPKMixin, Base):
    __tablename__ = "entity"
    __table_args__ = {"schema": "domain"}

    organization_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("iam.organization.id"), nullable=False
    )
    entity_type_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("domain.entity_type.id"), nullable=False
    )
    code: Mapped[str | None] = mapped_column(String(150), nullable=True)
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    description: Mapped[str | None] = mapped_column(String, nullable=True)
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str | None] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AttributeDefinition(UUIDPKMixin, Base):
    __tablename__ = "attribute_definition"
    __table_args__ = {"schema": "domain"}

    entity_type_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("domain.entity_type.id"), nullable=False
    )
    code: Mapped[str] = mapped_column(String(100), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    data_type: Mapped[str] = mapped_column(String(50), nullable=False)
    is_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_multi_value: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    default_value: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    validation_rule: Mapped[dict | None] = mapped_column(JSONB, nullable=True)


class EntityAttribute(UUIDPKMixin, Base):
    __tablename__ = "entity_attribute"
    __table_args__ = {"schema": "domain"}

    entity_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("domain.entity.id"), nullable=False
    )
    attribute_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("domain.attribute_definition.id"), nullable=False
    )
    value_string: Mapped[str | None] = mapped_column(String, nullable=True)
    value_number: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    value_boolean: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    value_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    value_datetime: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    value_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)


class RelationshipType(UUIDPKMixin, Base):
    __tablename__ = "relationship_type"
    __table_args__ = {"schema": "domain"}

    code: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    source_entity_type: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("domain.entity_type.id"), nullable=True
    )
    target_entity_type: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("domain.entity_type.id"), nullable=True
    )
    cardinality: Mapped[str | None] = mapped_column(String(30), nullable=True)
    is_directed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSONB, nullable=True)


class Relationship(UUIDPKMixin, Base):
    __tablename__ = "relationship"
    __table_args__ = {"schema": "domain"}

    relationship_type_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("domain.relationship_type.id"), nullable=False
    )
    source_entity_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("domain.entity.id"), nullable=False
    )
    target_entity_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("domain.entity.id"), nullable=False
    )
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    attributes: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
