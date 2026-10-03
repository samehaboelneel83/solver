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

**6. The IR is validated against the contract.**  Since Phase 0 there is
one -- `docs/contracts/problem-ir.md`, with `backend/app/ir/contract.json`
as its machine-readable half -- and `app.ir.validate` judges every posted
document against it.  The rules themselves are exercised, one refusal per
rule, by `test_ir_validate.py` against the shared fixture file; what is
pinned *here* is only what this router adds: that the refusal arrives as
the platform's list-form 422 with `loc` naming the element, that nothing is
stored when it does, and that the domain half runs at all (an IR naming a
set this problem's domain does not have used to be accepted here and
become a 500 inside `snapshot_dataset()` much later).

**7. A scenario's patch names constraints its version has.**  Task 9's
recorded gap.  The `crossed` fixture's versions therefore declare three
constraints, `c_x`, `c_y` and `c_z`, which is what the patch tests below
name.

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
# Both are contract-valid IRs; the reordering is what the hashing test needs.
REORDERED_BODY_1 = (
    '{"ir": {"version": 1, "sets": ["day"], "parameters": {}, '
    '"variables": {"x": {"index": ["day"], "domain": "binary"}}, "constraints": []}, '
    '"note": null}'
)
REORDERED_BODY_2 = (
    '{"note":null,"ir":{"constraints":[],  "parameters":{},'
    '"variables":{"x":{"domain":"binary","index":["day"]}},"sets":["day"],"version":1}}'
)


def _ir(marker="x", *, set_name="day", constraint_ids=("c_x", "c_y", "c_z")):
    """A contract-valid IR (`docs/contracts/problem-ir.md`).

    Two versions used to be told apart by an arbitrary extra key --
    `{"sets": [], "n": "a1"}` -- which the contract refuses, because a key
    nothing reads is a model half that is silently ignored.  `marker`
    names the variable instead, so two documents still differ in content
    and still hash differently, and the difference is now something the
    IR actually means.
    """
    return {
        "version": 1,
        "sets": [set_name],
        "parameters": {},
        "variables": {marker: {"index": [set_name], "domain": "binary"}},
        "constraints": [
            {
                "id": constraint_id,
                "forall": [{"index": "i", "set": set_name}],
                "left": {"var": marker, "index": ["i"]},
                "relation": "<=",
                "right": {"const": 1},
                "severity": "hard",
            }
            for constraint_id in constraint_ids
        ],
    }


def _mini_ir():
    """The smallest model the contract admits, naming no set at all -- for
    the tests whose domain has no entity types in it."""
    return {
        "version": 1,
        "sets": [],
        "parameters": {},
        "variables": {"x": {"index": [], "domain": "binary"}},
        "constraints": [],
    }


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
    # `day` and `shift`, because the contract's domain half now resolves an
    # IR's `sets` against the problem's own domain at submit time. Without
    # them every version in this module would be a 422.
    for name in ("day", "shift"):
        made = client.post(
            "/api/v1/entity-types",
            json={"domain_id": created_id, "name": name, "role": "time"},
            headers=auth_headers,
        )
        assert made.status_code == 201, made.text
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


def test_creating_a_problem_names_the_caller_as_owner(client, auth_headers, domain_id):
    """Omitting `owner` used to store null. The caller is who started it."""
    settings = get_settings()
    response = client.post(
        "/api/problem/",
        json={"domain_id": domain_id, "name": f"owned-{uuid.uuid4().hex[:8]}"},
        headers=auth_headers,
    )
    assert response.status_code == 201, response.text
    assert response.json()["owner"] == settings.admin_username


def test_creating_a_problem_keeps_an_explicit_owner(client, auth_headers, domain_id):
    response = client.post(
        "/api/problem/",
        json={
            "domain_id": domain_id,
            "name": f"ops-owned-{uuid.uuid4().hex[:8]}",
            "owner": "ops",
        },
        headers=auth_headers,
    )
    assert response.status_code == 201, response.text
    assert response.json()["owner"] == "ops"


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
    a1 = _version(client, auth_headers, a, _ir("a1"))
    a2 = _version(client, auth_headers, a, _ir("a2"))
    b1 = _version(client, auth_headers, b, _ir("b1"))
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
    a1 = _version(client, auth_headers, a, _ir("v1"))
    b1 = _version(client, auth_headers, b, _ir("v1"))
    a2 = _version(client, auth_headers, a, _ir("v2"))
    b2 = _version(client, auth_headers, b, _ir("v2"))
    a3 = _version(client, auth_headers, a, _ir("v3"))

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
    ir = {
        **_ir("open", constraint_ids=()),
        "objective": {
            "sense": "minimize",
            "terms": [
                {
                    "id": "o_open",
                    "weight": 3,
                    "expression": {
                        "sum": {"var": "open", "index": ["i"]},
                        "over": [{"index": "i", "set": "day"}],
                    },
                }
            ],
        },
    }
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
        f"/api/v1/problems/{a}/versions", json={"ir": _mini_ir()}, headers=auth_headers
    )
    assert response.status_code == 201, response.text
    assert response.json()["note"] is None


def test_publishing_the_latest_model_again_makes_no_new_version(client, auth_headers, problems):
    """Benchmark round 4: two publishes without an edit made versions 2 and 3. The latest version is
    the answer (200); going back to an older model is still a new version, with that one's hash."""
    a, _ = problems
    ir = _ir("open")
    first = _version(client, auth_headers, a, ir)
    again = client.post(f"/api/v1/problems/{a}/versions", json={"ir": ir}, headers=auth_headers)
    assert again.status_code == 200, again.text
    assert again.json()["id"] == first["id"] and again.json()["version"] == 1

    other = _version(client, auth_headers, a, _ir("shut"))
    back = _version(client, auth_headers, a, ir)
    assert (other["version"], back["version"]) == (2, 3)
    assert back["ir_hash"] == first["ir_hash"] and back["id"] != first["id"]


def test_the_base_scenario_follows_a_new_version_and_others_stay(client, auth_headers, db, problems):
    """Benchmark round 4: versions 2-4 were published and "Solve again" kept solving version 1."""
    a, _ = problems
    one = _version(client, auth_headers, a, _ir("open"))
    made = {}
    for name, patch in (("Base", {}), ("strict", {"disable": ["c_x"]}), ("other", {})):
        got = client.post("/api/v1/scenarios", json={"problem_id": a, "model_version_id": one["id"], "name": name, "patch": patch},
                          headers=auth_headers)
        assert got.status_code == 201, got.text
        made[name] = got.json()["id"]
    two = _version(client, auth_headers, a, _ir("shut"))
    on = dict(db.execute(text("SELECT name, model_version_id FROM scenario WHERE problem_id = :p"), {"p": a}).all())
    assert on == {"Base": two["id"], "strict": one["id"], "other": one["id"]}


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
    # The same model, written differently: it is the latest version already.
    assert second.status_code == 200, second.text
    assert second.json()["id"] == first.json()["id"]

    assert first.json()["ir_hash"] == second.json()["ir_hash"]
    raw_hashes = {hashlib.sha256(b.encode()).hexdigest() for b in (body_1, body_2)}
    assert first.json()["ir_hash"] not in raw_hashes


def test_different_ir_gives_a_different_hash(client, auth_headers, problems):
    a, _ = problems
    first = _version(client, auth_headers, a, _ir("open", set_name="day"))
    second = _version(client, auth_headers, a, _ir("open", set_name="shift"))
    assert first["ir_hash"] != second["ir_hash"]


def test_client_cannot_choose_version_or_hash(client, auth_headers, db, problems):
    """The trigger only fills a NULL `version`, so a client-supplied one
    would be stored verbatim if it reached the INSERT."""
    a, _ = problems
    response = client.post(
        f"/api/v1/problems/{a}/versions",
        json={"ir": _mini_ir(), "version": 99, "ir_hash": "f" * 64},
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
        "/api/v1/problems/999999999/versions", json={"ir": _mini_ir()}, headers=auth_headers
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
    "broken,loc",
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
def test_the_ir_keys_snapshot_reads_are_shape_checked(
    client, auth_headers, db, problems, broken, loc
):
    """`snapshot_dataset()` iterates `ir.sets` with
    jsonb_array_elements_text and `ir.parameters` with jsonb_object_keys;
    either on the wrong shape raises SQLSTATE 22023, a 500 at snapshot
    time. These two rules predate the contract -- the contract adopted
    them rather than replacing them -- so they are still pinned here, at
    the route, as well as in `test_ir_validate.py`.

    Each case is an otherwise valid IR with one key replaced, so the
    refusal that comes back is the one the `loc` names."""
    a, _ = problems
    response = client.post(
        f"/api/v1/problems/{a}/versions",
        json={"ir": {**_mini_ir(), **broken}},
        headers=auth_headers,
    )
    assert response.status_code == 422, response.text
    assert response.json()["detail"][0]["loc"] == loc
    assert db.execute(
        text("SELECT count(*) FROM model_version WHERE problem_id = :p"), {"p": a}
    ).scalar_one() == 0


def test_the_ir_is_no_longer_free_form(client, auth_headers, db, problems):
    """The exact document this test used to ACCEPT. It names a constraint
    without expressing it and carries a top-level key nothing reads --
    which is what the seeded sketch did too, and what Phase 0 decided a
    frozen, content-hashed model version may not be."""
    a, _ = problems
    ir = {
        "sets": ["day"],
        "parameters": {"demand": {"index": ["day"]}},
        "constraints": [{"id": "c_cover", "anything": [1, None, {"x": True}]}],
        "whatever": "the compiler wants",
    }
    response = client.post(
        f"/api/v1/problems/{a}/versions", json={"ir": ir}, headers=auth_headers
    )
    assert response.status_code == 422, response.text
    assert response.json()["detail"][0]["loc"] == ["body", "ir", "version"]
    assert db.execute(
        text("SELECT count(*) FROM model_version WHERE problem_id = :p"), {"p": a}
    ).scalar_one() == 0


def test_an_ir_naming_a_set_the_domain_lacks_is_refused_here_not_at_snapshot_time(
    client, auth_headers, db, problems
):
    """THE HOLE THIS CLOSES. `snapshot_dataset()` raises `IR set "%" has
    no entity_type in this domain` as a bare RAISE EXCEPTION, i.e.
    SQLSTATE P0001, which `translate_db_error` does not attribute to a
    field -- so an IR accepted here surfaced as a 500 from whatever route
    eventually took a snapshot. The 422 names the element instead.

    The second half proves the two judgements agree: the same IR, forced
    into the table with raw SQL, still makes the function raise.
    """
    a, _ = problems
    ir = {**_mini_ir(), "sets": ["machine"]}
    response = client.post(
        f"/api/v1/problems/{a}/versions", json={"ir": ir}, headers=auth_headers
    )
    assert response.status_code == 422, response.text
    detail = response.json()["detail"][0]
    assert detail["loc"] == ["body", "ir", "sets", 0]
    assert "machine" in detail["msg"]
    assert db.execute(
        text("SELECT count(*) FROM model_version WHERE problem_id = :p"), {"p": a}
    ).scalar_one() == 0

    forced = db.execute(
        text(
            "INSERT INTO model_version (problem_id, ir) "
            "VALUES (:p, CAST(:ir AS jsonb)) RETURNING id"
        ),
        {"p": a, "ir": json.dumps(ir)},
    ).scalar_one()
    with pytest.raises(Exception) as exc:
        db.execute(text("SELECT snapshot_dataset(:v)"), {"v": forced})
    assert "no entity_type in this domain" in str(exc.value)
    db.rollback()


def test_an_ir_naming_a_parameter_the_domain_lacks_is_refused_too(
    client, auth_headers, problems
):
    a, _ = problems
    ir = {**_mini_ir(), "sets": ["day"], "parameters": {"supply": {"index": ["day"]}}}
    response = client.post(
        f"/api/v1/problems/{a}/versions", json={"ir": ir}, headers=auth_headers
    )
    assert response.status_code == 422, response.text
    assert response.json()["detail"][0]["loc"] == ["body", "ir", "parameters", "supply"]


def test_a_refusal_carries_the_value_it_refused(client, auth_headers, problems):
    """Ruling 19's shape: `loc`, `msg` and the offending `input`, exactly
    as FastAPI's own body validation produces it, so `formatApiError` and
    the per-field form errors need no special case."""
    a, _ = problems
    # "real" is a plausible mistake for "continuous", which is admitted since
    # migration 0015. The vocabulary is still closed; this test is about the
    # shape of the refusal, not about which word is outside it.
    ir = {**_mini_ir(), "variables": {"x": {"index": [], "domain": "real"}}}
    response = client.post(
        f"/api/v1/problems/{a}/versions", json={"ir": ir}, headers=auth_headers
    )
    assert response.status_code == 422, response.text
    detail = response.json()["detail"][0]
    assert detail["loc"] == ["body", "ir", "variables", "x", "domain"]
    assert detail["input"] == "real"
    assert detail["type"] == "value_error"
    assert "real" in detail["msg"]


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
    assert body["ir"] == _ir("a2")


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
    _version(client, auth_headers, a, _ir("v3"))
    _version(client, auth_headers, a, _ir("v4"))
    _version(client, auth_headers, b, _ir("vb"))  # must not appear

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
        json={"model_version_id": crossed["a2"], "name": "what-if-2", "patch": {"disable": ["c_x"]}},
        headers=auth_headers,
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["model_version_id"] == crossed["a2"]
    assert patched.json()["name"] == "what-if-2"
    # Replaced wholesale, not merged: the old harden/soften are gone.
    assert patched.json()["patch"] == {"disable": ["c_x"]}

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
    # Said in words, not as a database conflict (benchmark round 3).
    assert again.json()["detail"] == "There is already a scenario called “same” in this problem: choose another name."
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


@pytest.mark.parametrize(
    "patch,loc",
    [
        ({"disable": ["no_such_c"]}, ["body", "patch", "disable", 0]),
        ({"disable": ["c_x", "no_such_c"]}, ["body", "patch", "disable", 1]),
        ({"harden": ["no_such_c"]}, ["body", "patch", "harden", 0]),
        ({"soften": {"no_such_c": 5}}, ["body", "patch", "soften", "no_such_c"]),
        ({"soften": {"c_x": 5, "no_such_c": 5}}, ["body", "patch", "soften", "no_such_c"]),
    ],
)
def test_a_patch_id_the_version_does_not_declare_is_422(
    client, auth_headers, db, crossed, patch, loc
):
    """TASK 9'S RECORDED GAP, closed by the contract: before there was one,
    a misspelt id was stored and silently had no effect on the run.

    A list is addressed by position and a mapping by its key -- the same
    `loc` shape `test_patch_shape_is_validated` pins for the other patch
    rules. Each case names one good id beside the bad one where it can, so
    a check that refused the whole patch on any miss would still have to
    point at the right element."""
    response = _scenario_post(client, auth_headers, crossed["a"], crossed["a1"], "typo", patch)
    assert response.status_code == 422, response.text
    detail = response.json()["detail"][0]
    assert detail["loc"] == loc
    assert "no_such_c" in detail["msg"]
    # ... and the message says what the version does have, which is the
    # half of a refusal that tells you what to do next.
    assert "c_x" in detail["msg"]
    assert db.execute(
        text("SELECT count(*) FROM scenario WHERE problem_id = :p"), {"p": crossed["a"]}
    ).scalar_one() == 0


def test_a_patch_naming_the_versions_own_constraints_is_accepted(
    client, auth_headers, crossed
):
    response = _scenario_post(
        client,
        auth_headers,
        crossed["a"],
        crossed["a1"],
        "ok",
        {"disable": ["c_x"], "harden": ["c_y"], "soften": {"c_z": 3}},
    )
    assert response.status_code == 201, response.text


def test_repointing_a_scenario_can_orphan_a_patch_id_and_is_refused(
    client, auth_headers, crossed
):
    """The case a check that only ran on `patch` would miss: the patch is
    not touched at all, the version under it is. `a1` declares `c_x`; the
    version made here does not."""
    created = _scenario_post(
        client, auth_headers, crossed["a"], crossed["a1"], "s", {"disable": ["c_x"]}
    )
    assert created.status_code == 201, created.text
    other = _version(
        client, auth_headers, crossed["a"], _ir("later", constraint_ids=("c_other",))
    )
    response = client.patch(
        f"/api/v1/scenarios/{created.json()['id']}",
        json={"model_version_id": other["id"]},
        headers=auth_headers,
    )
    assert response.status_code == 422, response.text
    assert response.json()["detail"][0]["loc"] == ["body", "patch", "disable", 0]


def test_a_patch_on_a_pre_contract_version_is_not_checked(client, auth_headers, db, crossed):
    """`model_version` rows are immutable, so a version stored before the
    contract existed can never gain a `constraints` array -- there is
    nothing authoritative to check its scenarios against, and refusing
    them all would break every scenario on one. Written with raw SQL
    because this router can no longer create such a version."""
    legacy = db.execute(
        text(
            "INSERT INTO model_version (problem_id, ir) "
            "VALUES (:p, '{\"sets\": []}'::jsonb) RETURNING id"
        ),
        {"p": crossed["a"]},
    ).scalar_one()
    db.commit()
    response = _scenario_post(
        client, auth_headers, crossed["a"], legacy, "legacy", {"disable": ["whatever"]}
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
    # ... and so is the id, on PATCH as on POST.
    orphan = client.patch(
        f"/api/v1/scenarios/{created.json()['id']}",
        json={"patch": {"soften": {"no_such_c": 5}}},
        headers=auth_headers,
    )
    assert orphan.status_code == 422, orphan.text
    assert orphan.json()["detail"][0]["loc"] == ["body", "patch", "soften", "no_such_c"]


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
        v = _version(client, auth_headers, p, _mini_ir())
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



def test_a_scenario_may_change_a_rule_s_limit(client, auth_headers, crossed):
    """User trial: "what if the budget were 80,000?" without publishing a new version."""
    ok = _scenario_post(client, auth_headers, crossed["a"], crossed["a1"], "budget", {"set_limit": {"c_x": 2.5}})
    assert ok.status_code == 201, ok.text
    assert ok.json()["patch"] == {"set_limit": {"c_x": 2.5}}
    missing = _scenario_post(client, auth_headers, crossed["a"], crossed["a1"], "typo", {"set_limit": {"no_such_c": 3}})
    assert missing.status_code == 422 and missing.json()["detail"][0]["loc"] == ["body", "patch", "set_limit", "no_such_c"]


def test_set_limit_replaces_the_number_side_and_only_that():
    from app.api.problems import rule_limit
    from app.solve.service import patched

    ir = _ir("a1")
    ir["constraints"].append({"id": "c_sum", "left": {"const": 4}, "relation": ">=",
                              "right": {"var": "a1", "index": ["d"]}, "severity": "hard"})
    out = patched(ir, {"set_limit": {"c_x": 80000, "c_sum": 2.5}})
    rules = {c["id"]: c for c in out["constraints"]}
    assert rules["c_x"]["right"] == {"const": 80000} and rules["c_y"]["right"] == {"const": 1}
    assert rules["c_sum"]["left"] == {"const": 2.5}
    assert ir["constraints"][0]["right"] == {"const": 1}  # the version itself is untouched
    assert rule_limit({"left": {"var": "x"}, "right": {"par": "cap", "index": []}}) is None
