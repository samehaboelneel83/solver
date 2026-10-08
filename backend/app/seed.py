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

import json
import logging
import re
from typing import Any

from sqlalchemy import func, insert, select, text, update
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
    Relationship,
    RelationshipType,
)
from app.models.v1_problem import ModelVersion, Problem, Scenario, Template

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

# Where each site stands (a GeoJSON Point, lon/lat): the demo's one
# `geometry` attribute, so the seed exercises every attribute type. The
# support desk has no site of its own -- a geometry is optional.
_UNIT_SITES = {
    "head_office": [31.2357, 30.0444],
    "north_region": [31.2400, 30.1200],
    "south_region": [31.2300, 29.9600],
    "depot_north": [31.2800, 30.1500],
    "depot_south": [31.2100, 29.9300],
}

_EMPLOYEES = [
    ("ahmed", "Ahmed Salah", "depot_north", {
        "full_name": "Ahmed Salah", "hours_per_week": 40, "hourly_rate": 24.5,
        "grade": "senior", "on_call": True, "hired_on": "2021-03-01",
    }),
    ("bilal", "Bilal Haddad", "depot_north", {
        "full_name": "Bilal Haddad", "hours_per_week": 32, "hourly_rate": 19.0,
        "grade": "mid", "hired_on": "2023-06-15", "mentor": "ahmed",
    }),
    ("carla", "Carla Mendes", "depot_south", {
        "full_name": "Carla Mendes", "hours_per_week": 40, "hourly_rate": 21.75,
        "grade": "mid", "on_call": True,
    }),
    ("dina", "Dina Farouk", "depot_south", {
        "full_name": "Dina Farouk", "hours_per_week": 20, "hourly_rate": 16.0,
        "grade": "junior", "hired_on": "2025-01-20", "mentor": "carla",
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
# One compromise is still visible, and it is not the one that used to be
# here. `c_max_hours` multiplies by a literal 8 because a shift's length
# lives in `starts_at`/`ends_at`, which are `time` attributes -- not
# numbers, in any version -- so the arithmetic cannot subtract one from
# the other.
#
# The other compromise has gone. The objective minimised shifts worked
# rather than cost because the only cost-bearing datum here is
# `employee.hourly_rate`, a `number`, and admitting it would have made
# the model continuous with nothing able to solve one. Migration 0015 and
# GLOP changed both halves of that. It still minimises shifts, because
# changing what the demo optimises is a separate decision from making it
# possible -- but it is now a choice rather than a limit.
_IR: dict[str, Any] = {
    "version": 1,
    "sets": ["employee", "unit", "day", "shift"],
    "relationships": ["reports_to", "works_in"],
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
        {
            "id": "c_north_region_lates",
            "note": (
                "North Region puts three people on the late shift every day, "
                "counting the depots under it"
            ),
            # The traversal decision note lists this as the first thing a
            # planner says that v1 could not express, and it is the case
            # that needs a walk rather than a filter: NOBODY works in
            # North Region itself. Every one of its people is in the depot
            # beneath it, so a constraint written over the unit alone
            # counts zero and is unsatisfiable for a reason that is
            # nothing to do with the roster.
            #
            # Two walks compose. `reports_to` at `any_or_self` depth
            # gathers North Region and everything under it; `works_in`
            # then gathers the people in each of those. The set is named
            # by its cost centre rather than its key because a `where`
            # filter reads attributes, which is the same vocabulary the
            # entity screens filter with.
            "forall": [
                {"index": "d", "set": "day"},
                {
                    "index": "r",
                    "set": "unit",
                    "where": [{"attr": "cost_centre", "op": "=", "value": "OPS-100"}],
                },
                {
                    "index": "late",
                    "set": "shift",
                    "where": [{"attr": "starts_at", "op": "=", "value": "14:00"}],
                },
            ],
            "left": {
                "sum": {"var": "assign", "index": ["e", "d", "late"]},
                "over": [
                    {
                        "index": "sub",
                        "set": "unit",
                        "via": {"rel": "reports_to", "from": "r", "depth": "any_or_self"},
                    },
                    {"index": "e", "set": "employee", "via": {"rel": "works_in", "to": "sub"}},
                ],
            },
            "relation": ">=",
            "right": {"const": 3},
            # Soft, and deliberately short by one: North Region and its
            # depot hold two people between them, so three is a target the
            # data cannot meet. That is the same honesty as the demand
            # figures -- the demo is over-subscribed on purpose -- and it
            # makes the penalty visible in `constraint_result` instead of
            # turning the whole model infeasible.
            "severity": "soft",
            "weight": 4,
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

WEEKLY_ROTA_TEMPLATE = "weekly_rota"


def weekly_rota_template_ir() -> dict[str, Any]:
    """The model a domain starts from: the demo's, with coverage a target.

    The seeded people cannot meet the seeded demand (21 shifts of capacity
    against 57 demanded), and no demand this data carries could make the
    hard rule meetable: a weekday wants nine people and there are five. As
    a *starting* model that meant a new user's first Solve said "no answer
    exists". So the template takes the demo's `relaxed_cover` softening --
    the same patch, the same penalty -- and solves to an optimal roster
    that shows the shortfall. The demo keeps its hard rule: it is the
    worked example of an infeasible model being explained.
    """
    softened = _SCENARIO_PATCH["soften"]
    constraints = []
    for spec in _IR["constraints"]:
        if spec["id"] in softened:
            spec = {**spec, "severity": "soft", "weight": int(softened[spec["id"]])}
        constraints.append(spec)
    return {**_IR, "constraints": constraints}


def _weekly_rota_domain_seed() -> dict[str, Any]:
    """The types, records and demand cells `plant_domain_seed` walks.

    Built from the same constants as the Workforce demo, so applying the
    template to an empty domain produces the same people, days and shifts
    the demo has, rather than a second handwritten copy that can drift.
    """
    entities: list[dict[str, Any]] = []
    for index, (key, label, _parent, cost_centre) in enumerate(_UNITS):
        entities.append({
            "type": "unit",
            "key": key,
            "label": label,
            "sort_order": index,
            "attrs": {
                "cost_centre": cost_centre,
                **({"site": {"type": "Point", "coordinates": _UNIT_SITES[key]}} if key in _UNIT_SITES else {}),
            },
        })
    for index, key in enumerate(_DAYS):
        entities.append({
            "type": "day",
            "key": key,
            "label": _DAY_LABELS[key],
            "sort_order": index,
            "attrs": {"is_weekend": key in ("sat", "sun")},
        })
    for index, (key, label, starts, ends) in enumerate(_SHIFTS):
        entities.append({
            "type": "shift",
            "key": key,
            "label": label,
            "sort_order": index,
            "attrs": {"starts_at": starts, "ends_at": ends},
        })
    for index, (key, label, _unit_key, attrs) in enumerate(_EMPLOYEES):
        entities.append({
            "type": "employee",
            "key": key,
            "label": label,
            "sort_order": index,
            "attrs": attrs,
        })
    relationships: list[dict[str, Any]] = []
    for key, _label, parent_key, _cost in _UNITS:
        if parent_key is not None:
            relationships.append({
                "type": "reports_to",
                "from": ["unit", parent_key],
                "to": ["unit", key],
            })
    for key, _label, unit_key, _attrs in _EMPLOYEES:
        relationships.append({
            "type": "works_in",
            "from": ["employee", key],
            "to": ["unit", unit_key],
        })
    return {
        "note": (
            "People, days and shifts. Coverage is a target; the seeded demand is "
            "more than five people can meet."
        ),
        "entity_types": [
            # integer, number, text, boolean and enum on `employee`; date
            # there too; `time` on `shift`. Spec §6 asks for full coverage
            # of the enum, and `test_seed_covers_every_attr_type` reads it
            # from the database rather than from a list here.
            {
                "name": "employee",
                "role": "agent",
                "colour": "#2563eb",
                "attributes": [
                    {"name": "full_name", "data_type": "text", "required": True},
                    {
                        "name": "hours_per_week",
                        "data_type": "integer",
                        "unit": "h/week",
                        "default_value": 40,
                    },
                    {
                        "name": "hourly_rate",
                        "data_type": "number",
                        "unit": "EUR/h",
                        "default_value": 20.0,
                    },
                    {"name": "on_call", "data_type": "boolean", "default_value": False},
                    {
                        "name": "grade",
                        "data_type": "enum",
                        "enum_values": ["junior", "mid", "senior"],
                        "default_value": "mid",
                    },
                    {"name": "hired_on", "data_type": "date"},
                    # Queue R20a: an entity as a value -- and the seed's one
                    # reference, so it still exercises every attribute type.
                    {"name": "mentor", "data_type": "reference", "target": "employee", "colour": "#0891b2"},
                ],
            },
            {
                "name": "unit",
                "role": "org",
                "colour": "#7c3aed",
                "attributes": [
                    {"name": "cost_centre", "data_type": "text"},
                    {"name": "site", "data_type": "geometry"},
                ],
            },
            {
                "name": "day",
                "role": "time",
                "colour": "#0d9488",
                "attributes": [
                    {"name": "is_weekend", "data_type": "boolean", "default_value": False}
                ],
            },
            {
                "name": "shift",
                "role": "time",
                "colour": "#d97706",
                "attributes": [
                    {"name": "starts_at", "data_type": "time", "required": True},
                    {"name": "ends_at", "data_type": "time", "required": True},
                ],
            },
        ],
        "relationship_types": [
            {
                "name": "reports_to",
                "from": "unit",
                "to": "unit",
                "cardinality": "one_to_many",
                "is_hierarchy": True,
                "colour": "#475569",
            },
            {
                "name": "works_in",
                "from": "employee",
                "to": "unit",
                "cardinality": "many_to_one",
                "is_hierarchy": False,
                "colour": "#16a34a",
            },
        ],
        "parameters": [
            {
                "name": "demand",
                "index": ["day", "shift"],
                "default_value": _DEMAND_DEFAULT,
                "unit": "people",
            }
        ],
        "entities": entities,
        "relationships": relationships,
        "parameter_values": [
            {
                "parameter": "demand",
                "entities": [["day", day_key], ["shift", shift_key]],
                "value": value,
            }
            for day_key in _DAYS
            for shift_key, value in (
                _WEEKEND_DEMAND if day_key in ("sat", "sun") else _WEEKDAY_DEMAND
            ).items()
        ],
    }


def ensure_weekly_rota_template(db: Session) -> int:
    """The starting model a domain can take, not a second copy of the demo.

    Idempotent on the name. A row that already exists is *refreshed* so a
    live database that got the thin seed cannot drift from this file:
    `domain_seed` and `default_ir` are written every call.
    """
    seed = _weekly_rota_domain_seed()
    found = db.execute(
        select(Template.id).where(Template.name == WEEKLY_ROTA_TEMPLATE)
    ).scalar_one_or_none()
    if found is not None:
        db.execute(
            update(Template)
            .where(Template.id == found)
            .values(domain_seed=seed, default_ir=weekly_rota_template_ir())
        )
        return found
    row = Template(
        name=WEEKLY_ROTA_TEMPLATE,
        ir_version="1",
        domain_seed=seed,
        default_ir=weekly_rota_template_ir(),
    )
    db.add(row)
    db.flush()
    return row.id


def seed_admin(db: Session) -> None:
    """Ensure a default organization and admin user exist. Idempotent."""
    settings = get_settings()

    org = db.query(Organization).filter(Organization.code == "default").first()
    if org is None:
        org = Organization(code="default", name="Default Organization", is_operator=True)
        db.add(org)
        db.commit()
        db.refresh(org)
    elif not org.is_operator:
        # The seed organization runs the platform (migration 0032). A
        # database migrated before it existed gets the flag here.
        org.is_operator = True
        db.commit()

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


def _entity_type(
    db: Session, domain_id: int, name: str, role: str, colour: str | None
) -> EntityType:
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
    sort_order: int | None = None,
    target: EntityType | None = None,
    colour: str | None = None,
) -> AttributeDef:
    if sort_order is None:
        # After the type's existing attributes, so a seed or a template lists
        # its attributes in the order it declares them (migration 0027)
        # rather than alphabetically.
        last = db.execute(
            select(func.max(AttributeDef.sort_order)).where(
                AttributeDef.entity_type_id == entity_type.id
            )
        ).scalar()
        sort_order = 1 if last is None else last + 1
    references_id = None
    if target is not None:
        # A reference's mirror, as the API makes it (migration 0067).
        mirror = RelationshipType(domain_id=entity_type.domain_id, name=name, from_type_id=entity_type.id,
                                  to_type_id=target.id, cardinality="many_to_one", colour=colour)
        db.add(mirror)
        db.flush()
        references_id = mirror.id
    row = AttributeDef(
        entity_type_id=entity_type.id,
        references_id=references_id,
        name=name,
        data_type=data_type,
        required=required,
        unit=unit,
        enum_values=enum_values,
        default_value=default_value,
        sort_order=sort_order,
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


def _ensure_attribute(
    db: Session, entity_type: EntityType, spec: dict[str, Any], types: dict[str, EntityType] | None = None
) -> AttributeDef | None:
    found = db.execute(
        select(AttributeDef).where(
            AttributeDef.entity_type_id == entity_type.id,
            AttributeDef.name == spec["name"],
        )
    ).scalar_one_or_none()
    if found is not None:
        return found
    target = None
    if spec["data_type"] == "reference":
        target = (types or {}).get(spec.get("target"))
        if target is None:
            return None  # a reference to a type the seed does not make
    return _attribute(
        db,
        entity_type,
        spec["name"],
        spec["data_type"],
        required=bool(spec.get("required", False)),
        unit=spec.get("unit"),
        enum_values=spec.get("enum_values"),
        default_value=spec.get("default_value"),
        sort_order=spec.get("sort_order") if isinstance(spec.get("sort_order"), int) else None,
        target=target,
        colour=spec.get("colour") if target is not None else None,
    )


def _seed_end(value: Any) -> tuple[str, str] | None:
    if isinstance(value, (list, tuple)) and len(value) == 2:
        return str(value[0]), str(value[1])
    return None


#: `"by": "#row"` in relationships_in_order: the records' own order, as their file lists them.
ROW_ORDER = "#row"
_MONTHS = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
_DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def order_key(v: Any) -> tuple:
    """How a field orders records: numbers by value, month and weekday names by the calendar ("Jan" .. "Dec",
    "January", "Mon" .. "Sunday", any case), and other text naturally ("P2" before "P10"). The production-plan
    field test (October 2026): months Jan..Jun sorted as text put April first and linked "Apr" -> "Feb"."""
    try:
        return (0, float(v), "")
    except (TypeError, ValueError):
        pass
    text = str(v).strip()
    low = text.lower()
    short = low if low in _MONTHS or low in _DAYS else (low[:3] if low in _CALENDAR_WORDS else None)
    for names, rank in ((_MONTHS, 1), (_DAYS, 2)):
        if short in names:
            return (rank, float(names.index(short)), "")
    parts = re.split(r"(\d+(?:\.\d+)?)", low)
    return (3, 0.0, tuple((0, float(p), "") if i % 2 else (1, 0.0, p) for i, p in enumerate(parts) if p != ""))


_CALENDAR_WORDS = {"january", "february", "march", "april", "june", "july", "august", "september", "october",
                   "november", "december", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday",
                   "sunday", "sept", "tues", "thur", "thurs"}


def order_links(seed: Any) -> Any:
    """`relationships_in_order`: links between records that follow each other -- the next step of the same job,
    the next day, the next period -- made from their own fields instead of a file of pairs. Each entry is
    {"type", "of": record type, "by": the ordering field, "within": a field that groups them (optional),
    "wrap": true to link the last back to the first (a week that repeats)}. Records come from the seed's
    entities (after their files are read); a link already given is not repeated. The job-shop field test
    (October 2026) had steps numbered within each part and no way to say "the next step"."""
    if not isinstance(seed, dict) or not seed.get("relationships_in_order"):
        return seed
    out = {k: v for k, v in seed.items() if k != "relationships_in_order"}
    links = list(out.get("relationships") or [])
    have = {(r.get("type"), tuple(r.get("from") or ()), tuple(r.get("to") or ())) for r in links if isinstance(r, dict)}

    def number(v: Any) -> Any:
        return order_key(v)

    for spec in seed["relationships_in_order"]:
        if not isinstance(spec, dict) or not spec.get("type") or not spec.get("of") or not spec.get("by"):
            continue
        groups: dict[Any, list[dict]] = {}
        by_row = spec["by"] == ROW_ORDER
        rows: dict[int, int] = {}
        for e in out.get("entities") or []:
            if not isinstance(e, dict) or e.get("type") != spec["of"]:
                continue
            attrs = e.get("attrs") or {}
            if (not by_row and spec["by"] not in attrs) or (spec.get("within") and spec["within"] not in attrs):
                continue
            rows[id(e)] = len(rows)
            groups.setdefault(attrs.get(spec["within"]) if spec.get("within") else None, []).append(e)
        for members in groups.values():
            members.sort(key=(lambda e: rows[id(e)]) if by_row else
                         (lambda e: number((e.get("attrs") or {}).get(spec["by"]))))
            pairs = list(zip(members, members[1:]))
            if spec.get("wrap") and len(members) > 2:
                pairs.append((members[-1], members[0]))
            for a, b in pairs:
                link = {"type": spec["type"], "from": [spec["of"], str(a["key"])], "to": [spec["of"], str(b["key"])]}
                if (link["type"], tuple(link["from"]), tuple(link["to"])) not in have:
                    links.append(link)
    out["relationships"] = links
    return out


def order_links_problems(seed: Any) -> list[str]:
    """Why a `relationships_in_order` entry would make no links, in words the writer can act on (the job-shop
    retest: "within": "job" with job loaded only as the label -- three times "then has NO links")."""
    problems: list[str] = []
    if not isinstance(seed, dict):
        return problems
    for spec in seed.get("relationships_in_order") or []:
        if not isinstance(spec, dict) or not spec.get("of") or not spec.get("by"):
            problems.append('each relationships_in_order entry names "type", "of" (a record type) and "by" '
                            '(the field that orders them); "within" (a grouping field) is optional')
            continue
        records = [e for e in seed.get("entities") or [] if isinstance(e, dict) and e.get("type") == spec["of"]]
        if not records:
            problems.append(f'relationships_in_order "{spec.get("type")}": no {spec["of"]} records in the seed '
                            f'(load them with entities_from_file)')
            continue
        fields = sorted({k for e in records for k in (e.get("attrs") or {})})
        for need in [*([spec["by"]] if spec["by"] != ROW_ORDER else []), *([spec["within"]] if spec.get("within") else [])]:
            if not any(need in (e.get("attrs") or {}) for e in records):
                problems.append(f'relationships_in_order "{spec.get("type")}": the {spec["of"]} records have no field '
                                f'"{need}" (their fields: {", ".join(fields) or "none"}); add "{need}": "<its column>" '
                                f'to their entities_from_file attrs (and to the entity type) -- a label is not a field')
    return problems


#: The most pairs one `distances_from_fields` entry writes (as `POST .../distances` does, app.api.distances).
FIELD_DISTANCE_PAIRS = 250_000


def field_distances(seed: Any) -> Any:
    """`distances_from_fields`: straight-line distances between records from two of their own number fields
    (x and y in km or metres -- a drawing's local metres, a plan's grid), as a parameter `name[of, to]`, in the
    fields' own unit. Each entry is {"name", "of": record type, "to": record type (default: the same), "x", "y",
    "round": decimals (optional)}. Map shapes have `POST .../distances`; plain coordinates had nothing, and a
    routing model needed run_python to make its distance table (the evaluation, October 2026)."""
    if not isinstance(seed, dict) or not seed.get("distances_from_fields"):
        return seed
    import math

    out = {k: v for k, v in seed.items() if k != "distances_from_fields"}
    params = list(out.get("parameters") or [])
    cells = list(out.get("parameter_values") or [])
    for spec in seed["distances_from_fields"]:
        if not isinstance(spec, dict) or not all(spec.get(k) for k in ("name", "of", "x", "y")):
            continue
        to = spec.get("to") or spec["of"]

        def points(kind: str) -> list[tuple[str, float, float]]:
            found = []
            for e in out.get("entities") or []:
                attrs = (e.get("attrs") or {}) if isinstance(e, dict) else {}
                if e.get("type") == kind:
                    try:
                        found.append((str(e["key"]), float(attrs[spec["x"]]), float(attrs[spec["y"]])))
                    except (KeyError, TypeError, ValueError):
                        continue
            return found

        origins, targets = points(spec["of"]), points(to)
        if len(origins) * len(targets) > FIELD_DISTANCE_PAIRS:
            continue
        if not any(isinstance(p, dict) and p.get("name") == spec["name"] for p in params):
            params.append({"name": spec["name"], "index": [spec["of"], to], "default_value": 0})
        places = spec.get("round")
        for a, ax, ay in origins:
            for b, bx, by in targets:
                d = math.hypot(ax - bx, ay - by)
                cells.append({"parameter": spec["name"], "entities": [[spec["of"], a], [to, b]],
                              "value": round(d, int(places)) if isinstance(places, int) else d})
    out["parameters"] = params
    out["parameter_values"] = cells
    return out


#: The most patterns one `patterns_that_fit` entry writes; past it only the full ones (nothing more fits) are kept.
PATTERN_LIMIT = 5_000


def _fits(spec: dict[str, Any], seed: dict[str, Any]) -> tuple[list[tuple[str, float]], float] | str:
    """The items (key, size) and the capacity of one `patterns_that_fit` entry, or why there are none."""
    try:
        capacity = float(spec.get("capacity"))
    except (TypeError, ValueError):
        return f'patterns_that_fit "{spec.get("type")}": "capacity" must be a number (the roll, bin or truck size)'
    if capacity <= 0:
        return f'patterns_that_fit "{spec.get("type")}": "capacity" must be above 0'
    records = [e for e in seed.get("entities") or [] if isinstance(e, dict) and e.get("type") == spec.get("of")]
    if not records:
        return (f'patterns_that_fit "{spec.get("type")}": no {spec.get("of")} records in the seed (load them with '
                f'entities_from_file)')
    items = []
    for e in records:
        try:
            size = float((e.get("attrs") or {})[spec["size"]])
        except (KeyError, TypeError, ValueError):
            fields = sorted({k for r in records for k in (r.get("attrs") or {})})
            return (f'patterns_that_fit "{spec.get("type")}": the {spec.get("of")} records have no number field '
                    f'"{spec.get("size")}" (their fields: {", ".join(fields) or "none"}); load it as a field')
        if size <= 0:
            return f'patterns_that_fit "{spec.get("type")}": {e.get("key")} has size {size}; sizes must be above 0'
        items.append((str(e["key"]), size))
    return items, capacity


def pattern_problems(seed: Any) -> list[str]:
    """Why a `patterns_that_fit` entry would make nothing, in words the writer can act on."""
    problems: list[str] = []
    if not isinstance(seed, dict):
        return problems
    for spec in seed.get("patterns_that_fit") or []:
        if not isinstance(spec, dict) or not all(spec.get(k) for k in ("type", "of", "size", "count")):
            problems.append('each patterns_that_fit entry names "type" (the new pattern records), "of" (the item '
                            'records), "size" (their size field), "capacity" (a number) and "count" (the parameter '
                            'count[pattern, item] it writes)')
            continue
        found = _fits(spec, seed)
        if isinstance(found, str):
            problems.append(found)
    return problems


def fitting_patterns(seed: Any) -> Any:
    """`patterns_that_fit`: every way to fill one roll, bin or truck of a given capacity with the item records
    (as many of each as fit), as new records of `type` with fields `used` and `waste`, and a parameter
    `count[type, of]` -- how many of each item a pattern holds. A cutting-stock or bin-packing model then decides
    how often to use each pattern (the Gilmore-Gomory model: exact, and small for a handful of sizes). Each entry is
    {"type", "of", "size", "capacity", "count"}. Past PATTERN_LIMIT patterns only the full ones are kept (nothing
    more fits), which is enough when surplus is allowed. The paper-cutting field test (October 2026): the Assistant
    set out to write the patterns by hand."""
    if not isinstance(seed, dict) or not seed.get("patterns_that_fit"):
        return seed
    out = {k: v for k, v in seed.items() if k != "patterns_that_fit"}
    types = list(out.get("entity_types") or [])
    entities = list(out.get("entities") or [])
    params = list(out.get("parameters") or [])
    cells = list(out.get("parameter_values") or [])
    for spec in seed["patterns_that_fit"]:
        if not isinstance(spec, dict) or not all(spec.get(k) for k in ("type", "of", "size", "count")):
            continue
        found = _fits(spec, out)
        if isinstance(found, str):
            continue
        items, capacity = found
        items.sort(key=lambda kv: -kv[1])
        smallest = min(size for _, size in items)
        patterns: list[tuple[list[int], float]] = []
        full_only = False

        def walk(i: int, room: float, counts: list[int]) -> None:
            if len(patterns) > PATTERN_LIMIT * 4:
                return
            if i == len(items):
                if any(counts) and (not full_only or room < smallest - 1e-9):
                    patterns.append((counts[:], capacity - room))
                return
            size = items[i][1]
            for k in range(int((room + 1e-9) // size), -1, -1):
                counts.append(k)
                walk(i + 1, room - k * size, counts)
                counts.pop()

        walk(0, capacity, [])
        if len(patterns) > PATTERN_LIMIT:
            full_only, patterns = True, []
            walk(0, capacity, [])
        patterns = patterns[:PATTERN_LIMIT]
        if not any(isinstance(t, dict) and t.get("name") == spec["type"] for t in types):
            types.append({"name": spec["type"], "role": "other", "attributes": [
                {"name": "used", "data_type": "number"}, {"name": "waste", "data_type": "number"}]})
        if not any(isinstance(p, dict) and p.get("name") == spec["count"] for p in params):
            params.append({"name": spec["count"], "index": [spec["type"], spec["of"]], "default_value": 0})
        for counts, used in patterns:
            key = " + ".join(f"{name} x{k}" if k > 1 else name for (name, _), k in zip(items, counts) if k)
            entities.append({"type": spec["type"], "key": key,
                             "attrs": {"used": round(used, 6), "waste": round(capacity - used, 6)}})
            for (name, _), k in zip(items, counts):
                if k:
                    cells.append({"parameter": spec["count"], "entities": [[spec["type"], key], [spec["of"], name]],
                                  "value": k})
    out.update(entity_types=types, entities=entities, parameters=params, parameter_values=cells)
    return out


#: Links written per statement when a seed is planted.
LINK_BATCH = 10_000


def plant_domain_seed(db: Session, domain_id: int, seed: Any, *, fresh_types: bool = False) -> None:
    """Create missing types, records and cells named by a template's seed.

    A name that already exists is left alone -- applying weekly_rota to
    Workforce must not invent a second Ahmed. ``{}`` is a no-op, so a
    template that only carries IR still 422s from ``validate_ir``.
    """
    if not isinstance(seed, dict):
        return

    types: dict[str, EntityType] = {
        row.name: row
        for row in db.execute(select(EntityType).where(EntityType.domain_id == domain_id)).scalars()
    }
    for spec in seed.get("entity_types") or []:
        if not isinstance(spec, dict) or not spec.get("name"):
            continue
        name = spec["name"]
        if name not in types:
            types[name] = _entity_type(
                db, domain_id, name, spec.get("role") or "other", spec.get("colour")
            )
        for attr in spec.get("attributes") or []:
            if isinstance(attr, dict) and attr.get("name") and attr.get("data_type"):
                _ensure_attribute(db, types[name], attr, types)

    rel_types: dict[str, RelationshipType] = {
        row.name: row
        for row in db.execute(
            select(RelationshipType).where(RelationshipType.domain_id == domain_id)
        ).scalars()
    }
    for spec in seed.get("relationship_types") or []:
        if not isinstance(spec, dict) or not spec.get("name"):
            continue
        name = spec["name"]
        if name in rel_types:
            continue
        from_type = types.get(spec.get("from"))
        to_type = types.get(spec.get("to"))
        if from_type is None or to_type is None:
            continue
        row = RelationshipType(
            domain_id=domain_id,
            name=name,
            from_type_id=from_type.id,
            to_type_id=to_type.id,
            cardinality=spec.get("cardinality") or "many_to_many",
            is_hierarchy=bool(spec.get("is_hierarchy", False)),
            colour=spec.get("colour"),
        )
        db.add(row)
        db.flush()
        rel_types[name] = row

    params: dict[str, ParameterDef] = {
        row.name: row
        for row in db.execute(
            select(ParameterDef).where(ParameterDef.domain_id == domain_id)
        ).scalars()
    }
    for spec in seed.get("parameters") or []:
        if not isinstance(spec, dict) or not spec.get("name"):
            continue
        name = spec["name"]
        if name in params:
            continue
        index_names = spec.get("index") or []
        if not isinstance(index_names, list) or any(n not in types for n in index_names):
            continue
        row = ParameterDef(
            domain_id=domain_id,
            name=name,
            index_type_ids=[types[n].id for n in index_names],
            default_value=spec.get("default_value", 0),
            unit=spec.get("unit"),
        )
        db.add(row)
        db.flush()
        params[name] = row

    entities: dict[tuple[str, str], Entity] = {}
    if not fresh_types:
        for type_name, entity_type in types.items():
            for row in db.execute(select(Entity).where(Entity.entity_type_id == entity_type.id)).scalars():
                entities[(type_name, row.key)] = row
    for spec in seed.get("entities") or []:
        if not isinstance(spec, dict) or not spec.get("key") or spec.get("type") not in types:
            continue
        key = (spec["type"], spec["key"])
        if key in entities:
            # Kept as it is, but a field it lacks is filled in: a model built again from new files (a new
            # column, such as a layout's `entrance`) must not read nothing there. Differing values are
            # refused before the build (model_spec.stale_records).
            row = entities[key]
            if row.id is not None:
                fill = {a: v for a, v in (spec.get("attrs") or {}).items() if (row.attrs or {}).get(a) is None}
                if fill:
                    row.attrs = {**(row.attrs or {}), **fill}
            continue
        # Added now, written in one flush below: a flush per record took 38 s for the 20,000 candidates
        # of a layout (camp-bed retest); ids are only needed from the relationships on.
        row = Entity(entity_type_id=types[spec["type"]].id, key=spec["key"], label=spec.get("label"),
                     sort_order=int(spec.get("sort_order") or 0), attrs=spec.get("attrs") or {})
        db.add(row)
        entities[key] = row
    db.flush()

    # The links already there, read once per type rather than one query per link (a layout's occupancy
    # links run to hundreds of thousands); new ones written in one flush.
    linked: dict[int, set[tuple[int, int]]] = {}
    new_links: list[dict[str, int]] = []
    for spec in seed.get("relationships") or []:
        if not isinstance(spec, dict) or spec.get("type") not in rel_types:
            continue
        src, dst = _seed_end(spec.get("from")), _seed_end(spec.get("to"))
        if src is None or dst is None or src not in entities or dst not in entities:
            continue
        rel_type = rel_types[spec["type"]]
        if rel_type.id not in linked:
            linked[rel_type.id] = set() if fresh_types else {
                (a, b) for a, b in db.execute(
                    select(Relationship.from_entity_id, Relationship.to_entity_id).where(
                        Relationship.relationship_type_id == rel_type.id)).all()}
        pair = (entities[src].id, entities[dst].id)
        if pair in linked[rel_type.id]:
            continue
        linked[rel_type.id].add(pair)
        new_links.append({"relationship_type_id": rel_type.id, "from_entity_id": pair[0], "to_entity_id": pair[1]})
    db.flush()
    # Written as rows, not one ORM object each, in batches (the scale benchmark of 7 October 2026: 200,000
    # links took 79 s to build, most of it per-link work; the database's own checks still run on every row).
    for start in range(0, len(new_links), LINK_BATCH):
        db.execute(Relationship.__table__.insert(), new_links[start:start + LINK_BATCH])

    cells: list[dict[str, Any]] = []
    for spec in seed.get("parameter_values") or []:
        if not isinstance(spec, dict) or spec.get("parameter") not in params:
            continue
        keys = spec.get("entities")
        if not isinstance(keys, list):
            continue
        param = params[spec["parameter"]]
        if not keys and not (param.index_type_ids or []):
            # A single number given as a cell is the parameter's value: its default, which every read of a
            # parameter without an index uses (the database-source test, October 2026: two capacities written
            # as cells with no index were read as their default 0, and the plan made nothing).
            value = spec.get("value")
            if isinstance(value, (int, float)) and not isinstance(value, bool) and param.value_type_id is None:
                param.default_value = value
                db.flush()
            continue
        entity_ids: list[int] = []
        skip = False
        for item in keys:
            end = _seed_end(item)
            if end is None or end not in entities:
                skip = True
                break
            entity_ids.append(entities[end].id)
        if skip:
            continue
        cells.append(
            {
                "parameter_def_id": params[spec["parameter"]].id,
                "entity_ids": entity_ids,
                "value": spec.get("value", 0),
            }
        )
    if cells:
        # Ruling 24: Core, not db.add() -- the primary key contains an array.
        # Skip cells that already exist so a second apply does not 409.
        # One JSON parameter, not a VALUES list (the general-purpose evaluation, October 2026: compiling
        # 24,000 VALUES rows took SQLAlchemy 3 s of a 19 s build); checked per statement since 0112.
        db.execute(
            text(
                "INSERT INTO parameter_value (parameter_def_id, entity_ids, value)"
                " SELECT r.parameter_def_id, r.entity_ids, r.value"
                " FROM jsonb_to_recordset(CAST(:cells AS jsonb))"
                " AS r(parameter_def_id bigint, entity_ids bigint[], value numeric)"
                " ON CONFLICT DO NOTHING"
            ),
            {"cells": json.dumps(cells, default=str)},
        )

    for spec in seed.get("grids") or []:
        _plant_grid(db, domain_id, spec, entities)
    # Distances and nearness from the places' shapes (queue R16a), once the places exist.
    _measure(db, domain_id, seed, types)


def _measure(db: Session, domain_id: int, seed: dict[str, Any], types: dict[str, EntityType]) -> None:
    """A seed's `distances` ({name, from, to, unit?, nearest?}), `within` ({name, from, to, max_m,
    output?: "parameter" for 0/1 data}) and `inside` ({name, from, to}), computed as `POST .../distances`,
    `.../within` and `.../spatial/inside` do. A name the domain already has is left alone,
    as every other name in a seed is."""
    from app.api.distances import DistanceRequest, WithinRequest, write_distances, write_within

    for spec in seed.get("distances") or []:
        if not isinstance(spec, dict) or spec.get("from") not in types or spec.get("to") not in types:
            continue
        if db.execute(select(ParameterDef.id).where(ParameterDef.domain_id == domain_id,
                                                    ParameterDef.name == spec.get("name"))).scalar_one_or_none():
            continue
        write_distances(db, domain_id, DistanceRequest(
            name=spec["name"], from_type_id=types[spec["from"]].id, to_type_id=types[spec["to"]].id,
            unit=spec.get("unit", "m"), nearest=spec.get("nearest")), commit=False)
    for spec in seed.get("within") or []:
        if not isinstance(spec, dict) or spec.get("from") not in types or spec.get("to") not in types:
            continue
        if db.execute(select(RelationshipType.id).where(RelationshipType.domain_id == domain_id,
                                                        RelationshipType.name == spec.get("name"))).scalar_one_or_none():
            continue
        if spec.get("output") == "parameter" and db.execute(select(ParameterDef.id).where(
                ParameterDef.domain_id == domain_id, ParameterDef.name == spec.get("name"))).scalar_one_or_none():
            continue
        write_within(db, domain_id, WithinRequest(
            name=spec["name"], from_type_id=types[spec["from"]].id, to_type_id=types[spec["to"]].id,
            max_m=spec["max_m"], output=spec.get("output", "relationship")), commit=False)
    # Which area each place lies in: a link a rule walks (`inside`, as POST .../spatial/inside makes).
    from app.api.spatial_ops import Pair, write_inside

    for spec in seed.get("inside") or []:
        if not isinstance(spec, dict) or spec.get("from") not in types or spec.get("to") not in types:
            continue
        if db.execute(select(RelationshipType.id).where(RelationshipType.domain_id == domain_id,
                                                        RelationshipType.name == spec.get("name"))).scalar_one_or_none():
            continue
        write_inside(db, domain_id, Pair(name=spec["name"], from_type_id=types[spec["from"]].id, to_type_id=types[spec["to"]].id))


def _plant_grid(db: Session, domain_id: int, spec: Any, entities: dict[tuple[str, str], Entity]) -> None:
    """A seed's grid (GIS 8): cells and adjacency over one of the seed's own
    records, made after the records exist. A type that already has cells is
    left alone, as every other name in a seed is -- a second apply does not
    remake a grid a scenario may already use."""
    from app.api.grids import GridRequest, write_grid

    if not isinstance(spec, dict):
        return
    end = _seed_end(spec.get("boundary_entity"))
    if end is None or end not in entities:
        return
    existing = db.execute(
        select(func.count(Entity.id))
        .join(EntityType, EntityType.id == Entity.entity_type_id)
        .where(EntityType.domain_id == domain_id, EntityType.name == spec.get("entity_type"))
    ).scalar_one()
    if existing:
        return
    body = {k: v for k, v in spec.items() if k != "boundary_entity"}
    write_grid(db, domain_id, GridRequest(**body, boundary_entity_id=entities[end].id), commit=False)


def seed_workforce_demo(db: Session) -> dict[str, Any]:
    """Create the "Workforce" demo domain, or report that it is already there.

    Returns the ids of what it created (or found), plus ``created``:
    ``True`` when this call wrote the data, ``False`` when it found the
    domain already present and wrote nothing at all.
    """
    template_id = ensure_weekly_rota_template(db)

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
            if problem_id is not None:
                db.execute(
                    text(
                        "UPDATE problem SET template_id = :t"
                        " WHERE id = :p AND template_id IS NULL"
                    ),
                    {"t": template_id, "p": problem_id},
                )
        db.commit()
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

    # Types, people, days, shifts, demand: the same JSON apply walks.
    plant_domain_seed(db, domain.id, _weekly_rota_domain_seed())
    types = {
        row.name: row
        for row in db.execute(select(EntityType).where(EntityType.domain_id == domain.id)).scalars()
    }
    rel_types = {
        row.name: row
        for row in db.execute(
            select(RelationshipType).where(RelationshipType.domain_id == domain.id)
        ).scalars()
    }
    params = {
        row.name: row
        for row in db.execute(
            select(ParameterDef).where(ParameterDef.domain_id == domain.id)
        ).scalars()
    }
    employee, unit, day, shift = types["employee"], types["unit"], types["day"], types["shift"]
    reports_to, works_in = rel_types["reports_to"], rel_types["works_in"]
    demand = params["demand"]

    # -- problem, model version, scenario ---------------------------------
    problem = Problem(
        domain_id=domain.id, name="weekly_rota", owner="demo", template_id=template_id
    )
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
