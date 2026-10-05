"""Two general tools that read the platform itself (stdlib only, works offline inside the network).

describe_workspace(domain_id) -> the vocabulary that already exists: kinds of record with their
    attributes and counts, relationship types (from -> to), data values (parameters), map data
    with its coordinate system, problems. The model reads this before asking the user anything.
validate_ir(problem_id, ir) -> the platform's own validator. The model calls it before proposing a
    plan, reads the error ("there is no parameter called 'cap'...", "a filter names an attribute of the
    set its binding ranges over"...) and fixes the model. Endpoints verified on Problem Solver.
"""
import json
import os
import urllib.request

BASE = os.environ.get("PS_API", "http://localhost:3010")


def _call(path, token, method="GET", body=None):
    req = urllib.request.Request(BASE + path, method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}")
        except ValueError:
            return e.code, {"detail": str(e)}


def describe_workspace(domain_id, token):
    _, et = _call(f"/api/v1/entity-types?domain_id={domain_id}&limit=500", token)
    _, rt = _call(f"/api/v1/relationship-types?domain_id={domain_id}&limit=500", token)
    _, pa = _call(f"/api/v1/parameters?domain_id={domain_id}&limit=500", token)
    _, gis = _call(f"/api/v1/gis/datasets?domain_id={domain_id}", token)
    _, pr = _call(f"/api/problem/?limit=100&offset=0&f_domain_id={domain_id}", token)
    types = et.get("items", et) if isinstance(et, dict) else et
    names = {t["id"]: t["name"] for t in types}
    kinds = []
    for t in types:
        _, cnt = _call(f"/api/v1/entities?entity_type_id={t['id']}&limit=1", token)
        kinds.append({"name": t["name"], "records": cnt.get("total"),
                      "attributes": {a["name"]: a["data_type"] for a in t.get("attributes", [])}})
    rels = [{"name": r["name"], "from": names.get(r["from_type_id"]), "to": names.get(r["to_type_id"]),
             "cardinality": r.get("cardinality")} for r in (rt.get("items", rt) if isinstance(rt, dict) else rt)]
    params = [{"name": p.get("name"), "index": p.get("index") or p.get("entity_type_id"), "unit": p.get("unit")}
              for p in pa.get("items", [])]
    maps = [{"name": d["name"], "crs": (d.get("placement") or {}).get("code"), "layers": (d.get("stats") or {}).get("kinds")}
            for d in gis.get("items", [])]
    probs = [{"id": p["id"], "name": p["name"]} for p in (pr.get("items", pr) if isinstance(pr, dict) else pr)]
    return {"kinds_of_record": kinds, "relationships": rels, "data_values": params, "map_data": maps, "problems": probs}


def validate_ir(problem_id, ir, token):
    status, body = _call(f"/api/v1/problems/{problem_id}/versions/validate", token, "POST", {"ir": ir})
    if status == 200 and body.get("ok"):
        return {"ok": True}
    errs = []
    for d in body.get("detail", []) if isinstance(body.get("detail"), list) else [body]:
        loc = ".".join(str(x) for x in d.get("loc", [])[2:]) if isinstance(d, dict) else ""
        errs.append({"where": loc, "problem": d.get("msg", str(d)) if isinstance(d, dict) else str(d)})
    return {"ok": False, "errors": errs}


SCHEMAS = [
    {"type": "function", "function": {
        "name": "describe_workspace",
        "description": "List what this workspace already has: kinds of record (attributes, counts), relationship types, "
                       "data values, map data and coordinate systems, problems. Call it before asking the user anything.",
        "parameters": {"type": "object", "properties": {}, "required": []}}},
    {"type": "function", "function": {
        "name": "validate_ir",
        "description": "Check a model (problem IR: sets, relationships, variables, parameters, constraints, objective) "
                       "with the platform's validator before proposing or publishing it. Fix every error it reports.",
        "parameters": {"type": "object", "properties": {
            "problem_id": {"type": "integer"},
            "ir": {"type": "object"}}, "required": ["problem_id", "ir"]}}},
]
