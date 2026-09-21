"""Seeds: the default organization/admin, and the schema v1 demo domain.

`seed_admin` runs on every startup (see `app.main`). `seed_workforce_demo`
does not -- it is run deliberately, either as `python -m app.seed` or by
importing it, because it writes a whole demo dataset that nobody wants
appearing in an empty installation by surprise.

Three things about `seed_workforce_demo` are decisions, not accidents:

**It writes below the routers.** It is the first non-router writer in the
project, so migration 0009's eight integrity rules are the only thing
judging it -- non-empty `enum_values` with no NULL member, non-blank
`entity.key`, endpoint types inside the relationship type's own domain,
index types inside the parameter's own domain, a `default_value` matching
its `data_type`, and the rest. That is the point: if a realistic dataset
cannot be built under those rules, the rules are wrong, and this is where
it shows.

**Two tables are written with Core, not the ORM.**
`parameter_value`'s primary key contains an array, so `db.add()` raises
`TypeError: unhashable type: 'list'` before any SQL is emitted (Ruling
24). `model_version.version` and `ir_hash` are filled by BEFORE INSERT
triggers the ORM does not know about, so an ORM insert sends explicit
NULLs and reads both back as `None` (Ruling 25); the Core insert uses
`returning(...)` instead.

**It is idempotent by refusing to re-seed.** If the domain already
exists, nothing is written and the existing ids are returned with
`created=False`. Row-by-row get-or-create would be the other option, but
`model_version` is immutable -- "make sure a version like this exists"
has no meaning there, and a second run would either create version 2 or
have to compare `ir_hash` by hand. Skipping is the honest shape.
"""

import logging
from typing import Any

from sqlalchemy import insert, select, text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import hash_password
from app.models.iam import Organization, UserAccount
from app.models.v1_domain import (
    AttributeDef,
    Domain,
    Entity,
    EntityType,
    ParameterDef,
    ParameterValue,
    Relationship,
    RelationshipType,
)
from app.models.v1_problem import ModelVersion, Problem, Scenario

logger = logging.getLogger(__name__)

WORKFORCE_DOMAIN_NAME = "Workforce"

# mon..sun and morning..night are the canonical case for `sort_order`:
# alphabetical order is wrong for both, and `snapshot_dataset()` orders by
# `sort_order` then `key`, so getting this wrong is visible in the
# solver's input, not just on screen.
_DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
_DAY_LABELS = {
    "mon": "Monday",
    "tue": "Tuesday",
    "wed": "Wednesday",
    "thu": "Thursday",
    "fri": "Friday",
    "sat": "Saturday",
    "sun": "Sunday",
}
_SHIFTS = [
    ("morning", "Morning", "06:00", "14:00"),
    ("evening", "Evening", "14:00", "22:00"),
    ("night", "Night", "22:00", "06:00"),
]

# demand[day, shift]. The default is 1, and every cell below differs from
# it: storage is sparse by design (a cell equal to the default is deleted
# by the API and reads as "empty" in the grid), so seeding one would be
# both redundant and misleading.
_DEMAND_DEFAULT = 1
_WEEKDAY_DEMAND = {"morning": 4, "evening": 3, "night": 2}
_WEEKEND_DEMAND = {"morning": 2, "evening": 2, "night": 2}

# The unit tree `reports_to` draws. Three levels, so `entity_descendants()`
# has something to recurse through rather than a single fan-out.
_UNITS = [
    ("head_office", "Head Office", None, "HQ-000"),
    ("north_region", "North Region", "head_office", "OPS-100"),
    ("south_region", "South Region", "head_office", "OPS-200"),
    ("depot_north", "North Depot", "north_region", "OPS-110"),
    ("depot_south", "South Depot", "south_region", "OPS-210"),
    ("support", "Support Desk", "head_office", "SUP-300"),
]

_EMPLOYEES = [
    ("ahmed", "Ahmed Salah", "depot_north", {
        "full_name": "Ahmed Salah", "hours_per_week": 40, "hourly_rate": 24.5,
        "grade": "senior", "on_call": True, "hired_on": "2021-03-01",
    }),
    ("bilal", "Bilal Haddad", "depot_north", {
        "full_name": "Bilal Haddad", "hours_per_week": 32, "hourly_rate": 19.0,
        "grade": "mid", "hired_on": "2023-06-15",
    }),
    ("carla", "Carla Mendes", "depot_south", {
        "full_name": "Carla Mendes", "hours_per_week": 40, "hourly_rate": 21.75,
        "grade": "mid", "on_call": True,
    }),
    ("dina", "Dina Farouk", "depot_south", {
        "full_name": "Dina Farouk", "hours_per_week": 20, "hourly_rate": 16.0,
        "grade": "junior", "hired_on": "2025-01-20",
    }),
    ("elias", "Elias Novak", "support", {
        "full_name": "Elias Novak", "hours_per_week": 40, "hourly_rate": 28.0,
        "grade": "senior",
    }),
]

# The IR the seeded model version carries, and the one worked example in
# `docs/contracts/problem-ir.md`. It is asserted equal to the `workforce`
# case in `backend/tests/ir_fixtures.json`, so the demo and the contract
# cannot drift apart.
#
# This used to be a SKETCH: variables carried a type and an index, the
# three constraints carried an id and a prose note and nothing else, and
# the objective referenced a term id (`o_cost`) that nothing defined. It
# named a model without expressing one. Phase 0 chose to express it
# rather than to admit "declared but unexpressed" as a state a frozen,
# content-hashed, immutable `model_version` may be in -- see the contract
# document's "The decision" section. The three notes below are the ones
# the sketch carried; what changed is that each now has arithmetic under
# it that says the same thing.
#
# Two compromises are visible here and both are the integer-only decision
# (spec section 2) biting:
#
#   * `c_max_hours` multiplies by a literal 8 because a shift's length
#     lives in `starts_at`/`ends_at`, which are `time` attributes, and v1
#     arithmetic runs over integers only.
#   * the objective minimises shifts worked, not cost. The only
#     cost-bearing datum in this domain is `employee.hourly_rate`, which
#     is a `number`; admitting it as a coefficient would make the model
#     continuous, which nothing here can solve.
_IR: dict[str, Any] = {
    "version": 1,
    "sets": ["employee", "unit", "day", "shift"],
    "parameters": {"demand": {"index": ["day", "shift"]}},
    "variables": {"assign": {"index": ["employee", "day", "shift"], "domain": "binary"}},
    "constraints": [
        {
            "id": "c_cover_demand",
            "note": "each day/shift is staffed to at least demand[day, shift]",
            "forall": [{"index": "d", "set": "day"}, {"index": "s", "set": "shift"}],
            "left": {
                "sum": {"var": "assign", "index": ["e", "d", "s"]},
                "over": [{"index": "e", "set": "employee"}],
            },
            "relation": ">=",
            "right": {"par": "demand", "index": ["d", "s"]},
            "severity": "hard",
        },
        {
            "id": "c_one_shift_per_day",
            "note": "nobody works two shifts in a day",
            "forall": [{"index": "e", "set": "employee"}, {"index": "d", "set": "day"}],
            "left": {
                "sum": {"var": "assign", "index": ["e", "d", "s"]},
                "over": [{"index": "s", "set": "shift"}],
            },
            "relation": "<=",
            "right": {"const": 1},
            "severity": "hard",
        },
        {
            "id": "c_max_hours",
            "note": (
                "weekly hours stay within hours_per_week; every seeded shift is "
                "eight hours long"
            ),
            "forall": [{"index": "e", "set": "employee"}],
            "left": {
                "mul": [
                    {"const": 8},
                    {
                        "sum": {"var": "assign", "index": ["e", "d", "s"]},
                        "over": [{"index": "d", "set": "day"}, {"index": "s", "set": "shift"}],
                    },
                ]
            },
            "relation": "<=",
            "right": {"attr": {"of": "e", "name": "hours_per_week"}},
            "severity": "hard",
        },
    ],
    "objective": {
        "sense": "minimize",
        "terms": [
            {
                "id": "o_shifts_worked",
                "weight": 1,
                "expression": {
                    "sum": {"var": "assign", "index": ["e", "d", "s"]},
                    "over": [
                        {"index": "e", "set": "employee"},
                        {"index": "d", "set": "day"},
                        {"index": "s", "set": "shift"},
                    ],
                },
            }
        ],
    },
}

# The `relaxed_cover` scenario's patch. It softens `c_cover_demand`, and
# with five employees against 57 shift-slots of demand it has to: the
# demo domain is deliberately over-subscribed. `create_scenario` now
# refuses a patch naming an id the version's IR does not declare (Task
# 9's gap), so this constant is asserted against `_IR` by a test.
_SCENARIO_PATCH: dict[str, Any] = {"soften": {"c_cover_demand": 100}}


def seed_admin(db: Session) -> None:
    """Ensure a default organization and admin user exist. Idempotent."""
    settings = get_settings()

    org = db.query(Organization).filter(Organization.code == "default").first()
    if org is None:
        org = Organization(code="default", name="Default Organization")
        db.add(org)
        db.commit()
        db.refresh(org)

    admin = db.query(UserAccount).filter(UserAccount.username == settings.admin_username).first()
    if admin is None:
        admin = UserAccount(
            organization_id=org.id,
            username=settings.admin_username,
            display_name="Administrator",
            email=settings.admin_email,
            hashed_password=hash_password(settings.admin_password),
        )
        db.add(admin)
        db.commit()

    # The admin role, every time -- not only when the account is created.
    # Migration 0013 grants it to everyone who existed then; an account made
    # after that migration would otherwise be an administrator who cannot
    # administer anything, which reads as the platform being broken.
    db.execute(
        text(
            "INSERT INTO iam.user_role (id, user_id, role_id)"
            " SELECT gen_random_uuid(), :u, r.id FROM iam.role r WHERE r.code = 'admin'"
            " ON CONFLICT (user_id, role_id) DO NOTHING"
        ),
        {"u": str(admin.id)},
    )
    db.commit()


def _entity_type(db: Session, domain_id: int, name: str, role: str, colour: str) -> EntityType:
    row = EntityType(domain_id=domain_id, name=name, role=role, colour=colour)
    db.add(row)
    db.flush()
    return row


def _attribute(
    db: Session,
    entity_type: EntityType,
    name: str,
    data_type: str,
    *,
    required: bool = False,
    unit: str | None = None,
    enum_values: list[str] | None = None,
    default_value: Any = None,
) -> AttributeDef:
    row = AttributeDef(
        entity_type_id=entity_type.id,
        name=name,
        data_type=data_type,
        required=required,
        unit=unit,
        enum_values=enum_values,
        default_value=default_value,
    )
    db.add(row)
    db.flush()
    return row


def _entity(
    db: Session,
    entity_type: EntityType,
    key: str,
    label: str | None,
    sort_order: int = 0,
    attrs: dict[str, Any] | None = None,
) -> Entity:
    row = Entity(
        entity_type_id=entity_type.id,
        key=key,
        label=label,
        sort_order=sort_order,
        attrs=attrs or {},
    )
    db.add(row)
    db.flush()
    return row


def seed_workforce_demo(db: Session) -> dict[str, Any]:
    """Create the "Workforce" demo domain, or report that it is already there.

    Returns the ids of what it created (or found), plus ``created``:
    ``True`` when this call wrote the data, ``False`` when it found the
    domain already present and wrote nothing at all.
    """
    existing = db.execute(
        select(Domain).where(Domain.name == WORKFORCE_DOMAIN_NAME)
    ).scalar_one_or_none()
    if existing is not None:
        problem_id = db.execute(
            select(Problem.id).where(Problem.domain_id == existing.id).order_by(Problem.id)
        ).scalars().first()
        model_version_id = model_version_number = ir_hash = scenario_id = None
        if problem_id is not None:
            found = db.execute(
                select(ModelVersion.id, ModelVersion.version, ModelVersion.ir_hash)
                .where(ModelVersion.problem_id == problem_id)
                .order_by(ModelVersion.version)
            ).first()
            if found is not None:
                model_version_id, model_version_number, ir_hash = found
            scenario_id = db.execute(
                select(Scenario.id)
                .where(Scenario.problem_id == problem_id)
                .order_by(Scenario.id)
            ).scalars().first()
        logger.info("Workforce demo already seeded (domain %s); nothing written", existing.id)
        return {
            "created": False,
            "domain_id": existing.id,
            "problem_id": problem_id,
            "model_version_id": model_version_id,
            "model_version_number": model_version_number,
            "ir_hash": ir_hash,
            "scenario_id": scenario_id,
        }

    domain = Domain(name=WORKFORCE_DOMAIN_NAME)
    db.add(domain)
    db.flush()

    # -- entity types, coloured so the graph's types view shows something --
    employee = _entity_type(db, domain.id, "employee", "agent", "#2563eb")
    unit = _entity_type(db, domain.id, "unit", "org", "#7c3aed")
    day = _entity_type(db, domain.id, "day", "time", "#0d9488")
    shift = _entity_type(db, domain.id, "shift", "time", "#d97706")

    # -- attribute definitions: every attr_type is represented ------------
    # integer, number, text, boolean and enum on `employee`; date there
    # too; `time` on `shift`. Spec §6 asks for full coverage of the enum,
    # and `test_seed_covers_every_attr_type` reads the enum from the
    # database rather than from a list here, so a new label fails.
    _attribute(db, employee, "full_name", "text", required=True)
    _attribute(db, employee, "hours_per_week", "integer", unit="h/week", default_value=40)
    _attribute(db, employee, "hourly_rate", "number", unit="EUR/h", default_value=20.0)
    _attribute(db, employee, "on_call", "boolean", default_value=False)
    _attribute(
        db,
        employee,
        "grade",
        "enum",
        enum_values=["junior", "mid", "senior"],
        default_value="mid",
    )
    _attribute(db, employee, "hired_on", "date")
    _attribute(db, unit, "cost_centre", "text")
    _attribute(db, shift, "starts_at", "time", required=True)
    _attribute(db, shift, "ends_at", "time", required=True)
    _attribute(db, day, "is_weekend", "boolean", default_value=False)

    # -- entities ---------------------------------------------------------
    units = {
        key: _entity(db, unit, key, label, index, {"cost_centre": cost_centre})
        for index, (key, label, _parent, cost_centre) in enumerate(_UNITS)
    }
    days = {
        key: _entity(
            db, day, key, _DAY_LABELS[key], index, {"is_weekend": key in ("sat", "sun")}
        )
        for index, key in enumerate(_DAYS)
    }
    shifts = {
        key: _entity(db, shift, key, label, index, {"starts_at": starts, "ends_at": ends})
        for index, (key, label, starts, ends) in enumerate(_SHIFTS)
    }
    employees = {
        key: _entity(db, employee, key, label, index, attrs)
        for index, (key, label, _unit_key, attrs) in enumerate(_EMPLOYEES)
    }

    # -- relationship types -----------------------------------------------
    # A hierarchy reads "from is the PARENT of to", which is why
    # `reports_to` points from the parent unit down. The DDL requires
    # from_type = to_type and one_to_many for any is_hierarchy type.
    reports_to = RelationshipType(
        domain_id=domain.id,
        name="reports_to",
        from_type_id=unit.id,
        to_type_id=unit.id,
        cardinality="one_to_many",
        is_hierarchy=True,
        colour="#475569",
    )
    # many_to_one: an employee works in at most one unit, a unit holds many.
    works_in = RelationshipType(
        domain_id=domain.id,
        name="works_in",
        from_type_id=employee.id,
        to_type_id=unit.id,
        cardinality="many_to_one",
        is_hierarchy=False,
        colour="#16a34a",
    )
    db.add_all([reports_to, works_in])
    db.flush()

    for key, _label, parent_key, _cost_centre in _UNITS:
        if parent_key is not None:
            db.add(
                Relationship(
                    relationship_type_id=reports_to.id,
                    from_entity_id=units[parent_key].id,
                    to_entity_id=units[key].id,
                )
            )
    for key, _label, unit_key, _attrs in _EMPLOYEES:
        db.add(
            Relationship(
                relationship_type_id=works_in.id,
                from_entity_id=employees[key].id,
                to_entity_id=units[unit_key].id,
            )
        )
    db.flush()

    # -- demand[day, shift] ------------------------------------------------
    demand = ParameterDef(
        domain_id=domain.id,
        name="demand",
        index_type_ids=[day.id, shift.id],
        default_value=_DEMAND_DEFAULT,
        unit="people",
    )
    db.add(demand)
    db.flush()

    # Ruling 24: Core, not db.add() -- the primary key contains an array.
    cells = [
        {
            "parameter_def_id": demand.id,
            "entity_ids": [days[day_key].id, shifts[shift_key].id],
            "value": value,
        }
        for day_key in _DAYS
        for shift_key, value in (
            _WEEKEND_DEMAND if day_key in ("sat", "sun") else _WEEKDAY_DEMAND
        ).items()
    ]
    db.execute(insert(ParameterValue), cells)

    # -- problem, model version, scenario ---------------------------------
    problem = Problem(domain_id=domain.id, name="weekly_rota", owner="demo")
    db.add(problem)
    db.flush()

    # Ruling 25: `version` and `ir_hash` come from BEFORE INSERT triggers,
    # so they are read back with RETURNING rather than set here.
    model_version_id, version, ir_hash = db.execute(
        insert(ModelVersion)
        .values(problem_id=problem.id, ir=_IR, note="Seeded demo model")
        .returning(ModelVersion.id, ModelVersion.version, ModelVersion.ir_hash)
    ).one()

    scenario = Scenario(
        problem_id=problem.id,
        model_version_id=model_version_id,
        name="relaxed_cover",
        patch=_SCENARIO_PATCH,
    )
    db.add(scenario)
    db.flush()

    db.commit()
    logger.info(
        "Seeded the Workforce demo: domain %s, problem %s, model version %s (v%s, %s)",
        domain.id,
        problem.id,
        model_version_id,
        version,
        ir_hash[:12],
    )
    return {
        "created": True,
        "domain_id": domain.id,
        "problem_id": problem.id,
        "model_version_id": model_version_id,
        # Reported because they are the evidence for Ruling 25: an ORM
        # insert would still create the row, but both of these would come
        # back `None` while the database held the real values.
        "model_version_number": version,
        "ir_hash": ir_hash,
        "scenario_id": scenario.id,
        "entity_type_ids": {
            "employee": employee.id,
            "unit": unit.id,
            "day": day.id,
            "shift": shift.id,
        },
        "relationship_type_ids": {"reports_to": reports_to.id, "works_in": works_in.id},
        "parameter_def_ids": {"demand": demand.id},
    }


def main() -> None:  # pragma: no cover -- CLI entry point
    """`python -m app.seed`: admin account, then the Workforce demo."""
    from app.core.db import SessionLocal

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    db = SessionLocal()
    try:
        seed_admin(db)
        result = seed_workforce_demo(db)
        if result["created"]:
            print(f"Seeded the Workforce demo (domain {result['domain_id']}).")
        else:
            print(
                f"Workforce demo already present (domain {result['domain_id']}); "
                "nothing was written."
            )
    finally:
        db.close()


if __name__ == "__main__":  # pragma: no cover
    main()
