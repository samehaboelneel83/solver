"""Model versions and scenarios (`app/api/problems.py`), plus one documented
gap in the schema.

What is pinned here, and why each is shaped the way it is:

**1. Numbering is per problem.**  Every numbering test uses *two* problems
and interleaves their versions.  "1 then 2" on a single fresh problem would
pass just as well if versions were numbered globally.

**2. Hashing is content-based, not byte-based.**  The same-hash test sends
the two IRs as *raw bodies* whose keys are in a different order and whose
whitespace differs, so a hash of the request bytes (or of Python's
insertion-ordered dict) could not pass it.  The returned hash is also
compared with the one the database stored, so a router that computed its
own hash instead of reading back `set_hash()`'s would fail.

**3. Server-assigned fields are read back, not assumed.**  `version` and
`ir_hash` are filled by BEFORE INSERT triggers, and the ORM does not know
it: a probe showed it sends explicit NULLs for both and then believes they
are still NULL after the flush.  Every create test asserts the response
against a direct query of the row.

**4. Immutability.**  PATCH, PUT and DELETE on a version are 405, the row
is proven unchanged afterwards, and no route anywhere on the app offers
those methods on a version path.

**5. Scenario/version consistency.**  The cross-problem fixture gives both
problems a version numbered 1, and the scenario points at the *other*
problem's version 1: a check that compared version numbers rather than
ownership would accept it.  Since migration 0009 the database enforces the
rule too (a composite FK); `test_database_refuses_a_scenario_on_another_problems_version`
proves it with raw SQL, bypassing this router.

**6. What only the platform reads is validated.**  `snapshot_dataset()`
reads `ir.sets` as an array of names and `ir.parameters` as an object; any
other shape makes it fail with SQLSTATE 22023, which surfaces as a 500 at
snapshot time.  So those two keys are checked, and nothing else in the IR.

Test hygiene: rows made through HTTP are committed by the app.  Everything
hangs off one `domain` row which the `domain_id` fixture deletes in a
`finally`; `ON DELETE CASCADE` from domain -> problem -> model_version /
scenario takes the rest (and `test_deleting_the_domain_cascades_cleanly`
proves that chain runs even though `scenario.model_version_id` has no
`ON DELETE` clause).  Raw-SQL tests use the `db` fixture, which only ever
rolls back.
"""

import hashlib
import json
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.crud.registry import TABLE_REGISTRY
from app.main import app
from app.models.v1_problem import IMMUTABLE_TABLES
from app.seed import seed_admin

# The same content, differing in key order at two levels and in whitespace.
REORDERED_BODY_1 = '{"ir": {"sets": ["day"], "objective": {"a": 1, "b": 2}}, "note": null}'
REORDERED_BODY_2 = '{"note":null,"ir":{"objective":{"b":2,"a":1},  "sets":["day"]}}'


@pytest.fixture(autouse=True)
def ensure_admin_seeded():
    db = SessionLocal()
    seed_admin(db)
    db.close()


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def auth_headers(client):
    settings = get_settings()
    response = client.post(
        "/api/auth/login",
        data={"username": settings.admin_username, "password": settings.admin_password},
    )
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def domain_id(client, auth_headers):
    """A throwaway domain, deleted in a `finally`. Everything a test makes
    hangs off it and cascades away with it."""
    response = client.post(
        "/api/domain/",
        json={"name": f"problem-test-{uuid.uuid4().hex[:8]}"},
        headers=auth_headers,
    )
    assert response.status_code == 201, response.text
    created_id = response.json()["id"]
    try:
        yield created_id
    finally:
        client.delete(f"/api/domain/{created_id}", headers=auth_headers)


@pytest.fixture
def db(domain_id):
    """A raw session that only ever rolls back. Depends on `domain_id` so it
    is torn down *before* the domain is deleted."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


def _problem(client, auth_headers, domain_id, name) -> int:
    response = client.post(
        "/api/problem/", json={"domain_id": domain_id, "name": name}, headers=auth_headers
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _version(client, auth_headers, problem_id, ir, note=None) -> dict:
    response = client.post(
        f"/api/v1/problems/{problem_id}/versions",
        json={"ir": ir, "note": note},
        headers=auth_headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


def _scenario_post(client, auth_headers, problem_id, model_version_id, name="base", patch=None):
    body = {"problem_id": problem_id, "model_version_id": model_version_id, "name": name}
    if patch is not None:
        body["patch"] = patch
    return client.post("/api/v1/scenarios", json=body, headers=auth_headers)


def _row(db, sql, **params):
    return db.execute(text(sql), params).mappings().one_or_none()


@pytest.fixture
def problems(client, auth_headers, domain_id):
    """Two problems, A and B."""
    return (
        _problem(client, auth_headers, domain_id, "roster-a"),
        _problem(client, auth_headers, domain_id, "roster-b"),
    )


@pytest.fixture
def crossed(client, auth_headers, problems):
    """A has versions 1 and 2, B has version 1. Both problems therefore own
    a version *numbered* 1, with different ids -- which is what lets the
    cross-problem tests tell "owned by this problem" apart from "this
    problem has a version with that number"."""
    a, b = problems
    a1 = _version(client, auth_headers, a, {"sets": [], "n": "a1"})
    a2 = _version(client, auth_headers, a, {"sets": [], "n": "a2"})
    b1 = _version(client, auth_headers, b, {"sets": [], "n": "b1"})
    assert (a1["version"], a2["version"], b1["version"]) == (1, 2, 1)
    assert len({a1["id"], a2["id"], b1["id"]}) == 3
    return {"a": a, "b": b, "a1": a1["id"], "a2": a2["id"], "b1": b1["id"]}


# --------------------------------------------------------------------------
# authentication and surface
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "method,path",
    [
        ("get", "/api/v1/problems/1/versions"),
        ("post", "/api/v1/problems/1/versions"),
        ("get", "/api/v1/versions/1"),
        ("get", "/api/v1/scenarios"),
        ("post", "/api/v1/scenarios"),
        ("get", "/api/v1/scenarios/1"),
        ("patch", "/api/v1/scenarios/1"),
        ("delete", "/api/v1/scenarios/1"),
    ],
)
def test_routes_require_authentication(client, method, path):
    kwargs = {"json": {}} if method in ("post", "patch") else {}
    assert getattr(client, method)(path, **kwargs).status_code == 401


def test_no_route_can_change_or_delete_a_version():
    """Static check over the whole app, not just this router: nothing may
    offer PUT, PATCH or DELETE on a path that addresses a model version."""
    offenders = [
        (route.path, sorted(route.methods))
        for route in app.routes
        if hasattr(route, "methods")
        and ("version" in route.path)
        and route.methods & {"PUT", "PATCH", "DELETE"}
    ]
    assert offenders == []


def test_model_version_is_not_in_the_generic_registry():
    registered = {meta.table for meta in TABLE_REGISTRY}
    assert "model_version" not in registered
    assert not (IMMUTABLE_TABLES & registered)


# --------------------------------------------------------------------------
# model versions: create
# --------------------------------------------------------------------------


def test_versions_are_numbered_per_problem(client, auth_headers, problems):
    """Interleaved across two problems: a global counter would give B's
    first version the number 2."""
    a, b = problems
    a1 = _version(client, auth_headers, a, {"sets": [], "n": 1})
    b1 = _version(client, auth_headers, b, {"sets": [], "n": 1})
    a2 = _version(client, auth_headers, a, {"sets": [], "n": 2})
    b2 = _version(client, auth_headers, b, {"sets": [], "n": 2})
    a3 = _version(client, auth_headers, a, {"sets": [], "n": 3})

    assert [a1["version"], a2["version"], a3["version"]] == [1, 2, 3]
    assert [b1["version"], b2["version"]] == [1, 2]
    assert {a1["problem_id"], a2["problem_id"], a3["problem_id"]} == {a}
    assert {b1["problem_id"], b2["problem_id"]} == {b}


def test_created_version_reports_what_the_database_stored(client, auth_headers, db, problems):
    a, _ = problems
    # jsonb orders keys by length first, then bytewise, so its canonical
    # text puts "sets" before "objective" -- the opposite of alphabetical.
    # With keys whose two orders agreed, a router hashing
    # json.dumps(ir, sort_keys=True) itself would produce the very same
    # digest and pass (mutant M2c survived exactly that way).
    ir = {"objective": {"weight": 3, "b": 2}, "sets": ["day"]}
    created = _version(client, auth_headers, a, ir, note="first cut")

    stored = _row(
        db,
        "SELECT problem_id, version, ir, ir_hash, note FROM model_version WHERE id = :i",
        i=created["id"],
    )
    assert stored is not None
    assert created["problem_id"] == stored["problem_id"] == a
    assert created["version"] == stored["version"] == 1
    assert created["ir_hash"] == stored["ir_hash"]
    assert created["ir"] == stored["ir"] == ir
    assert created["note"] == stored["note"] == "first cut"
    assert created["created_at"]
    # sha256 of jsonb's own canonical text, i.e. set_hash(), not a Python
    # re-serialisation of the request.
    canonical = db.execute(
        text("SELECT ir::text FROM model_version WHERE id = :i"), {"i": created["id"]}
    ).scalar_one()
    assert created["ir_hash"] == hashlib.sha256(canonical.encode()).hexdigest()


def test_note_is_optional(client, auth_headers, problems):
    a, _ = problems
    response = client.post(
        f"/api/v1/problems/{a}/versions", json={"ir": {}}, headers=auth_headers
    )
    assert response.status_code == 201, response.text
    assert response.json()["note"] is None


def test_identical_ir_twice_gives_two_versions_with_one_hash(client, auth_headers, problems):
    """Hashing is content-based, not a dedup: both inserts succeed."""
    a, _ = problems
    ir = {"sets": ["day", "shift"], "objective": {"a": 1, "b": 2}}
    first = _version(client, auth_headers, a, ir)
    second = _version(client, auth_headers, a, ir)

    assert first["id"] != second["id"]
    assert (first["version"], second["version"]) == (1, 2)
    assert first["ir_hash"] == second["ir_hash"]


def test_reordered_keys_and_whitespace_hash_the_same(client, auth_headers, problems):
    """Sent as raw bodies, so the bytes genuinely differ -- in key order at
    two levels and in whitespace. A hash of the request body, or of a
    Python dict serialised in insertion order, would differ."""
    a, _ = problems
    body_1, body_2 = REORDERED_BODY_1, REORDERED_BODY_2
    assert body_1 != body_2
    assert json.loads(body_1) == json.loads(body_2)
    headers = {**auth_headers, "Content-Type": "application/json"}

    first = client.post(f"/api/v1/problems/{a}/versions", content=body_1, headers=headers)
    second = client.post(f"/api/v1/problems/{a}/versions", content=body_2, headers=headers)
    assert first.status_code == 201, first.text
    assert second.status_code == 201, second.text

    assert first.json()["ir_hash"] == second.json()["ir_hash"]
    raw_hashes = {hashlib.sha256(b.encode()).hexdigest() for b in (body_1, body_2)}
    assert first.json()["ir_hash"] not in raw_hashes


def test_different_ir_gives_a_different_hash(client, auth_headers, problems):
    a, _ = problems
    first = _version(client, auth_headers, a, {"sets": ["day"]})
    second = _version(client, auth_headers, a, {"sets": ["shift"]})
    assert first["ir_hash"] != second["ir_hash"]


def test_client_cannot_choose_version_or_hash(client, auth_headers, db, problems):
    """The trigger only fills a NULL `version`, so a client-supplied one
    would be stored verbatim if it reached the INSERT."""
    a, _ = problems
    response = client.post(
        f"/api/v1/problems/{a}/versions",
        json={"ir": {"sets": []}, "version": 99, "ir_hash": "f" * 64},
        headers=auth_headers,
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["version"] == 1
    assert body["ir_hash"] != "f" * 64
    stored = _row(db, "SELECT version, ir_hash FROM model_version WHERE id = :i", i=body["id"])
    assert (stored["version"], stored["ir_hash"]) == (1, body["ir_hash"])


def test_version_for_an_unknown_problem_is_404(client, auth_headers):
    response = client.post(
        "/api/v1/problems/999999999/versions", json={"ir": {}}, headers=auth_headers
    )
    assert response.status_code == 404


@pytest.mark.parametrize("ir", [[], "ir", 3, None, True])
def test_ir_must_be_an_object(client, auth_headers, problems, ir):
    a, _ = problems
    response = client.post(
        f"/api/v1/problems/{a}/versions", json={"ir": ir}, headers=auth_headers
    )
    assert response.status_code == 422, response.text
    assert response.json()["detail"][0]["loc"][:2] == ["body", "ir"]


def test_ir_is_required(client, auth_headers, problems):
    a, _ = problems
    response = client.post(
        f"/api/v1/problems/{a}/versions", json={"note": "x"}, headers=auth_headers
    )
    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["body", "ir"]


@pytest.mark.parametrize(
    "ir,loc",
    [
        ({"sets": "day"}, ["body", "ir", "sets"]),
        ({"sets": None}, ["body", "ir", "sets"]),
        ({"sets": {"day": 1}}, ["body", "ir", "sets"]),
        ({"sets": ["day", 3]}, ["body", "ir", "sets", 1]),
        ({"parameters": ["demand"]}, ["body", "ir", "parameters"]),
        ({"parameters": None}, ["body", "ir", "parameters"]),
        ({"parameters": "demand"}, ["body", "ir", "parameters"]),
    ],
)
def test_the_ir_keys_snapshot_reads_are_shape_checked(client, auth_headers, db, problems, ir, loc):
    """`snapshot_dataset()` iterates `ir.sets` with
    jsonb_array_elements_text and `ir.parameters` with jsonb_object_keys;
    either on the wrong shape raises SQLSTATE 22023, a 500 at snapshot
    time. Refused here instead, and nothing is stored."""
    a, _ = problems
    response = client.post(
        f"/api/v1/problems/{a}/versions", json={"ir": ir}, headers=auth_headers
    )
    assert response.status_code == 422, response.text
    assert response.json()["detail"][0]["loc"] == loc
    assert db.execute(
        text("SELECT count(*) FROM model_version WHERE problem_id = :p"), {"p": a}
    ).scalar_one() == 0


def test_the_rest_of_the_ir_is_free_form(client, auth_headers, problems):
    a, _ = problems
    ir = {
        "sets": ["day"],
        "parameters": {"demand": {"index": ["day"]}},
        "constraints": [{"id": "c_cover", "anything": [1, None, {"x": True}]}],
        "whatever": "the compiler wants",
    }
    assert _version(client, auth_headers, a, ir)["ir"] == ir


# --------------------------------------------------------------------------
# model versions: read, and immutability
# --------------------------------------------------------------------------


def test_get_a_version(client, auth_headers, crossed):
    response = client.get(f"/api/v1/versions/{crossed['a2']}", headers=auth_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == crossed["a2"]
    assert body["problem_id"] == crossed["a"]
    assert body["version"] == 2
    assert body["ir"] == {"sets": [], "n": "a2"}


def test_unknown_version_is_404(client, auth_headers):
    assert client.get("/api/v1/versions/999999999", headers=auth_headers).status_code == 404


def test_list_versions_newest_first_by_number_not_id(client, auth_headers, problems):
    """Rows inserted directly with explicit numbers, in the order 2, 1, so
    id order and version order disagree. Then two through the API (3, 4).
    The list promises newest *version* first."""
    a, b = problems
    session = SessionLocal()
    try:
        for number in (2, 1):
            session.execute(
                text(
                    "INSERT INTO model_version (problem_id, version, ir) "
                    "VALUES (:p, :v, '{}'::jsonb)"
                ),
                {"p": a, "v": number},
            )
        session.commit()
    finally:
        session.close()
    _version(client, auth_headers, a, {"n": 3})
    _version(client, auth_headers, a, {"n": 4})
    _version(client, auth_headers, b, {"n": "b"})  # must not appear

    response = client.get(f"/api/v1/problems/{a}/versions", headers=auth_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 4
    assert [item["version"] for item in body["items"]] == [4, 3, 2, 1]
    assert {item["problem_id"] for item in body["items"]} == {a}
    # The list is a summary; the IR itself is fetched per version.
    assert all("ir" not in item for item in body["items"])
    assert all(len(item["ir_hash"]) == 64 for item in body["items"])

    page = client.get(
        f"/api/v1/problems/{a}/versions?limit=2&offset=1", headers=auth_headers
    ).json()
    assert [item["version"] for item in page["items"]] == [3, 2]
    assert page["total"] == 4


def test_list_versions_of_an_unknown_problem_is_404(client, auth_headers):
    response = client.get("/api/v1/problems/999999999/versions", headers=auth_headers)
    assert response.status_code == 404


@pytest.mark.parametrize("method", ["patch", "put", "delete"])
def test_a_version_cannot_be_changed_or_deleted(client, auth_headers, db, crossed, method):
    vid = crossed["a1"]
    before = _row(db, "SELECT version, ir, ir_hash, note FROM model_version WHERE id = :i", i=vid)

    kwargs = {"json": {"note": "edited", "ir": {"sets": ["x"]}}} if method != "delete" else {}
    response = getattr(client, method)(f"/api/v1/versions/{vid}", headers=auth_headers, **kwargs)
    assert response.status_code == 405

    db.rollback()  # fresh snapshot
    after = _row(db, "SELECT version, ir, ir_hash, note FROM model_version WHERE id = :i", i=vid)
    assert after == before


# --------------------------------------------------------------------------
# scenarios
# --------------------------------------------------------------------------


def test_scenario_crud(client, auth_headers, db, crossed):
    a = crossed["a"]
    patch = {"disable": ["c_x"], "harden": ["c_y"], "soften": {"c_z": 100}}
    created = _scenario_post(client, auth_headers, a, crossed["a1"], "what-if", patch)
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["problem_id"] == a
    assert body["model_version_id"] == crossed["a1"]
    assert body["name"] == "what-if"
    assert body["patch"] == patch
    assert body["created_at"]
    sid = body["id"]
    stored = _row(db, "SELECT patch, model_version_id FROM scenario WHERE id = :i", i=sid)
    assert stored["patch"] == patch

    fetched = client.get(f"/api/v1/scenarios/{sid}", headers=auth_headers)
    assert fetched.status_code == 200
    assert fetched.json() == body

    # Re-point to the problem's own later version, rename, replace the patch.
    patched = client.patch(
        f"/api/v1/scenarios/{sid}",
        json={"model_version_id": crossed["a2"], "name": "what-if-2", "patch": {"disable": ["c_q"]}},
        headers=auth_headers,
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["model_version_id"] == crossed["a2"]
    assert patched.json()["name"] == "what-if-2"
    # Replaced wholesale, not merged: the old harden/soften are gone.
    assert patched.json()["patch"] == {"disable": ["c_q"]}

    deleted = client.delete(f"/api/v1/scenarios/{sid}", headers=auth_headers)
    assert deleted.status_code == 204
    assert client.get(f"/api/v1/scenarios/{sid}", headers=auth_headers).status_code == 404


def test_patch_defaults_to_empty(client, auth_headers, crossed):
    response = _scenario_post(client, auth_headers, crossed["a"], crossed["a1"])
    assert response.status_code == 201, response.text
    assert response.json()["patch"] == {}


def test_unknown_scenario_is_404(client, auth_headers):
    for method in ("get", "patch", "delete"):
        kwargs = {"json": {"name": "x"}} if method == "patch" else {}
        response = getattr(client, method)("/api/v1/scenarios/999999999", headers=auth_headers, **kwargs)
        assert response.status_code == 404, method


def test_list_scenarios_by_problem(client, auth_headers, crossed):
    a, b = crossed["a"], crossed["b"]
    # Inserted so that id order and name order disagree.
    for name in ("zeta", "alpha", "mid"):
        assert _scenario_post(client, auth_headers, a, crossed["a1"], name).status_code == 201
    assert _scenario_post(client, auth_headers, b, crossed["b1"], "beta").status_code == 201

    body = client.get(f"/api/v1/scenarios?problem_id={a}", headers=auth_headers).json()
    assert body["total"] == 3
    assert [item["name"] for item in body["items"]] == ["alpha", "mid", "zeta"]

    by_version = client.get(
        f"/api/v1/scenarios?model_version_id={crossed['b1']}", headers=auth_headers
    ).json()
    assert [item["name"] for item in by_version["items"]] == ["beta"]


def test_scenario_on_another_problems_version_is_422(client, auth_headers, db, crossed):
    """A's scenario pointing at B's version *1* -- A also has a version 1,
    so only an ownership check refuses it."""
    response = _scenario_post(client, auth_headers, crossed["a"], crossed["b1"], "crossed")
    assert response.status_code == 422, response.text
    entry = response.json()["detail"][0]
    assert entry["loc"] == ["body", "model_version_id"]
    assert "kind" not in entry  # the router's refusal, not a trigger's
    assert db.execute(
        text("SELECT count(*) FROM scenario WHERE problem_id = :p"), {"p": crossed["a"]}
    ).scalar_one() == 0


def test_scenario_on_its_own_version_is_accepted(client, auth_headers, crossed):
    """The positive twin of the test above, on B's side: B's version 1 is
    fine for B."""
    response = _scenario_post(client, auth_headers, crossed["b"], crossed["b1"], "own")
    assert response.status_code == 201, response.text


def test_repointing_a_scenario_to_another_problems_version_is_422(
    client, auth_headers, db, crossed
):
    created = _scenario_post(client, auth_headers, crossed["a"], crossed["a2"], "s")
    sid = created.json()["id"]
    response = client.patch(
        f"/api/v1/scenarios/{sid}", json={"model_version_id": crossed["b1"]}, headers=auth_headers
    )
    assert response.status_code == 422, response.text
    assert response.json()["detail"][0]["loc"] == ["body", "model_version_id"]
    stored = _row(db, "SELECT model_version_id FROM scenario WHERE id = :i", i=sid)
    assert stored["model_version_id"] == crossed["a2"]


def test_scenario_on_an_unknown_version_is_422(client, auth_headers, crossed):
    response = _scenario_post(client, auth_headers, crossed["a"], 999999999, "ghost")
    assert response.status_code == 422, response.text
    assert response.json()["detail"][0]["loc"] == ["body", "model_version_id"]


def test_problem_id_is_not_patchable(client, auth_headers, db, crossed):
    created = _scenario_post(client, auth_headers, crossed["a"], crossed["a1"], "s")
    sid = created.json()["id"]
    response = client.patch(
        f"/api/v1/scenarios/{sid}",
        json={"problem_id": crossed["b"], "name": "renamed"},
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    assert response.json()["problem_id"] == crossed["a"]
    stored = _row(db, "SELECT problem_id, name FROM scenario WHERE id = :i", i=sid)
    assert (stored["problem_id"], stored["name"]) == (crossed["a"], "renamed")


@pytest.mark.parametrize("field", ["name", "model_version_id", "patch"])
def test_patch_null_for_a_not_null_column_is_422(client, auth_headers, crossed, field):
    created = _scenario_post(client, auth_headers, crossed["a"], crossed["a1"], "s")
    response = client.patch(
        f"/api/v1/scenarios/{created.json()['id']}", json={field: None}, headers=auth_headers
    )
    assert response.status_code == 422, response.text
    assert response.json()["detail"][0]["loc"] == ["body", field]
    # The message too: for `model_version_id`, a missing null check would
    # still 422 at the same `loc` -- as "model version None does not exist".
    assert "cannot be null" in response.json()["detail"][0]["msg"]


def test_duplicate_scenario_name_is_409_per_problem(client, auth_headers, crossed):
    assert _scenario_post(client, auth_headers, crossed["a"], crossed["a1"], "same").status_code == 201
    again = _scenario_post(client, auth_headers, crossed["a"], crossed["a2"], "same")
    assert again.status_code == 409, again.text
    # Unique per problem, not globally.
    other = _scenario_post(client, auth_headers, crossed["b"], crossed["b1"], "same")
    assert other.status_code == 201, other.text


@pytest.mark.parametrize(
    "patch,loc",
    [
        ({"remove": ["c_x"]}, ["body", "patch", "remove"]),
        ({"disable": "c_x"}, ["body", "patch", "disable"]),
        ({"disable": [1]}, ["body", "patch", "disable", 0]),
        ({"disable": [""]}, ["body", "patch", "disable", 0]),
        ({"harden": None}, ["body", "patch", "harden"]),
        ({"soften": ["c_z"]}, ["body", "patch", "soften"]),
        ({"soften": {"c_z": "100"}}, ["body", "patch", "soften", "c_z"]),
        ({"soften": {"c_z": 1.5}}, ["body", "patch", "soften", "c_z"]),
        ({"soften": {"c_z": 100.0}}, ["body", "patch", "soften", "c_z"]),
        ({"soften": {"c_z": True}}, ["body", "patch", "soften", "c_z"]),
        ({"soften": {"c_z": 0}}, ["body", "patch", "soften", "c_z"]),
        ({"soften": {"c_z": -5}}, ["body", "patch", "soften", "c_z"]),
        ({"soften": {"c_z": 2**63}}, ["body", "patch", "soften", "c_z"]),
        ({"soften": {"": 5}}, ["body", "patch", "soften"]),
        ([], ["body", "patch"]),
        ("disable", ["body", "patch"]),
    ],
)
def test_patch_shape_is_validated(client, auth_headers, db, crossed, patch, loc):
    response = _scenario_post(client, auth_headers, crossed["a"], crossed["a1"], "bad", patch)
    assert response.status_code == 422, response.text
    assert response.json()["detail"][0]["loc"][: len(loc)] == loc
    assert db.execute(
        text("SELECT count(*) FROM scenario WHERE problem_id = :p"), {"p": crossed["a"]}
    ).scalar_one() == 0


@pytest.mark.parametrize(
    "patch",
    [
        {"disable": ["c_x"], "harden": ["c_x"]},
        {"disable": ["c_x"], "soften": {"c_x": 5}},
        {"harden": ["c_x"], "soften": {"c_x": 5}},
        {"disable": ["c_x", "c_x"]},
        {"harden": ["c_y", "c_y"]},
    ],
)
def test_contradictory_or_repeated_ids_are_422(client, auth_headers, crossed, patch):
    """One constraint cannot be both disabled and hardened (or softened):
    which instruction wins would be up to the solver's patch order."""
    response = _scenario_post(client, auth_headers, crossed["a"], crossed["a1"], "bad", patch)
    assert response.status_code == 422, response.text
    assert response.json()["detail"][0]["loc"][:2] == ["body", "patch"]


def test_patch_ids_are_not_checked_against_the_ir(client, auth_headers, crossed):
    """Deliberate: the repository defines no IR schema, so there is nowhere
    authoritative to look constraint ids up. See the module docstring."""
    response = _scenario_post(
        client, auth_headers, crossed["a"], crossed["a1"], "typo", {"disable": ["no_such_c"]}
    )
    assert response.status_code == 201, response.text


def test_patching_the_patch_is_validated_too(client, auth_headers, crossed):
    created = _scenario_post(client, auth_headers, crossed["a"], crossed["a1"], "s")
    response = client.patch(
        f"/api/v1/scenarios/{created.json()['id']}",
        json={"patch": {"soften": {"c_z": 0}}},
        headers=auth_headers,
    )
    assert response.status_code == 422, response.text


# --------------------------------------------------------------------------
# cascades
# --------------------------------------------------------------------------


def test_deleting_a_problem_cascades_to_versions_and_scenarios(
    client, auth_headers, db, crossed
):
    """`scenario.model_version_id` has no ON DELETE clause (NO ACTION), but
    the scenario and its version are both deleted by the *same* cascade
    from `problem`, within one statement, so the version is never left
    referenced. (Mutation-checked: making that FK `ON DELETE RESTRICT` did
    not break this either, so the test pins the outcome, not the clause;
    dropping the CASCADE on `scenario.problem_id` does break it.)"""
    a = crossed["a"]
    sid = _scenario_post(client, auth_headers, a, crossed["a1"], "s").json()["id"]

    response = client.delete(f"/api/problem/{a}", headers=auth_headers)
    assert response.status_code == 204, response.text

    assert _row(db, "SELECT id FROM scenario WHERE id = :i", i=sid) is None
    assert db.execute(
        text("SELECT count(*) FROM model_version WHERE problem_id = :p"), {"p": a}
    ).scalar_one() == 0
    # B is untouched.
    assert _row(db, "SELECT id FROM model_version WHERE id = :i", i=crossed["b1"]) is not None


def test_deleting_the_domain_cascades_cleanly(client, auth_headers):
    """Our own domain, not the fixture's, so the delete's status can be
    asserted: the fixture's `finally` deliberately ignores it."""
    domain = client.post(
        "/api/domain/", json={"name": f"cascade-{uuid.uuid4().hex[:8]}"}, headers=auth_headers
    ).json()["id"]
    try:
        p = _problem(client, auth_headers, domain, "p")
        v = _version(client, auth_headers, p, {"sets": []})
        sid = _scenario_post(client, auth_headers, p, v["id"], "s").json()["id"]
        response = client.delete(f"/api/domain/{domain}", headers=auth_headers)
        assert response.status_code == 204, response.text
    finally:
        client.delete(f"/api/domain/{domain}", headers=auth_headers)

    session = SessionLocal()
    try:
        for sql, value in (
            ("SELECT count(*) FROM problem WHERE domain_id = :x", domain),
            ("SELECT count(*) FROM model_version WHERE id = :x", v["id"]),
            ("SELECT count(*) FROM scenario WHERE id = :x", sid),
        ):
            assert session.execute(text(sql), {"x": value}).scalar_one() == 0, sql
    finally:
        session.close()


# --------------------------------------------------------------------------
# The database enforces scenario/version consistency (migration 0009, rule 7)
# --------------------------------------------------------------------------


def test_database_refuses_a_scenario_on_another_problems_version(db, crossed):
    """Formerly Task 9's KNOWN GAP: `scenario.problem_id` and
    `scenario.model_version_id` were independent foreign keys, so raw SQL
    -- the Task 15 seed, a future worker -- could bypass the router's 422
    (`test_scenario_on_another_problems_version_is_422`) and store a
    scenario on another problem's version. That row also made problem B
    undeletable, since B's version was then referenced from outside B's
    cascade.

    Migration 0009 adds `UNIQUE (id, problem_id)` on `model_version` and
    the composite FK `scenario_version_same_problem_fkey`
    `(model_version_id, problem_id) REFERENCES model_version (id,
    problem_id)`, exactly the fix Task 9's mutant D2 proved. The crossed
    fixture's versions are both *numbered* 1, so a rule comparing numbers
    rather than ownership would still accept this row.
    """
    nested = db.begin_nested()
    with pytest.raises(IntegrityError) as exc:
        db.execute(
            text(
                "INSERT INTO scenario (problem_id, model_version_id, name) "
                "VALUES (:p, :m, 'inconsistent')"
            ),
            {"p": crossed["a"], "m": crossed["b1"]},
        )
    nested.rollback()
    assert exc.value.orig.pgcode == "23503"
    assert exc.value.orig.diag.constraint_name == "scenario_version_same_problem_fkey"

    # The legal row still goes in, and B stays deletable.
    sid = db.execute(
        text(
            "INSERT INTO scenario (problem_id, model_version_id, name) "
            "VALUES (:p, :m, 'consistent') RETURNING id"
        ),
        {"p": crossed["a"], "m": crossed["a2"]},
    ).scalar_one()
    assert _row(db, "SELECT problem_id FROM scenario WHERE id = :i", i=sid)["problem_id"] == crossed["a"]
    db.execute(text("DELETE FROM problem WHERE id = :p"), {"p": crossed["b"]})
    assert db.execute(
        text("SELECT count(*) FROM model_version WHERE id = :m"), {"m": crossed["b1"]}
    ).scalar_one() == 0

