"""Build a whole problem from one spec: the assistant's "describe it in words" path.

    POST /api/v1/problems/from-spec        {..., "dry_run": true}  check only, nothing kept
    POST /api/v1/problems/from-spec        {..., "dry_run": false} build it

A spec is what a template is -- a `domain_seed` and an IR -- plus where to put
it. The build is `apply_template`'s, in one transaction: the domain (new or
existing), its missing types, fields, links, parameters, records and cells
(`plant_domain_seed`), the problem, its first model version and a `Base`
scenario. Any refusal rolls all of it back, so nothing is left half-built.

`plant_domain_seed` skips an entry it cannot place (a parameter indexed by a
type nobody makes, a cell naming a record that does not exist) -- right for a
template someone tested, wrong for a spec a language model wrote. So the seed
is checked first and every such entry is a refusal naming where it is, the
way a 422 names a field. A dry run returns them all at once; the model fixes
them before the person is ever shown the plan.
"""

from __future__ import annotations

import re
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, insert, select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app import audit
from app.api.deps import requires
from app.core.db import get_db
from app.crud.db_errors import translate_db_error
from app.ir.validate import validate_ir
from app.models.iam import UserAccount
from app.models.v1_domain import AttributeDef, Domain, Entity, EntityType, ParameterDef, Relationship, RelationshipType
from app.models.v1_problem import ModelVersion, Problem, Scenario
from app.seed import (field_distances, fitting_patterns, order_links, order_links_problems, pattern_problems,
                      plant_domain_seed)

router = APIRouter(prefix="/api/v1", tags=["problems"])

NAME = re.compile(r"^[a-z][a-z0-9_]*$")
ROLES = {"agent", "resource", "time", "location", "task", "org", "other"}
DATA_TYPES = {"integer", "number", "text", "boolean", "enum", "time", "date", "geometry", "reference"}
CARDINALITIES = {"one_to_one", "one_to_many", "many_to_one", "many_to_many"}
MAX_ENTITIES = 150_000  # a layout's generated candidates and cells (camp-bed tests): 50,000 refused 62,000
MAX_CELLS = 200_000


class ModelSpec(BaseModel):
    domain_id: int | None = Field(default=None, description="put it in this existing domain")
    domain_name: str | None = Field(default=None, max_length=200, description="or make a new domain")
    problem_name: str = Field(min_length=1, max_length=200)
    seed: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "entity_types [{name, role, attributes [{name, data_type, required, unit, enum_values, "
            "default_value}]}], relationship_types [{name, from, to, cardinality, is_hierarchy}], "
            "parameters [{name, index [type names], default_value, unit}], entities [{type, key, label, "
            "attrs}], relationships [{type, from [type, key], to [type, key]}], parameter_values "
            "[{parameter, entities [[type, key], ...], value}]"
        ),
    )
    ir: dict[str, Any] = Field(description="the Problem IR (docs/contracts/problem-ir.md)")
    note: str | None = Field(default=None, max_length=2000, description="kept on the model version")
    dry_run: bool = False


def _end(value: Any) -> tuple[str, str] | None:
    if isinstance(value, (list, tuple)) and len(value) == 2:
        return str(value[0]), str(value[1])
    if isinstance(value, dict) and "type" in value and "key" in value:
        return str(value["type"]), str(value["key"])
    return None


def normalise(seed: dict[str, Any]) -> dict[str, Any]:
    """`{type, key}` ends as `[type, key]`, which is what `plant_domain_seed` reads."""
    out = dict(seed)
    out["relationships"] = [
        {**r, "from": list(_end(r.get("from")) or []), "to": list(_end(r.get("to")) or [])}
        for r in seed.get("relationships") or [] if isinstance(r, dict)
    ]
    out["parameter_values"] = [
        {**v, "entities": [list(_end(e) or []) for e in v.get("entities") or []]}
        for v in seed.get("parameter_values") or [] if isinstance(v, dict)
    ]
    return out


def check_seed(db: Session, domain_id: int | None, seed: dict[str, Any]) -> list[dict[str, Any]]:
    """Every entry `plant_domain_seed` would skip or the database would refuse."""
    errors: list[dict[str, Any]] = []

    def err(loc: list, msg: str) -> None:
        errors.append({"loc": ["seed", *loc], "msg": msg})

    existing_types: dict[str, int] = {}
    existing_attrs: dict[str, dict[str, AttributeDef]] = {}
    existing_params: dict[str, list[int]] = {}
    if domain_id is not None:
        for t in db.execute(select(EntityType).where(EntityType.domain_id == domain_id)).scalars():
            existing_types[t.name] = t.id
            existing_attrs[t.name] = {
                a.name: a for a in db.execute(select(AttributeDef).where(AttributeDef.entity_type_id == t.id)).scalars()}
        for p in db.execute(select(ParameterDef).where(ParameterDef.domain_id == domain_id)).scalars():
            existing_params[p.name] = list(p.index_type_ids or [])

    types: dict[str, dict[str, dict]] = {n: {a: {"data_type": d.data_type,
                                                 "required": d.required and d.default_value is None}
                                             for a, d in attrs.items()}
                                         for n, attrs in existing_attrs.items()}
    for i, t in enumerate(seed.get("entity_types") or []):
        name = (t or {}).get("name")
        if not isinstance(name, str) or not NAME.match(name):
            err(["entity_types", i, "name"], "a lower_snake_case name is required")
            continue
        if t.get("role") and t["role"] not in ROLES:
            err(["entity_types", i, "role"], f"role must be one of {sorted(ROLES)}")
        attrs = types.setdefault(name, {})
        for j, a in enumerate(t.get("attributes") or []):
            an, dt = (a or {}).get("name"), (a or {}).get("data_type")
            if not isinstance(an, str) or not NAME.match(an):
                err(["entity_types", i, "attributes", j, "name"], "a lower_snake_case name is required")
                continue
            if dt not in DATA_TYPES:
                err(["entity_types", i, "attributes", j, "data_type"], f"data_type must be one of {sorted(DATA_TYPES)}")
                continue
            if dt == "enum" and not a.get("enum_values"):
                err(["entity_types", i, "attributes", j, "enum_values"], "an enum needs enum_values")
            if dt == "reference" and not a.get("target"):
                err(["entity_types", i, "attributes", j, "target"], "a reference needs a target type")
            attrs.setdefault(an, {"data_type": dt,
                                  "required": bool(a.get("required")) and a.get("default_value") is None})

    for i, r in enumerate(seed.get("relationship_types") or []):
        for end in ("from", "to"):
            if (r or {}).get(end) not in types:
                err(["relationship_types", i, end], f"no entity type named {r.get(end)!r}")
        if r.get("cardinality") and r["cardinality"] not in CARDINALITIES:
            err(["relationship_types", i, "cardinality"], f"cardinality must be one of {sorted(CARDINALITIES)}")
    rel_types = {r.get("name") for r in seed.get("relationship_types") or [] if isinstance(r, dict)}

    params: dict[str, int] = {n: len(ix) for n, ix in existing_params.items()}
    for i, p in enumerate(seed.get("parameters") or []):
        name = (p or {}).get("name")
        if not isinstance(name, str) or not NAME.match(name):
            err(["parameters", i, "name"], "a lower_snake_case name is required")
            continue
        index = p.get("index") or []
        missing = [n for n in index if n not in types]
        if missing:
            err(["parameters", i, "index"], f"no entity type named {missing}")
        if not isinstance(p.get("default_value", 0), (int, float)):
            err(["parameters", i, "default_value"], "a number is required")
        params.setdefault(name, len(index))

    entity_keys: set[tuple[str, str]] = set()
    entities = seed.get("entities") or []
    if len(entities) > MAX_ENTITIES:
        err(["entities"], f"at most {MAX_ENTITIES} records in one spec; import the rest from a spreadsheet")
    for i, e in enumerate(entities):
        t, key = (e or {}).get("type"), (e or {}).get("key")
        if t not in types:
            err(["entities", i, "type"], f"no entity type named {t!r}")
            continue
        if key in (None, ""):
            err(["entities", i, "key"], "a key is required")
            continue
        attrs = e.get("attrs") or {}
        for an in attrs:
            if an not in types[t]:
                err(["entities", i, "attrs", an], f"{t} has no attribute {an!r}; declare it on the entity type")
        for an, spec in types[t].items():
            if spec["required"] and an not in attrs:
                err(["entities", i, "attrs"], f"{t}.{an} is required")
        entity_keys.add((t, str(key)))

    def known(end: tuple[str, str] | None) -> bool:
        # A record already in the domain is fine too; the database says so at build time.
        return end is not None and (end in entity_keys or end[0] in existing_types)

    for i, r in enumerate(seed.get("relationships") or []):
        if (r or {}).get("type") not in rel_types:
            err(["relationships", i, "type"], f"no relationship type named {r.get('type')!r} in the seed")
        for end in ("from", "to"):
            if not known(_end(r.get(end))):
                err(["relationships", i, end], f"no record {r.get(end)!r}; use [type, key] of a record in entities")

    cells = seed.get("parameter_values") or []
    if len(cells) > MAX_CELLS:
        err(["parameter_values"], f"at most {MAX_CELLS} cells in one spec")
    unknown: set[str] = set()
    missing: set[str] = set()
    for i, v in enumerate(cells):
        name = (v or {}).get("parameter")
        if name not in params:
            # Once per name, saying how to fix it: the Assistant's field tests (October 2026) declared a
            # parameter in the IR only, and got the same line back once per cell -- 42 of them.
            if name not in unknown:
                unknown.add(name)
                count = sum(1 for c in cells if (c or {}).get("parameter") == name)
                err(["parameter_values", i, "parameter"],
                    f"no parameter named {name!r} ({count} cells give it values); declare it in the seed's "
                    'parameters: {"name", "index": [record types], "default_value"} -- the IR\'s "parameters" '
                    "only says which ones the model reads")
            continue
        ends = v.get("entities") or []
        if len(ends) != params[name]:
            err(["parameter_values", i, "entities"],
                f"{name} has {params[name]} index(es); give exactly that many [type, key] records")
        for k, item in enumerate(ends):
            if not known(_end(item)):
                # Once per missing record, saying where records come from (the retest: 21 cells for days
                # and shifts that were never made, each refused with a bare "no record ['day', 'Sun']").
                if repr(item) in missing:
                    continue
                missing.add(repr(item))
                err(["parameter_values", i, "entities", k],
                    f"no record {item!r}: every record a value names must exist -- make it in the seed's "
                    'entities ({"type", "key"}), load it with entities_from_file, or use one already in the domain')
        if not isinstance(v.get("value"), (int, float)):
            err(["parameter_values", i, "value"], "a number is required")
    if domain_id is not None and not errors:
        errors.extend({"loc": ["seed", *loc], "msg": msg} for loc, msg in stale_records(db, domain_id, seed))
    return errors


def _same(a: Any, b: Any) -> bool:
    if a == b:
        return True
    try:
        return float(a) == float(b)
    except (TypeError, ValueError):
        return str(a) == str(b)


def stale_records(db: Session, domain_id: int, seed: dict[str, Any]) -> list[tuple[list, str]]:
    """Records and links of the seed that the domain already holds differently.

    A key already in the domain is left as it is (a template must not make a second Ahmed), so a model built
    again from new files into the same workspace would read yesterday's values and keep yesterday's links
    beside today's: the camp retest (October 2026) rebuilt a layout into its old workspace, its cells kept no
    `entrance` field and the old candidates' links, and the run said "optimal" with no bed at all. A field
    the old record lacks is filled in at build time; a value or a link that differs is refused here, once
    per type with a count, so the build goes to a new workspace or uses new keys."""
    out: list[tuple[list, str]] = []
    by_type: dict[str, dict[str, dict]] = {}
    for e in seed.get("entities") or []:
        if isinstance(e, dict) and e.get("type") and e.get("key") not in (None, ""):
            by_type.setdefault(e["type"], {})[str(e["key"])] = e.get("attrs") or {}
    if not by_type:
        return out
    types = {t.name: t.id for t in db.execute(select(EntityType).where(EntityType.domain_id == domain_id)).scalars()}
    ids: dict[tuple[str, str], int] = {}
    for name, records in by_type.items():
        if name not in types:
            continue
        differ, example = 0, None
        for row in db.execute(select(Entity).where(Entity.entity_type_id == types[name])).scalars():
            ids[(name, row.key)] = row.id
            new = records.get(row.key)
            if new is None:
                continue
            old = row.attrs or {}
            bad = next((a for a, v in new.items() if a in old and old[a] is not None and v is not None
                        and not _same(old[a], v)), None)
            if bad is not None:
                differ += 1
                example = example or (row.key, bad, old[bad], new[bad])
        if differ:
            key, field, was, now = example
            out.append((["entities"], (
                f"{differ} {name} record(s) are already in this workspace with other values (e.g. {key!r}: "
                f"{field} is {was!r} there, {now!r} here); the old values would stay. Build in a new workspace "
                f"(domain_name instead of domain_id), or give the records new keys")))
    rels = {r.name: r.id for r in db.execute(
        select(RelationshipType).where(RelationshipType.domain_id == domain_id)).scalars()}
    wanted: dict[str, set[tuple[int, int]]] = {}
    sources: dict[str, set[int]] = {}
    for r in seed.get("relationships") or []:
        if not isinstance(r, dict) or r.get("type") not in rels:
            continue
        a, b = _end(r.get("from")), _end(r.get("to"))
        if a in ids and b in ids:
            wanted.setdefault(r["type"], set()).add((ids[a], ids[b]))
            sources.setdefault(r["type"], set()).add(ids[a])
    for name, pairs in wanted.items():
        extra = sum(1 for a, b in db.execute(select(Relationship.from_entity_id, Relationship.to_entity_id)
                                             .where(Relationship.relationship_type_id == rels[name])).all()
                    if a in sources[name] and (a, b) not in pairs)
        if extra:
            out.append((["relationships"], (
                f"{extra} {name} link(s) already in this workspace start at records of this spec but are not in "
                f"it; they would stay beside the new ones. Build in a new workspace (domain_name instead of "
                f"domain_id), or give the records new keys")))
    return out


@router.post("/problems/from-spec")
def build_from_spec(
    spec: ModelSpec,
    request: Request,
    db: Session = Depends(get_db),
    user: UserAccount = Depends(requires("model.publish")),
) -> dict[str, Any]:
    """Check (`dry_run`) or build a domain's data, a problem, its model and a Base scenario
    from one spec, all or nothing. A refusal is a 422 whose `detail` lists every error
    with `loc` (where) and `msg` (what)."""
    if spec.domain_id is None and not (spec.domain_name or "").strip():
        raise HTTPException(status_code=422, detail=[{"loc": ["domain_name"], "msg": "give domain_id or domain_name"}])
    if spec.domain_id is not None and db.get(Domain, spec.domain_id) is None:
        raise HTTPException(status_code=404, detail="domain not found")

    # Links between records that follow each other, made from their fields (app.seed.order_links).
    problems = order_links_problems(spec.seed)
    if problems:
        raise HTTPException(status_code=422, detail=[{"loc": ["seed", "relationships_in_order"], "msg": m}
                                                     for m in problems])
    problems = pattern_problems(order_links(spec.seed))
    if problems:
        raise HTTPException(status_code=422, detail=[{"loc": ["seed", "patterns_that_fit"], "msg": m}
                                                     for m in problems])
    spec.seed = fitting_patterns(field_distances(order_links(spec.seed)))
    errors = check_seed(db, spec.domain_id, spec.seed)
    if errors:
        raise HTTPException(status_code=422, detail=errors)

    try:
        made_domain = spec.domain_id is None
        if made_domain:
            # A name already used (the roster field test got Postgres' "a problem row with the same
            # domain_organization_name already exists" and could not tell what to change).
            existing = db.scalar(select(Domain.id).where(Domain.name == spec.domain_name.strip()))  # type: ignore[union-attr]
            if existing is not None:
                raise HTTPException(status_code=422, detail=[{"loc": ["domain_name"], "msg": (
                    f"a domain named {spec.domain_name.strip()!r} already exists (id {existing}): give another "
                    f"domain_name for a new one, or domain_id {existing} to build in it")}])
            domain = Domain(name=spec.domain_name.strip())  # type: ignore[union-attr]
            db.add(domain)
            db.flush()
            domain_id = domain.id
        else:
            domain_id = spec.domain_id  # type: ignore[assignment]
            taken = db.scalar(select(func.count()).select_from(Problem)
                              .where(Problem.domain_id == domain_id, Problem.name == spec.problem_name))
            if taken:
                raise HTTPException(status_code=422, detail=[
                    {"loc": ["problem_name"], "msg": "a problem with this name already exists in the domain"}])

        plant_domain_seed(db, domain_id, normalise(spec.seed))
        db.flush()
        problem = Problem(domain_id=domain_id, name=spec.problem_name, owner=user.username)
        db.add(problem)
        db.flush()

        refusal = validate_ir(db, domain_id, spec.ir)
        if refusal is not None:
            raise HTTPException(status_code=422, detail=[{"loc": ["ir", *refusal.loc], "msg": refusal.message}])

        counts = {
            "entity_types": len(spec.seed.get("entity_types") or []),
            "entities": len(spec.seed.get("entities") or []),
            "relationships": len(spec.seed.get("relationships") or []),
            "parameters": len(spec.seed.get("parameters") or []),
            "parameter_values": len(spec.seed.get("parameter_values") or []),
            "variables": len(spec.ir.get("variables") or {}),
            "constraints": len(spec.ir.get("constraints") or []),
            "objective_terms": len((spec.ir.get("objective") or {}).get("terms") or []),
        }
        if spec.dry_run:
            db.rollback()
            return {"ok": True, "dry_run": True, "would_create": counts}

        version_id = db.execute(
            insert(ModelVersion.__table__)
            .values(problem_id=problem.id, ir=spec.ir, note=spec.note or "built by the assistant from a description")
            .returning(ModelVersion.__table__.c.id)
        ).scalar_one()
        scenario = Scenario(problem_id=problem.id, model_version_id=version_id, name="Base", patch={})
        db.add(scenario)
        db.flush()
        audit.write(
            db, user, request,
            action="problem.from_spec",
            object_type="problem",
            object_id=problem.id,
            after={"domain_id": domain_id, "domain_created": made_domain,
                   "model_version_id": version_id, "scenario_id": scenario.id, "created": counts},
        )
        db.commit()
    except HTTPException:
        db.rollback()
        raise
    except DBAPIError as exc:
        db.rollback()
        raise translate_db_error(exc, "problem") from exc
    return {"ok": True, "dry_run": False, "domain_id": domain_id, "domain_created": made_domain,
            "problem_id": problem.id, "model_version_id": version_id, "scenario_id": scenario.id,
            "created": counts}
