"""Schema v1 -- PROBLEM + RUN halves.

Mirrors the eight tables created by migration
`0007_schema_v1_problem_run`: template, problem, model_version, scenario,
dataset, run, solution, constraint_result.

Everything lives in the `public` schema (only the four `iam` tables keep a
schema qualifier) and every surrogate key is
`bigint GENERATED ALWAYS AS IDENTITY` -- there are no UUIDs in v1.
`solution` and `constraint_result` carry no surrogate at all: they key off
`run_id`, because a run has at most one solution and at most one result per
constraint.

The tables, their CHECK constraints, their triggers, `snapshot_dataset()`
and the `run_overview` view are created by raw DDL in the migration, not by
`Base.metadata.create_all`. These classes exist so application code can
query them through the ORM; `run_status` is declared with
`create_type=False`, since the migration already created it.

Three columns are populated by BEFORE INSERT triggers rather than by the
caller, and are therefore not to be set from Python:
`model_version.version` (by `next_model_version()`),
`model_version.ir_hash` and `dataset.data_hash` (both by `set_hash()`).
"""

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Identity,
    Integer,
    Numeric,
    PrimaryKeyConstraint,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ENUM, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.ir.contract import IR_VERSION

# Rows in these four tables are frozen by the `forbid_update()` trigger:
# any UPDATE raises. The API layer reads this to withhold PUT/PATCH rather
# than render an edit form the database will reject (spec §4), and Task 4
# asserts that none of them appears in the generic CRUD TABLE_REGISTRY.
IMMUTABLE_TABLES = {"model_version", "dataset", "solution", "constraint_result"}

# Created by the migration; `create_type=False` keeps SQLAlchemy from
# trying to emit CREATE TYPE again.
RUN_STATUS = ENUM(
    "queued",
    "running",
    "optimal",
    "feasible",
    "infeasible",
    "unknown",
    "error",
    "cancelled",
    name="run_status",
    create_type=False,
)


class Template(Base):
    """Seed data: the types and parameters to create, plus a starting IR."""

    __tablename__ = "template"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    ir_version: Mapped[str] = mapped_column(Text, nullable=False, default=str(IR_VERSION))
    domain_seed: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )
    default_ir: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    # Migration 0023 -- the generic form sends every filled field.
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.clock_timestamp()
    )


class Problem(Base):
    __tablename__ = "problem"
    __table_args__ = (UniqueConstraint("domain_id", "name"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    domain_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("domain.id", ondelete="CASCADE"), nullable=False
    )
    template_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("template.id"), nullable=True
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    owner: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    # Migration 0023 -- the generic form sends every filled field.
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.clock_timestamp()
    )


class ModelVersion(Base):
    """Immutable. Editing a model means inserting the next version.

    `version` and `ir_hash` are both filled by BEFORE INSERT triggers;
    leave them unset on insert and read them back afterwards.
    """

    __tablename__ = "model_version"
    __table_args__ = (
        UniqueConstraint("problem_id", "version"),
        # Migration 0009: what scenario_version_same_problem_fkey references.
        UniqueConstraint("id", "problem_id", name="model_version_id_problem_id_key"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    problem_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("problem.id", ondelete="CASCADE"), nullable=False
    )
    # Assigned by next_model_version(): 1 for a problem's first version,
    # then +1, numbered independently per problem.
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    ir: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    # sha256 of ir::text, set by set_hash(). jsonb normalises key order, so
    # two IRs written with the same content hash identically.
    ir_hash: Mapped[str] = mapped_column(Text, nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Scenario(Base):
    """A what-if: a patch over one model version.

    `patch` matches ProblemIR.patched():
    {"disable": ["c_x"], "harden": ["c_y"], "soften": {"c_z": 100}}
    """

    __tablename__ = "scenario"
    __table_args__ = (
        UniqueConstraint("problem_id", "name"),
        # Migration 0009, rule 7: the version belongs to this scenario's
        # own problem.
        ForeignKeyConstraint(
            ["model_version_id", "problem_id"],
            ["model_version.id", "model_version.problem_id"],
            name="scenario_version_same_problem_fkey",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    problem_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("problem.id", ondelete="CASCADE"), nullable=False
    )
    model_version_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("model_version.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    patch: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Dataset(Base):
    """Immutable frozen copy of the domain data, in the JSON shape the
    solver's data loader reads. Produced by `snapshot_dataset()`; identical
    snapshots are shared, which is what UNIQUE (problem_id, data_hash)
    enforces. `data_hash` is set by set_hash()."""

    __tablename__ = "dataset"
    __table_args__ = (UniqueConstraint("problem_id", "data_hash"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    problem_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("problem.id", ondelete="CASCADE"), nullable=False
    )
    data: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    data_hash: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Run(Base):
    """One solve. Mutable: the worker advances `status` and fills in the
    result columns. It reads `dataset_id`, never the live domain tables,
    which is what makes a run reproducible."""

    __tablename__ = "run"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    scenario_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("scenario.id", ondelete="CASCADE"), nullable=False
    )
    dataset_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("dataset.id"), nullable=False
    )
    status: Mapped[str] = mapped_column(RUN_STATUS, nullable=False, server_default="queued")
    solver: Mapped[str] = mapped_column(Text, nullable=False, server_default="cp-sat")
    solver_version: Mapped[str | None] = mapped_column(Text, nullable=True)
    compiler_version: Mapped[str | None] = mapped_column(Text, nullable=True)
    # time_limit, workers...
    params: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    seed: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    # bigint, not int: CP-SAT objectives scale past 2^31.
    # numeric(15, 6) since migration 0015: a linear program's optimum is
    # fractional almost always, and a bigint would round the answer.
    objective: Mapped[Decimal | None] = mapped_column(Numeric(15, 6), nullable=True)
    # Migration 0028: what an answer may claim -- global, local or none.
    optimality: Mapped[str | None] = mapped_column(Text, nullable=True)
    wall_time_s: Mapped[float | None] = mapped_column(Float, nullable=True)
    # infeasible: [{"constraint_id": "...", "instance": [...]}]
    conflict: Mapped[Any | None] = mapped_column(JSONB, nullable=True)
    conflict_minimal: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    queued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Touched while the worker is actually solving. Reclaim looks at this,
    # not at started_at, so a slow run is not stolen from a live worker.
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Set by POST /runs/{id}/cancel. A queued run is cancelled immediately;
    # a running one is asked to stop, and the worker records `cancelled`.
    cancel_requested: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")


class Solution(Base):
    """Immutable. Keyed by `run_id`: a run has at most one solution.

    `assignments` is {"assign": [["ahmed","mon","morning","hq"], ...]}.
    """

    __tablename__ = "solution"

    run_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("run.id", ondelete="CASCADE"), primary_key=True
    )
    assignments: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    # Reduced costs from a linear solver, grouped like the roster.
    # Null when the backend has none or the run predates migration 0020.
    reduced_costs: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)


class ConstraintResult(Base):
    """Immutable. Normalized on purpose: this is what you query ACROSS runs,
    which is also why `constraint_result_violated_idx` is partial on
    NOT satisfied."""

    __tablename__ = "constraint_result"
    __table_args__ = (PrimaryKeyConstraint("run_id", "constraint_id"),)

    run_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("run.id", ondelete="CASCADE"), nullable=False
    )
    constraint_id: Mapped[str] = mapped_column(Text, nullable=False)
    label: Mapped[str] = mapped_column(Text, nullable=False)
    hard: Mapped[bool] = mapped_column(Boolean, nullable=False)
    satisfied: Mapped[bool] = mapped_column(Boolean, nullable=False)
    # Likewise: a rule in a continuous model can be short by half a unit.
    total_violation: Mapped[Decimal] = mapped_column(
        Numeric(15, 6), nullable=False, server_default="0"
    )
    penalty_paid: Mapped[Decimal] = mapped_column(
        Numeric(15, 6), nullable=False, server_default="0"
    )
    # [{"instance": [...], "amount": 1}]
    violations: Mapped[Any] = mapped_column(JSONB, nullable=False, server_default="[]")
    # Residual at the recorded assignment: 0 means the rule has no room left.
    # Nullable because a run made before migration 0017 has none to report.
    slack: Mapped[Decimal | None] = mapped_column(Numeric(15, 6), nullable=True)
    # Shadow price from a linear solver. Null when the backend has none
    # (CP-SAT, mixed-integer search) or the run predates migration 0019.
    dual: Mapped[Decimal | None] = mapped_column(Numeric(15, 6), nullable=True)


__all__ = [
    "IMMUTABLE_TABLES",
    "RUN_STATUS",
    "ConstraintResult",
    "Dataset",
    "ModelVersion",
    "Problem",
    "Run",
    "Scenario",
    "Solution",
    "Template",
]
