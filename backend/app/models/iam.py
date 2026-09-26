import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.base import UUIDPKMixin


class Organization(UUIDPKMixin, Base):
    __tablename__ = "organization"
    __table_args__ = {"schema": "iam"}

    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("iam.organization.id"), nullable=True
    )
    code: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(String, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Migration 0032: an operator organization may change what every
    # organization shares -- roles, capabilities, setting keys, templates,
    # platform settings -- and manage other organizations' people.
    is_operator: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # Migration 0023 -- the generic form sends every filled field.
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.clock_timestamp()
    )


class UserAccount(UUIDPKMixin, Base):
    __tablename__ = "user_account"
    __table_args__ = {"schema": "iam"}

    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("iam.organization.id"), nullable=True
    )
    username: Mapped[str] = mapped_column(String(150), nullable=False, unique=True)
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Migration 0079 — OIDC subject and JWT revoke counter (R35/R36).
    external_sub: Mapped[str | None] = mapped_column(String, nullable=True)
    token_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # Migration 0023 -- see Organization.updated_at.
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.clock_timestamp()
    )


class Role(UUIDPKMixin, Base):
    __tablename__ = "role"
    __table_args__ = {"schema": "iam"}

    code: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    # Migration 0023 -- see Organization.updated_at.
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.clock_timestamp()
    )


class UserRole(UUIDPKMixin, Base):
    __tablename__ = "user_role"
    __table_args__ = {"schema": "iam"}

    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("iam.user_account.id"), nullable=False
    )
    role_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("iam.role.id"), nullable=False
    )
    # Migration 0023 -- see Organization.updated_at.
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.clock_timestamp()
    )


class Capability(Base):
    """A verb the platform can grant. Rows are seeded (0013); the factory
    exposes them read-only so a grant form is not the only place the
    catalogue can be read."""

    __tablename__ = "capability"
    __table_args__ = {"schema": "iam"}

    code: Mapped[str] = mapped_column(String(100), primary_key=True)
    group: Mapped[str] = mapped_column("group", String(50), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)


class RoleCapability(UUIDPKMixin, Base):
    """A grant: this role may do this capability.

    The pair is unique (migration 0026). `capability_code` is a foreign
    key to `iam.capability`; the grant form is the same picker as any
    other reference.
    """

    __tablename__ = "role_capability"
    __table_args__ = {"schema": "iam"}

    role_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("iam.role.id"), nullable=False
    )
    capability_code: Mapped[str] = mapped_column(
        String(100), ForeignKey("iam.capability.code"), nullable=False
    )
    # Migration 0026 -- same trigger as the other factory tables.
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.clock_timestamp()
    )
