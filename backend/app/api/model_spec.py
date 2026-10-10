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
from app.core import limits
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
MAX_ENTITIES = limits.SPEC_RECORDS  # a layout's generated candidates and cells (app/core/limits.py)
MAX_CELLS = limits.SPEC_CELLS


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
    #: With dry_run: also solve the model once on its data, briefly, before anything is kept (`trial` in the
    #: answer: status, goal, how many cells of each decision are used) -- a plan that cannot be met, or that
    #: chooses nothing, shows before a person approves it.
    trial: bool = False


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


TRIAL_SECONDS = 15
TRIAL_CELLS = 200_000
#: A decision's used cells are named in the trial when there are at most this many.
TRIAL_LISTED = 12


def _trial(db: Session, domain_id: int, ir: dict[str, Any], keep: dict[str, Any] | None = None) -> dict[str, Any]:
    """One short solve of the planned model on its own data, inside the dry run's transaction (the field tests,
    October 2026: plans that passed every check read stock from the month after, or planned for futures with
    nothing decided later -- a trial shows what such a model does before a person approves it)."""
    from app.solve import sandbox
    from app.solve.backends import NoBackend, choose
    from app.solve.classify import classify
    from app.solve.compile import Unsupported, compile_model
    from app.solve.convexity import refine
    from app.solve.preview import live_data

    try:
        data = live_data(db, domain_id, ir)
        compiled = compile_model(ir, data)
    except Unsupported as exc:
        return {"status": "not compiled", "why": str(exc)[:500]}
    except Exception as exc:  # noqa: BLE001 -- a trial informs, it never refuses a plan
        return {"status": "not compiled", "why": f"{type(exc).__name__}: {str(exc)[:300]}"}
    if keep is not None:
        keep["compiled"] = compiled  # for the shape checks (app.solve.lint), which read the same rows
    if len(compiled.variables) > TRIAL_CELLS:
        return {"status": "skipped", "why": f"{len(compiled.variables):,} decisions: too big for a trial"}
    try:
        found = refine(classify(ir, data), compiled)
        backend, _ = choose(found)
        result, reason = sandbox.run("app.solve.sandbox:solve_in_child",
                             {"backend": backend.name, "compiled": compiled, "time_limit": TRIAL_SECONDS,
                              "seed": 0, "workers": 1, "gap_rel": 0.0},
                             time_limit=TRIAL_SECONDS)
    except NoBackend as exc:
        return {"status": "no solver", "why": str(exc)[:300]}
    except Exception as exc:  # noqa: BLE001
        return {"status": "failed", "why": f"{type(exc).__name__}: {str(exc)[:300]}"}
    if result is None:
        return {"status": "no answer", "why": str(reason or "")[:300]}
    used: dict[str, list[int]] = {}
    for key in compiled.variables:
        if not str(key[0]).startswith("__"):
            used.setdefault(str(key[0]), [0, 0])[1] += 1
    # Which cells are used, by their records' keys, while that is short enough to read (the file-source test,
    # October 2026: given only "3 of 5", the Assistant named three projects the trial had not chosen).
    chosen: dict[str, list[str]] = {}
    for key, value in (result.assignments or {}).items():
        if str(key[0]) in used and abs(float(value)) > 1e-9:
            used[str(key[0])][0] += 1
            index = key[1] if len(key) > 1 and isinstance(key[1], (tuple, list)) else key[1:]
            cell = " · ".join(map(str, index))
            amount = float(value)
            chosen.setdefault(str(key[0]), []).append(
                cell if abs(amount - 1) < 1e-9 else f"{cell} = {round(amount, 6):g}")
    conflict: dict[str, Any] = {}
    if result.status == "infeasible":
        conflict = _trial_conflict(backend.name, compiled, ir)
    return {"status": result.status, "objective": result.objective, "solver": backend.name,
            "seconds": TRIAL_SECONDS, **conflict,
            "used": {k: {"non_zero": v[0], "cells": v[1],
                         **({"chosen": chosen.get(k, [])} if v[0] <= TRIAL_LISTED else {})} for k, v in used.items()}}


#: Solves a trial may spend finding which rules cannot hold together, and the seconds each gets.
CONFLICT_PROBES = 40
CONFLICT_PROBE_SECONDS = 2.0
#: A proven-smallest conflict names its records when it is at most this many rows.
CONFLICT_ROWS = 6


def _trial_conflict(backend: str, compiled: Any, ir: dict[str, Any]) -> dict[str, Any]:
    """Which rules of an infeasible trial cannot hold together, with their notes (the Nile Juice check, 10 October
    2026: overtime written on the wrong side of the capacity rule gave a plan with no answer, and "infeasible"
    alone sent the Assistant to tell the person their demand could not be met). A few short probes; nothing when
    they do not settle it."""
    from types import SimpleNamespace

    from app.solve import diagnose, sandbox

    def probe(model: Any, *, time_limit: float, workers: int) -> Any:
        try:
            answer, _ = sandbox.run("app.solve.sandbox:solve_in_child",
                                    {"backend": backend, "compiled": model, "time_limit": time_limit, "seed": 0,
                                     "workers": 1, "gap_rel": 0.0}, time_limit=time_limit)
        except Exception:  # noqa: BLE001 -- a probe that fails decides nothing
            answer = None
        return answer if answer is not None else SimpleNamespace(status="unknown")

    try:
        found = diagnose.explain(compiled, probe, probe_seconds=CONFLICT_PROBE_SECONDS, budget=CONFLICT_PROBES)
    except Exception:  # noqa: BLE001 -- the trial informs; it never fails a plan
        return {}
    rules = [r for r in found.rules if not str(r).startswith("__")]
    if not rules or len(rules) == len({c.id for c in compiled.constraints}) > 6:
        return {}
    notes = {c.get("id"): c.get("note") for c in ir.get("constraints") or [] if isinstance(c, dict)}
    # Which records, when the conflict is proven smallest and short: "c_balance at OJ1L, W01" says the balance is
    # also written for the first week, where no week comes before (the Nile Juice check's second wrong model).
    rows: dict[str, list[str]] = {}
    if found.minimal and len(found.items) <= CONFLICT_ROWS:
        for item in found.items:
            if item.get("instance"):
                rows.setdefault(item["constraint_id"], []).append(", ".join(map(str, item["instance"])))
    return {"conflict": [{"rule": r, **({"note": str(notes[r])[:200]} if notes.get(r) else {}),
                          **({"at": rows[r]} if rows.get(r) else {})} for r in rules]}


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
        if not spec.dry_run and spec.seed.get("source_bindings"):
            # What came from which source -- a database table (use_source) or a file kept in the workspace -- so it
            # can be refreshed (migrations 0114, 0115).
            from app.integrations.refresh import file_sheet, keepable, record_bindings, save_file

            versions = {}
            for f in spec.seed.get("source_files") or []:
                if keepable(f):
                    versions[f["name"]] = save_file(db, domain_id, f, user.id)
            for b in spec.seed["source_bindings"]:
                if b.get("file_name"):
                    kept = versions.get(b["file_name"]) or (file_sheet(db, domain_id, b["file_name"]) or {}).get("source")
                    if kept:
                        b["file_version"], b["sha256"] = kept.get("version"), kept.get("sha256")
            spec.seed["source_bindings"] = [b for b in spec.seed["source_bindings"]
                                            if not b.get("file_name") or b.get("file_version")]
            record_bindings(db, domain_id, spec.seed["source_bindings"])
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
            **({"bound_to_sources": len(spec.seed["source_bindings"])} if spec.seed.get("source_bindings") else {}),
        }
        if spec.dry_run:
            kept: dict[str, Any] = {}
            trial = _trial(db, domain_id, spec.ir, kept) if spec.trial else None
            db.rollback()
            shape: list[dict[str, Any]] = []
            if spec.trial:
                # What the model's shape gives away even when it solves (app.solve.lint): a decision that can
                # never help, data given and never read. Findings, never a refusal.
                from app.solve import lint

                try:
                    shape = lint.findings(spec.ir, spec.seed, kept.get("compiled"))
                except Exception:  # noqa: BLE001 -- a check that fails says nothing
                    shape = []
            return {"ok": True, "dry_run": True, "would_create": counts, **({"trial": trial} if trial else {}),
                    **({"shape": shape} if shape else {})}

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


class DraftCheck(BaseModel):
    ir: dict[str, Any] = Field(description="the draft model, as the editor holds it")
    trial: bool = Field(default=False, description="also solve it once, briefly, on the domain's data")


@router.post("/problems/{problem_id}/draft-check")
def check_draft(problem_id: int, body: DraftCheck, db: Session = Depends(get_db),
                user: UserAccount = Depends(requires("model.publish"))) -> dict[str, Any]:
    """What `check_spec` gives the Assistant, for a draft in the model editor (owner, 9 October 2026: everything
    without the Assistant): the platform's refusal if any, the model read back in plain words, and -- with
    `trial` -- one short solve on the domain's own data. Nothing is kept."""
    from app.agent.readback import readback

    problem = db.get(Problem, problem_id)
    if problem is None:
        raise HTTPException(status_code=404, detail="problem not found")
    refusal = validate_ir(db, problem.domain_id, body.ir)
    out: dict[str, Any] = {
        "refusal": {"code": refusal.code, "loc": refusal.loc, "message": refusal.message} if refusal else None,
        "readback": readback({"ir": body.ir}).split("\n")[1:],
    }
    if body.trial and refusal is None:
        out["trial"] = _trial(db, problem.domain_id, body.ir)
        db.rollback()
    return out
