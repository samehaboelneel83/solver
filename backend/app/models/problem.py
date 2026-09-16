import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.base import UUIDPKMixin


class Problem(UUIDPKMixin, Base):
    __tablename__ = "problem"
    __table_args__ = {"schema": "problem"}

    organization_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("iam.organization.id"), nullable=False
    )
    code: Mapped[str] = mapped_column(String(100), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(String, nullable=True)
    problem_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="DRAFT")
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("iam.user_account.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Scenario(UUIDPKMixin, Base):
    __tablename__ = "scenario"
    __table_args__ = {"schema": "problem"}

    problem_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("problem.problem.id"), nullable=False
    )
    code: Mapped[str] = mapped_column(String(100), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(String, nullable=True)
    parent_scenario_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("problem.scenario.id"), nullable=True
    )
    parameters: Mapped[dict | None] = mapped_column(JSONB, nullable=True)


class VariableDefinition(UUIDPKMixin, Base):
    __tablename__ = "variable_definition"
    __table_args__ = {"schema": "problem"}

    problem_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("problem.problem.id"), nullable=False
    )
    code: Mapped[str] = mapped_column(String(150), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    variable_type: Mapped[str] = mapped_column(String(50), nullable=False)
    description: Mapped[str | None] = mapped_column(String, nullable=True)
    domain_definition: Mapped[dict | None] = mapped_column(JSONB, nullable=True)


class VariableDimension(UUIDPKMixin, Base):
    __tablename__ = "variable_dimension"
    __table_args__ = {"schema": "problem"}

    variable_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("problem.variable_definition.id"), nullable=False
    )
    dimension_order: Mapped[int] = mapped_column(Integer, nullable=False)
    dimension_type: Mapped[str] = mapped_column(String(50), nullable=False)
    domain_source: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
