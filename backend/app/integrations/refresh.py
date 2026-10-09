"""Refreshing a domain's data from its database sources (migration 0114).

A plan that loaded a source's sheet (`use_source`, then *_from_file) keeps a binding per entry: the connection,
the entry's mapping (key/label/fields, link ends, or a parameter's index columns and value) and the extraction it
was built from. `compare` reads a newer extraction through the same mapping and says what would change -- records
added, fields changed, records gone, links and values added, changed or gone -- and `apply` writes it in one
transaction. Records a source no longer has are set inactive (kept, with their history), never deleted.
"""
from __future__ import annotations

import json
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.agent import files as agent_files
from app.integrations import artifacts

#: Rows one refresh reads from a source: one extraction's ceiling (app.integrations.contracts).
SOURCE_ROWS = 100_000
#: Example keys listed per change kind in a report; the counts are always whole.
SHOWN = 20
KIND_KEY = {"entities": "entities_from_file", "relationships": "relationships_from_file",
            "parameter_values": "parameter_values_from_file"}


class RefreshRefused(ValueError):
    pass


# -- an extraction as a sheet ---------------------------------------------------------------------------------

def job_row(db: Session, job_id: int, organization_id) -> dict | None:
    row = db.execute(text(
        "SELECT j.id, j.state, j.artifact_id, j.connection_id, j.finished_at, c.domain_id, c.name AS connection_name"
        " FROM ingestion_job j JOIN integration_connection c ON c.id = j.connection_id"
        " WHERE j.id = :id AND j.organization_id = :o"), {"id": job_id, "o": organization_id}).mappings().one_or_none()
    return dict(row) if row else None


def job_sheet(job: dict, organization_id) -> dict:
    """An extracted job as an attached file: `{name, sheets: [...], source: {...}}`, rows checked against the
    extraction's SHA-256. Raises `artifacts.ArtifactUnavailable` / `ArtifactChanged`."""
    if job["state"] != "extracted" or job["artifact_id"] is None:
        raise artifacts.ArtifactUnavailable(f"this extraction has no rows to read (it is {job['state']})")
    path = artifacts.folder(organization_id, job["connection_id"], job["artifact_id"])
    manifest = artifacts.manifest(path)
    sheets = []
    for entry in artifacts.tables(manifest):  # a sheet per table read (one source, several tables)
        records = artifacts.verified_rows(path, entry.get("sha256", ""), SOURCE_ROWS, entry.get("file") or "rows.jsonl")
        columns = list(entry.get("columns") or (list(records[0]) if records else []))
        rows = [[agent_files._cell(r.get(c)) for c in columns] for r in records]
        total = int(entry.get("rows") or len(rows))
        sheets.append({"name": str(entry.get("source_object") or "rows"), "columns": columns, "rows": rows,
                       "total_rows": total, "truncated": total > len(rows),
                       **({"since": entry["since"]} if entry.get("since") is not None else {})})
    return {"name": job["connection_name"], "sheets": sheets,
            "source": {"connection_id": job["connection_id"], "job_id": job["id"],
                       "sha256": manifest.get("sha256"), "extracted_at": manifest.get("completed_at"),
                       **({"since": manifest["since"]} if manifest.get("since") is not None else {})}}


# -- bindings -------------------------------------------------------------------------------------------------

# -- workspace files (migration 0115) -------------------------------------------------------------------------

#: The most rows a file kept in a workspace may have (all sheets): an attachment's own ceiling is 5,000 a sheet.
FILE_ROWS = 60_000


def file_sha(sheets: list[dict]) -> str:
    """A file's fingerprint: its tables as read (columns and rows), so the same content is the same version."""
    import hashlib

    canonical = json.dumps([{"name": s.get("name"), "columns": s.get("columns"), "rows": s.get("rows")}
                            for s in sheets or []], sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


def keepable(f: dict) -> bool:
    """An attached table file a workspace can keep: not a map file, not a database source, not too big."""
    if not isinstance(f, dict) or f.get("spatial") or f.get("source") or not f.get("name"):
        return False
    return sum(len(s.get("rows") or []) for s in f.get("sheets") or []) <= FILE_ROWS


def save_file(db: Session, domain_id: int, f: dict, added_by=None) -> dict:
    """Keep a file in the workspace: a new version unless the latest one has the same content."""
    sheets = [{k: s.get(k) for k in ("name", "columns", "rows", "total_rows", "truncated")} for s in f.get("sheets") or []]
    sha = file_sha(sheets)
    latest = db.execute(text("SELECT version, sha256 FROM workspace_file WHERE domain_id = :d AND name = :n"
                             " ORDER BY version DESC LIMIT 1"), {"d": domain_id, "n": f["name"]}).first()
    if latest is not None and latest.sha256 == sha:
        return {"name": f["name"], "version": latest.version, "sha256": sha, "new": False}
    version = (latest.version if latest else 0) + 1
    db.execute(text("INSERT INTO workspace_file (domain_id, name, version, sha256, sheets, rows, added_by)"
                    " VALUES (:d, :n, :v, :s, CAST(:sheets AS jsonb), :r, :u)"),
               {"d": domain_id, "n": f["name"], "v": version, "s": sha, "sheets": json.dumps(sheets, default=str),
                "r": sum(len(x.get("rows") or []) for x in sheets), "u": added_by})
    return {"name": f["name"], "version": version, "sha256": sha, "new": True}


def file_sheet(db: Session, domain_id: int, name: str, version: int | None = None) -> dict | None:
    """A kept file as an attached file, `source` naming the file and version."""
    row = db.execute(text(
        "SELECT name, version, sha256, sheets, created_at FROM workspace_file WHERE domain_id = :d AND name = :n"
        + (" AND version = :v" if version else "") + " ORDER BY version DESC LIMIT 1"),
        {"d": domain_id, "n": name, "v": version}).mappings().first()
    if row is None:
        return None
    return {"name": row["name"], "sheets": row["sheets"],
            "source": {"file": row["name"], "version": row["version"], "sha256": row["sha256"],
                       "added_at": row["created_at"].isoformat()}}


def files(db: Session, domain_id: int) -> list[dict]:
    return [dict(r) for r in db.execute(text(
        "SELECT name, max(version) AS latest, count(*) AS versions, max(created_at) AS updated_at,"
        " (array_agg(rows ORDER BY version DESC))[1] AS rows FROM workspace_file WHERE domain_id = :d"
        " GROUP BY name ORDER BY name"), {"d": domain_id}).mappings()]


def record_bindings(db: Session, domain_id: int, bindings: list[dict] | None) -> int:
    """Keep what a build loaded from which source. A source of another domain is not bound (a refresh of this
    domain must not read another's connection); a second build from the same source replaces the mapping."""
    kept = 0
    for b in bindings or []:
        if not isinstance(b, dict) or b.get("kind") not in KIND_KEY or not b.get("target"):
            continue
        if b.get("file_name"):
            db.execute(text(
                "INSERT INTO source_binding (domain_id, file_name, file_version, kind, target, mapping, sha256,"
                " refreshed_at) VALUES (:d, :f, :v, :k, :t, CAST(:m AS jsonb), :s, now())"
                " ON CONFLICT (domain_id, file_name, kind, target) WHERE file_name IS NOT NULL DO UPDATE SET"
                " mapping = EXCLUDED.mapping, file_version = EXCLUDED.file_version, sha256 = EXCLUDED.sha256,"
                " refreshed_at = now()"),
                {"d": domain_id, "f": b["file_name"], "v": b.get("file_version"), "k": b["kind"],
                 "t": str(b["target"])[:200], "m": json.dumps(b.get("mapping") or {}), "s": b.get("sha256")})
            kept += 1
            continue
        owner = db.execute(text("SELECT domain_id FROM integration_connection WHERE id = :c"),
                           {"c": b.get("connection_id")}).scalar()
        if owner != domain_id:
            continue
        db.execute(text(
            "INSERT INTO source_binding (domain_id, connection_id, kind, target, mapping, job_id, sha256, refreshed_at)"
            " VALUES (:d, :c, :k, :t, CAST(:m AS jsonb), :j, :s, now())"
            " ON CONFLICT (domain_id, connection_id, kind, target) DO UPDATE SET mapping = EXCLUDED.mapping,"
            " job_id = EXCLUDED.job_id, sha256 = EXCLUDED.sha256, refreshed_at = now()"),
            {"d": domain_id, "c": b["connection_id"], "k": b["kind"], "t": str(b["target"])[:200],
             "m": json.dumps(b.get("mapping") or {}), "j": b.get("job_id"), "s": b.get("sha256")})
        kept += 1
    return kept


def bindings(db: Session, domain_id: int) -> list[dict]:
    return [dict(r) for r in db.execute(text(
        "SELECT b.id, b.connection_id, coalesce(c.name, b.file_name) AS connection, coalesce(c.enabled, true) AS enabled,"
        " b.file_name, b.file_version, b.kind, b.target, b.mapping, b.job_id,"
        " b.sha256, b.created_at, b.refreshed_at FROM source_binding b"
        " LEFT JOIN integration_connection c ON c.id = b.connection_id WHERE b.domain_id = :d"
        " ORDER BY CASE b.kind WHEN 'entities' THEN 0 WHEN 'relationships' THEN 1 ELSE 2 END, b.id"),
        {"d": domain_id}).mappings()]


# -- what the source says now, through a binding's mapping -----------------------------------------------------

def _wanted(binding: dict, sheet: dict) -> list[dict]:
    """The records, links or cells the binding's mapping makes from the sheet: what the build made from it."""
    entry = {**(binding["mapping"] or {}), "file": sheet["name"]}
    if binding["kind"] == "entities":
        entry.setdefault("type", binding["target"])
    elif binding["kind"] == "relationships":
        entry.setdefault("type", binding["target"])
    else:
        entry.setdefault("parameter", binding["target"])
    try:
        made = agent_files.expand({KIND_KEY[binding["kind"]]: [entry]}, [sheet])
    except agent_files.FileRefused as exc:
        raise RefreshRefused(f"{binding['connection']} -> {binding['target']}: {exc}") from None
    return list(made.get(binding["kind"]) or [])


def _same(a: Any, b: Any) -> bool:
    if isinstance(a, (int, float)) and isinstance(b, (int, float)) and not isinstance(a, bool) and not isinstance(b, bool):
        return abs(float(a) - float(b)) <= 1e-9 * max(1.0, abs(float(a)), abs(float(b)))
    try:
        return float(a) == float(b)  # 37.5 stored as "37.5" or Decimal
    except (TypeError, ValueError):
        return a == b


def _report() -> dict:
    return {"added": [], "changed": [], "removed": [], "unchanged": 0}


def _entities(db: Session, domain_id: int, binding: dict, wanted: list[dict]) -> dict:
    type_id = db.execute(text("SELECT id FROM entity_type WHERE domain_id = :d AND name = :n"),
                         {"d": domain_id, "n": binding["target"]}).scalar()
    if type_id is None:
        raise RefreshRefused(f"the kind of record {binding['target']!r} no longer exists in this workspace")
    have = {r["key"]: dict(r) for r in db.execute(text(
        "SELECT id, key, label, attrs, active FROM entity WHERE entity_type_id = :t"), {"t": type_id}).mappings()}
    mapped = list((binding["mapping"] or {}).get("attrs") or {})
    labelled = bool((binding["mapping"] or {}).get("label"))
    out = _report() | {"type_id": type_id, "mapped": mapped}
    seen = set()
    for w in wanted:
        key = str(w["key"])
        seen.add(key)
        h = have.get(key)
        if h is None or not h["active"]:
            out["added"].append({"key": key, "label": w.get("label"), "attrs": w.get("attrs") or {},
                                 "returning": h is not None})
            continue
        diffs = [{"field": a, "before": (h["attrs"] or {}).get(a), "after": (w.get("attrs") or {}).get(a)}
                 for a in mapped if not _same((h["attrs"] or {}).get(a), (w.get("attrs") or {}).get(a))]
        if labelled and (w.get("label") or None) != (h["label"] or None):
            diffs.append({"field": "label", "before": h["label"], "after": w.get("label")})
        if diffs:
            out["changed"].append({"key": key, "fields": diffs})
        else:
            out["unchanged"] += 1
    out["removed"] = [{"key": k} for k, h in have.items() if h["active"] and k not in seen]
    return out


def _ids(db: Session, domain_id: int, pairs: set[tuple[str, str]]) -> dict[tuple[str, str], int]:
    if not pairs:
        return {}
    rows = db.execute(text(
        "SELECT t.name, e.key, e.id FROM entity e JOIN entity_type t ON t.id = e.entity_type_id"
        " WHERE t.domain_id = :d AND (t.name, e.key) IN (SELECT * FROM unnest(CAST(:n AS text[]), CAST(:k AS text[])))"),
        {"d": domain_id, "n": [p[0] for p in pairs], "k": [p[1] for p in pairs]}).all()
    return {(n, k): i for n, k, i in rows}


def _relationships(db: Session, domain_id: int, binding: dict, wanted: list[dict]) -> dict:
    rt = db.execute(text("SELECT id FROM relationship_type WHERE domain_id = :d AND name = :n"),
                    {"d": domain_id, "n": binding["target"]}).scalar()
    if rt is None:
        raise RefreshRefused(f"the relationship type {binding['target']!r} no longer exists in this workspace")
    have = {(f, t): i for i, f, t in db.execute(text(
        "SELECT r.id, ef.key, et.key FROM relationship r JOIN entity ef ON ef.id = r.from_entity_id"
        " JOIN entity et ON et.id = r.to_entity_id WHERE r.relationship_type_id = :r"), {"r": rt}).all()}
    out = _report() | {"type_id": rt}
    seen = set()
    for w in wanted:
        pair = (str(w["from"][1]), str(w["to"][1]))
        seen.add(pair)
        if pair in have:
            out["unchanged"] += 1
        else:
            out["added"].append({"from": list(w["from"]), "to": list(w["to"])})
    out["removed"] = [{"from": f, "to": t, "id": i} for (f, t), i in have.items() if (f, t) not in seen]
    return out


def _cells(db: Session, domain_id: int, binding: dict, wanted: list[dict]) -> dict:
    param = db.execute(text("SELECT id, index_type_ids FROM parameter_def WHERE domain_id = :d AND name = :n"),
                       {"d": domain_id, "n": binding["target"]}).mappings().one_or_none()
    if param is None:
        raise RefreshRefused(f"the data value {binding['target']!r} no longer exists in this workspace")
    have = {tuple(keys): (value, ids) for keys, value, ids in db.execute(text(
        "SELECT array_agg(e.key ORDER BY u.ord), v.value, v.entity_ids FROM parameter_value v"
        " CROSS JOIN LATERAL unnest(v.entity_ids) WITH ORDINALITY AS u(eid, ord) JOIN entity e ON e.id = u.eid"
        " WHERE v.parameter_def_id = :p GROUP BY v.entity_ids, v.value"), {"p": param["id"]}).all()}
    out = _report() | {"parameter_id": param["id"]}
    seen = set()
    for w in wanted:
        keys = tuple(str(k) for _, k in w["entities"])
        seen.add(keys)
        h = have.get(keys)
        if h is None:
            out["added"].append({"index": list(keys), "entities": w["entities"], "value": w["value"]})
        elif not _same(h[0], w["value"]):
            out["changed"].append({"index": list(keys), "before": float(h[0]) if h[0] is not None else None,
                                   "after": w["value"], "entity_ids": list(h[1])})
        else:
            out["unchanged"] += 1
    out["removed"] = [{"index": list(k), "entity_ids": list(ids)} for k, (_, ids) in have.items() if k not in seen]
    return out


def compare(db: Session, domain_id: int, binding: dict, sheet: dict) -> dict:
    wanted = _wanted(binding, sheet)
    if binding["kind"] == "entities":
        out = _entities(db, domain_id, binding, wanted)
    elif binding["kind"] == "relationships":
        out = _relationships(db, domain_id, binding, wanted)
    else:
        out = _cells(db, domain_id, binding, wanted)
    # The binding's own table: each table of a source has its own mark.
    named = (binding.get("mapping") or {}).get("sheet")
    own = next((t for t in sheet.get("sheets") or [] if t.get("name") == named), None) if named else None
    own = own or ((sheet.get("sheets") or [None])[0] if len(sheet.get("sheets") or []) == 1 else None)
    since = own.get("since") if own is not None else (sheet.get("source") or {}).get("since")
    if since is not None:
        # An incremental read (migration 0118) has only what changed since `since`: a record it does not have is
        # unchanged, not gone. A full read finds what was removed.
        out["removed"] = []
        out["incremental_since"] = since
    return out


# -- writing it ------------------------------------------------------------------------------------------------

def apply_change(db: Session, domain_id: int, binding: dict, change: dict, remove_missing: bool) -> dict:
    """Write one binding's change. Entities before links and values (the caller orders the bindings)."""
    kind = binding["kind"]
    written = {"added": 0, "changed": 0, "removed": 0}
    if kind == "entities":
        order = db.execute(text("SELECT coalesce(max(sort_order), 0) FROM entity WHERE entity_type_id = :t"),
                           {"t": change["type_id"]}).scalar()
        for a in change["added"]:
            if a.get("returning"):
                db.execute(text("UPDATE entity SET active = true, attrs = attrs || CAST(:a AS jsonb),"
                                " label = coalesce(:l, label) WHERE entity_type_id = :t AND key = :k"),
                           {"a": json.dumps(a["attrs"], default=str), "l": a.get("label"), "t": change["type_id"],
                            "k": a["key"]})
            else:
                order += 1
                db.execute(text("INSERT INTO entity (entity_type_id, key, label, attrs, sort_order)"
                                " VALUES (:t, :k, :l, CAST(:a AS jsonb), :o)"),
                           {"t": change["type_id"], "k": a["key"], "l": a.get("label"),
                            "a": json.dumps(a["attrs"], default=str), "o": order})
            written["added"] += 1
        for c in change["changed"]:
            fields = {f["field"]: f["after"] for f in c["fields"] if f["field"] != "label"}
            label = next((f["after"] for f in c["fields"] if f["field"] == "label"), None)
            db.execute(text("UPDATE entity SET attrs = (attrs - CAST(:gone AS text[])) || CAST(:a AS jsonb),"
                            " label = CASE WHEN :relabel THEN :l ELSE label END"
                            " WHERE entity_type_id = :t AND key = :k"),
                       {"a": json.dumps({k: v for k, v in fields.items() if v is not None}, default=str),
                        "gone": [k for k, v in fields.items() if v is None],
                        "relabel": any(f["field"] == "label" for f in c["fields"]), "l": label,
                        "t": change["type_id"], "k": c["key"]})
            written["changed"] += 1
        if remove_missing and change["removed"]:
            db.execute(text("UPDATE entity SET active = false WHERE entity_type_id = :t AND key = ANY(:k)"),
                       {"t": change["type_id"], "k": [r["key"] for r in change["removed"]]})
            written["removed"] = len(change["removed"])
    elif kind == "relationships":
        ends = {tuple(a["from"]) for a in change["added"]} | {tuple(a["to"]) for a in change["added"]}
        ids = _ids(db, domain_id, ends)
        for a in change["added"]:
            f, t = ids.get(tuple(a["from"])), ids.get(tuple(a["to"]))
            if f is None or t is None:
                raise RefreshRefused(f"{binding['target']}: a link names a record the workspace does not have "
                                     f"({a['from']} -> {a['to']}); refresh the source of those records too")
            db.execute(text("INSERT INTO relationship (relationship_type_id, from_entity_id, to_entity_id)"
                            " VALUES (:r, :f, :t)"), {"r": change["type_id"], "f": f, "t": t})
            written["added"] += 1
        if remove_missing and change["removed"]:
            db.execute(text("DELETE FROM relationship WHERE id = ANY(:ids)"),
                       {"ids": [r["id"] for r in change["removed"]]})
            written["removed"] = len(change["removed"])
    else:
        ends = {tuple(e) for a in change["added"] for e in a["entities"]}
        ids = _ids(db, domain_id, ends)
        cells = []
        for a in change["added"]:
            entity_ids = [ids.get(tuple(e)) for e in a["entities"]]
            if None in entity_ids:
                raise RefreshRefused(f"{binding['target']}: a value names a record the workspace does not have "
                                     f"({a['index']}); refresh the source of those records too")
            cells.append({"p": change["parameter_id"], "e": entity_ids, "v": a["value"]})
        cells += [{"p": change["parameter_id"], "e": c["entity_ids"], "v": c["after"]} for c in change["changed"]]
        if cells:
            db.execute(text(
                "INSERT INTO parameter_value (parameter_def_id, entity_ids, value)"
                " SELECT r.p, r.e, r.v FROM jsonb_to_recordset(CAST(:cells AS jsonb)) AS r(p bigint, e bigint[], v numeric)"
                " ON CONFLICT (parameter_def_id, entity_ids) DO UPDATE SET value = EXCLUDED.value"),
                {"cells": json.dumps(cells, default=str)})
        written["added"], written["changed"] = len(change["added"]), len(change["changed"])
        if remove_missing and change["removed"]:
            for r in change["removed"]:
                db.execute(text("DELETE FROM parameter_value WHERE parameter_def_id = :p AND entity_ids = CAST(:e AS bigint[])"),
                           {"p": change["parameter_id"], "e": r["entity_ids"]})
            written["removed"] = len(change["removed"])
    return written


def shown(change: dict) -> dict:
    """A change for a person or the Assistant: counts, and up to SHOWN examples of each kind."""
    def strip(items: list[dict]) -> list[dict]:
        return [{k: v for k, v in i.items() if k not in ("id", "entity_ids", "entities")} for i in items[:SHOWN]]
    return {"counts": {"added": len(change["added"]), "changed": len(change["changed"]),
                       "removed": len(change["removed"]), "unchanged": change["unchanged"]},
            "added": strip(change["added"]), "changed": strip(change["changed"]), "removed": strip(change["removed"])}


# -- one refresh, for the API, the Sources page and the schedule ------------------------------------------------

def run_refresh(db: Session, domain_id: int, organization_id, *, jobs: dict | None = None, files: dict | None = None,
                connections: list | None = None, apply: bool = False, remove_missing: bool = True,
                on_applied=None) -> dict:
    """Compare the domain's bound data with its sources (the named extractions / file versions, else each one's
    latest) and, with `apply`, write it in one transaction. Raises RefreshRefused for what a person must fix."""
    bound = [b for b in bindings(db, domain_id)
             if (not connections and not files) or (connections and b["connection_id"] in connections)
             or (files and b["file_name"] in files)]
    if not bound:
        raise RefreshRefused("Nothing in this workspace was built from a data source, so there is nothing to refresh. "
                             "Data loaded from a source with use_source and *_from_file is bound to it.")
    sheets: dict[Any, dict] = {}
    for name in {b["file_name"] for b in bound if b["file_name"]}:
        found = file_sheet(db, domain_id, name, (files or {}).get(name))
        if found is None:
            raise RefreshRefused(f"The workspace has no file {name!r} (or that version).")
        sheets[("file", name)] = found
    for cid in {b["connection_id"] for b in bound if b["connection_id"]}:
        job_id = (jobs or {}).get(cid) or (jobs or {}).get(str(cid)) or db.execute(text(
            "SELECT max(id) FROM ingestion_job WHERE connection_id = :c AND state = 'extracted'"), {"c": cid}).scalar()
        job = job_row(db, int(job_id), organization_id) if job_id else None
        if job is None or job["connection_id"] != cid:
            raise RefreshRefused(f"Connection {cid} has no extraction to read; extract it first.")
        try:
            sheets[("db", cid)] = job_sheet(job, organization_id)
        except (artifacts.ArtifactUnavailable, artifacts.ArtifactChanged) as exc:
            raise RefreshRefused(f"Connection {cid}: {exc}") from None

    def sheet_of(b):
        return sheets[("file", b["file_name"]) if b["file_name"] else ("db", b["connection_id"])]

    report, changes = [], []
    for b in bound:
        src = sheet_of(b)["source"]
        change = compare(db, domain_id, b, sheet_of(b))
        changes.append((b, change))
        report.append({"binding_id": b["id"], "connection_id": b["connection_id"], "file_name": b["file_name"],
                       "source": b["connection"], "kind": b["kind"], "target": b["target"],
                       "from_job": b["job_id"], "job_id": src.get("job_id"),
                       "from_version": b["file_version"], "version": src.get("version"),
                       "extracted_at": src.get("extracted_at") or src.get("added_at"),
                       "same_extraction": b["sha256"] == src.get("sha256"), **shown(change)})
    total = sum(len(c["added"]) + len(c["changed"]) + (len(c["removed"]) if remove_missing else 0) for _, c in changes)
    if not apply:
        db.rollback()
        return {"applied": False, "changes": total, "bindings": report}
    written = []
    for b, change in changes:  # records first (bindings are ordered so), then links and values
        written.append(apply_change(db, domain_id, b, change, remove_missing))
        src = sheet_of(b)["source"]
        db.execute(text("UPDATE source_binding SET job_id = :j, file_version = :v, sha256 = :s, refreshed_at = now()"
                        " WHERE id = :id"),
                   {"j": src.get("job_id"), "v": src.get("version"), "s": src.get("sha256"), "id": b["id"]})
    if on_applied is not None:
        on_applied([{"id": r["binding_id"], "job_id": r["job_id"], "version": r["version"], **w}
                    for r, w in zip(report, written)])
    db.commit()
    for r, w in zip(report, written):
        r["written"] = w
    return {"applied": True, "changes": total, "bindings": report}


#: The most scenarios one refresh solves again.
SOLVE_AT_MOST = 20


def scenarios_reading(db: Session, domain_id: int, targets: set[str]) -> list[dict]:
    """The domain's scenarios whose model reads any of these kinds of record, relationship types or parameters."""
    found = []
    for row in db.execute(text(
            "SELECT s.id, s.name, s.problem_id, p.name AS problem, v.ir FROM scenario s JOIN problem p ON p.id = s.problem_id"
            " JOIN model_version v ON v.id = s.model_version_id WHERE p.domain_id = :d ORDER BY p.id, s.id"),
            {"d": domain_id}).mappings():
        ir = row["ir"] or {}
        names = set(ir.get("sets") or []) | set((ir.get("parameters") or {}).keys())
        rels = ir.get("relationships") or []
        names |= set(rels.keys() if isinstance(rels, dict) else
                     [r.get("name") if isinstance(r, dict) else r for r in rels])
        if names & targets:
            found.append({"scenario_id": row["id"], "scenario": row["name"], "problem_id": row["problem_id"],
                          "problem": row["problem"]})
    return found


def batch_share(db: Session, n: int) -> int | None:
    """The threads each of `n` re-solves asks for, so they solve side by side: the long lane's threads (the host's,
    less the reserve kept for short runs) over as many as run at once (the solve workers online, or `n` if fewer).
    None for a single run: it asks for what the settings say. Each asking for its full share, two of three
    re-solves fitted on a 16-thread host and the third waited (handover of 8 October 2026)."""
    from app.api.preflight import ONLINE_WITHIN_SECONDS
    from app.solve.reserve import host_capacity

    if n <= 1:
        return None
    online = db.execute(text("SELECT count(*) FROM worker_heartbeat WHERE last_seen > now() - make_interval(secs => :w)"),
                        {"w": ONLINE_WITHIN_SECONDS}).scalar() or 1
    capacity = host_capacity()
    lane = capacity.workers - int(capacity.workers * capacity.short_share)
    return max(1, lane // max(1, min(n, int(online))))


def solve_again(db: Session, domain_id: int, report: dict) -> list[dict]:
    """After an applied refresh: a new run of every scenario that reads the refreshed data, beside its last answer."""
    from app.solve.service import enqueue_run

    targets = {b["target"] for b in report.get("bindings") or []
               if (b.get("written") or {}).get("added") or (b.get("written") or {}).get("changed")
               or (b.get("written") or {}).get("removed")}
    runs = []
    chosen = scenarios_reading(db, domain_id, targets)[:SOLVE_AT_MOST]
    share = batch_share(db, len(chosen))
    for s in chosen:
        last = db.execute(text("SELECT id, objective FROM run WHERE scenario_id = :s AND status IN ('optimal', 'feasible')"
                               " ORDER BY id DESC LIMIT 1"), {"s": s["scenario_id"]}).first()
        try:
            run_id = enqueue_run(db, s["scenario_id"], workers=share)
            runs.append({**s, "run_id": run_id,
                         **({"previous_run_id": last.id, "previous_objective": float(last.objective)}
                            if last is not None and last.objective is not None else {})})
        except Exception as exc:  # noqa: BLE001 -- one scenario that cannot run does not stop the others
            db.rollback()
            runs.append({**s, "error": str(exc)[:300] or type(exc).__name__})
    return runs
