"""Epic UX, U-4: from an extraction to domain data -- preview, validate against a mapping, load once, with lineage."""
from __future__ import annotations

import hashlib
import json
from uuid import uuid4

import pytest
from sqlalchemy import text

from app.core.db import SessionLocal
from tests.test_integrations import create, setup  # noqa: F401
from tests.test_tenancy import tenants  # noqa: F401
from tests.test_v1_problem_run import db, make_entity_type  # noqa: F401

ROWS = [
    {"staff_id": "n1", "full_name": "Ada", "hours": "37.5", "grade": 3},
    {"staff_id": "n2", "full_name": "Ben", "hours": "not a number", "grade": 2},
    {"staff_id": "n3", "full_name": "Cy", "hours": "20", "grade": 1},
]
GOOD = [ROWS[0], ROWS[2]]


def _artifact(root, organization_id, connection_id, rows, columns=None) -> str:
    identity = str(uuid4())
    folder = root / str(organization_id) / str(connection_id) / identity
    folder.mkdir(parents=True)
    lines = [(json.dumps(r, sort_keys=True, separators=(",", ":")) + "\n").encode() for r in rows]
    (folder / "rows.jsonl").write_bytes(b"".join(lines))
    manifest = {"format_version": 1, "id": identity, "columns": columns or ["staff_id", "full_name", "hours", "grade"],
                "source_object": "staff", "source_schema": [{"name": "hours", "type": "numeric"}],
                "rows": len(rows), "sha256": hashlib.sha256(b"".join(lines)).hexdigest(), "completed_at": "2026-09-29T00:00:00Z"}
    (folder / "manifest.json").write_text(json.dumps(manifest))
    return identity


@pytest.fixture
def extracted(setup, db, tmp_path, monkeypatch):  # noqa: F811
    client, body, tenants = setup
    monkeypatch.setenv("OAAS_INTEGRATION_OUTPUT", str(tmp_path))
    connection = create(setup)
    person = make_entity_type(db, body["domain_id"], f"nurse_{uuid4().hex[:6]}")
    db.execute(text("INSERT INTO attribute_def (entity_type_id, name, data_type) VALUES (:t, 'hours', 'number')"), {"t": person})
    db.commit()
    org, user = db.execute(text("SELECT organization_id, id FROM iam.user_account WHERE organization_id ="
                                " (SELECT organization_id FROM integration_connection WHERE id = :c) LIMIT 1"), {"c": connection}).one()

    def job(rows, columns=None):
        artifact = _artifact(tmp_path, org, connection, rows, columns)
        with SessionLocal() as s:
            identity = s.execute(text("INSERT INTO ingestion_job (connection_id, organization_id, requested_by, state, artifact_id,"
                                      " finished_at) VALUES (:c, :o, :u, 'extracted', CAST(:a AS uuid), now()) RETURNING id"),
                                 {"c": connection, "o": org, "u": user, "a": artifact}).scalar_one()
            s.commit()
        return identity

    yield client, tenants, connection, person, job, tmp_path
    with SessionLocal() as s:
        s.execute(text("DELETE FROM import_load"))
        s.execute(text("DELETE FROM import_validation"))
        s.execute(text("DELETE FROM parameter_def WHERE domain_id = :d AND name LIKE 'shift_len_%'"), {"d": body["domain_id"]})
        s.execute(text("DELETE FROM relationship_type WHERE domain_id = :d AND name LIKE 'works_on_%'"), {"d": body["domain_id"]})
        s.execute(text("DELETE FROM entity WHERE entity_type_id IN (SELECT id FROM entity_type WHERE domain_id = :d"
                       " AND name LIKE 'ward_%')"), {"d": body["domain_id"]})
        s.execute(text("DELETE FROM entity_type WHERE domain_id = :d AND name LIKE 'ward_%'"), {"d": body["domain_id"]})
        s.execute(text("DELETE FROM entity WHERE entity_type_id = :t"), {"t": person})
        s.commit()


MAPPING = {"columns": {"staff_id": "key", "full_name": "label", "hours": "hours"}}


def test_preview_shows_the_columns_and_first_rows(extracted):
    client, tenants, _, _, job, _ = extracted
    job_id = job(ROWS)
    preview = client.get(f"/api/v1/ingestion-jobs/{job_id}/preview?limit=2", headers=tenants["a"]).json()
    assert preview["columns"] == ["staff_id", "full_name", "hours", "grade"]
    assert preview["rows_total"] == 3 and len(preview["rows"]) == 2
    assert client.get(f"/api/v1/ingestion-jobs/{job_id}/preview", headers=tenants["b"]).status_code == 404


def test_validation_names_the_row_and_column_and_writes_nothing(extracted, db):  # noqa: F811
    client, tenants, _, person, job, _ = extracted
    job_id = job(ROWS)
    report = client.post(f"/api/v1/ingestion-jobs/{job_id}/validate", json={"entity_type_id": person, **MAPPING},
                         headers=tenants["a"]).json()
    assert report["ok"] is False and report["rows"] == 3
    assert report["faults"] == [{"row": 2, "column": "hours → hours", "message": report["faults"][0]["message"]}]
    assert "number" in report["faults"][0]["message"]
    assert db.execute(text("SELECT count(*) FROM entity WHERE entity_type_id = :t"), {"t": person}).scalar_one() == 0
    # A mapping onto a column the type does not have is a mapping fault, row 0.
    bad = client.post(f"/api/v1/ingestion-jobs/{job_id}/validate",
                      json={"entity_type_id": person, "columns": {"staff_id": "key", "grade": "seniority"}}, headers=tenants["a"]).json()
    assert bad["faults"][0]["row"] == 0 and bad["faults"][0]["message"].startswith("mapping:")
    # A source column the extraction does not have is refused outright.
    assert client.post(f"/api/v1/ingestion-jobs/{job_id}/validate", json={"entity_type_id": person, "columns": {"nope": "key"}},
                       headers=tenants["a"]).status_code == 422


def test_a_clean_validation_loads_once_with_its_lineage(extracted, db):  # noqa: F811
    client, tenants, connection, person, job, _ = extracted
    job_id = job(GOOD)
    report = client.post(f"/api/v1/ingestion-jobs/{job_id}/validate", json={"entity_type_id": person, **MAPPING},
                         headers=tenants["a"]).json()
    assert report["ok"] is True and report["would_write"] == 2
    loaded = client.post(f"/api/v1/ingestion-jobs/{job_id}/load", json={"validation_id": report["validation_id"]}, headers=tenants["a"])
    assert loaded.status_code == 200, loaded.text
    assert loaded.json()["rows_written"] == 2
    rows = db.execute(text("SELECT key, label, attrs FROM entity WHERE entity_type_id = :t ORDER BY key"), {"t": person}).all()
    assert [(r.key, r.label, float(r.attrs["hours"])) for r in rows] == [("n1", "Ada", 37.5), ("n3", "Cy", 20.0)]
    lineage = db.execute(text("SELECT artifact_sha256, mapping_hash, rows_written FROM import_load WHERE job_id = :j"), {"j": job_id}).one()
    assert lineage.artifact_sha256 == report["artifact_sha256"] and lineage.mapping_hash == report["mapping_hash"]
    assert lineage.rows_written == 2
    # Never twice for the same artifact and mapping.
    again = client.post(f"/api/v1/ingestion-jobs/{job_id}/load", json={"validation_id": report["validation_id"]}, headers=tenants["a"])
    assert again.status_code == 409 and "already loaded" in again.text
    # The job history shows the load.
    history = client.get(f"/api/v1/connections/{connection}/jobs", headers=tenants["a"]).json()
    assert history["items"][0]["loads"][0]["rows_written"] == 2


def test_a_failed_validation_cannot_be_loaded(extracted):
    client, tenants, _, person, job, _ = extracted
    job_id = job(ROWS)
    report = client.post(f"/api/v1/ingestion-jobs/{job_id}/validate", json={"entity_type_id": person, **MAPPING}, headers=tenants["a"]).json()
    refused = client.post(f"/api/v1/ingestion-jobs/{job_id}/load", json={"validation_id": report["validation_id"]}, headers=tenants["a"])
    assert refused.status_code == 409 and "did not validate clean" in refused.text


def test_rows_changed_after_validation_are_refused(extracted):
    client, tenants, connection, person, job, root = extracted
    job_id = job(GOOD)
    report = client.post(f"/api/v1/ingestion-jobs/{job_id}/validate", json={"entity_type_id": person, **MAPPING}, headers=tenants["a"]).json()
    rows_file = next(root.rglob("rows.jsonl"))
    rows_file.write_bytes(rows_file.read_bytes().replace(b"Ada", b"Eve"))
    refused = client.post(f"/api/v1/ingestion-jobs/{job_id}/load", json={"validation_id": report["validation_id"]}, headers=tenants["a"])
    assert refused.status_code == 409 and "changed" in refused.text


def test_a_job_with_nothing_extracted_has_nothing_to_preview(extracted):
    client, tenants, connection, _, _, _ = extracted
    queued = client.post(f"/api/v1/connections/{connection}/jobs", headers=tenants["a"]).json()["id"]
    assert client.get(f"/api/v1/ingestion-jobs/{queued}/preview", headers=tenants["a"]).status_code == 409


def _wards_and_nurses(db, person, domain_id):  # noqa: F811
    """Two nurses, two wards: what a link or a cell names by key."""
    ward = make_entity_type(db, domain_id, f"ward_{uuid4().hex[:6]}")
    for key, type_id in (("n1", person), ("n3", person), ("w1", ward), ("w2", ward)):
        db.execute(text("INSERT INTO entity (entity_type_id, key) VALUES (:t, :k)"), {"t": type_id, "k": key})
    db.commit()
    return ward


def test_rows_become_links_between_two_records_by_key(extracted, db):  # noqa: F811
    client, tenants, connection, person, job, _ = extracted
    domain_id = db.execute(text("SELECT domain_id FROM entity_type WHERE id = :t"), {"t": person}).scalar_one()
    ward = _wards_and_nurses(db, person, domain_id)
    rel = db.execute(text("INSERT INTO relationship_type (domain_id, name, from_type_id, to_type_id)"
                          " VALUES (:d, :n, :f, :t) RETURNING id"),
                     {"d": domain_id, "n": f"works_on_{uuid4().hex[:6]}", "f": person, "t": ward}).scalar_one()
    db.commit()
    columns = ["nurse", "ward_code"]
    bad_job = job([{"nurse": "n1", "ward_code": "w1"}, {"nurse": "n9", "ward_code": "w2"}], columns)
    mapping = {"relationship_type_id": rel, "columns": {"nurse": "from", "ward_code": "to"}}
    bad = client.post(f"/api/v1/ingestion-jobs/{bad_job}/validate", json=mapping, headers=tenants["a"]).json()
    assert bad["ok"] is False and bad["target"]["kind"] == "relationship_type"
    assert bad["faults"] == [{"row": 2, "column": "nurse → from", "message": "no from end has the key 'n9'"}]

    good_job = job([{"nurse": "n1", "ward_code": "w1"}, {"nurse": "n3", "ward_code": "w2"}], columns)
    report = client.post(f"/api/v1/ingestion-jobs/{good_job}/validate", json=mapping, headers=tenants["a"]).json()
    assert report["ok"] is True and report["would_write"] == 2 and report["noun"] == "links"
    loaded = client.post(f"/api/v1/ingestion-jobs/{good_job}/load", json={"validation_id": report["validation_id"]},
                         headers=tenants["a"])
    assert loaded.status_code == 200, loaded.text
    assert loaded.json()["rows_written"] == 2 and loaded.json()["target"]["id"] == rel
    links = db.execute(text("SELECT ef.key, et.key FROM relationship r JOIN entity ef ON ef.id = r.from_entity_id"
                            " JOIN entity et ON et.id = r.to_entity_id WHERE r.relationship_type_id = :r ORDER BY 1"),
                       {"r": rel}).all()
    assert [tuple(link) for link in links] == [("n1", "w1"), ("n3", "w2")]
    history = client.get(f"/api/v1/connections/{connection}/jobs", headers=tenants["a"]).json()
    load = next(item for item in history["items"] if item["id"] == good_job)["loads"][0]
    assert load["target"] == {"kind": "relationship_type", "id": rel, "name": loaded.json()["target"]["name"]}


def test_rows_become_a_parameter_s_cells(extracted, db):  # noqa: F811
    client, tenants, _, person, job, _ = extracted
    domain_id = db.execute(text("SELECT domain_id FROM entity_type WHERE id = :t"), {"t": person}).scalar_one()
    ward = _wards_and_nurses(db, person, domain_id)
    parameter = db.execute(text("INSERT INTO parameter_def (domain_id, name, index_type_ids, default_value)"
                                " VALUES (:d, :n, ARRAY[:p, :w]::bigint[], 8) RETURNING id"),
                           {"d": domain_id, "n": f"shift_len_{uuid4().hex[:6]}", "p": person, "w": ward}).scalar_one()
    db.commit()
    heads = db.execute(text("SELECT name FROM entity_type WHERE id IN (:p, :w) ORDER BY id"),
                       {"p": person, "w": ward}).scalars().all()
    columns = ["who", "where", "hours"]
    job_id = job([{"who": "n1", "where": "w1", "hours": "12"}, {"who": "n3", "where": "w2", "hours": "8"}], columns)
    mapping = {"parameter_id": parameter, "columns": {"who": heads[0], "where": heads[1], "hours": "value"}}
    report = client.post(f"/api/v1/ingestion-jobs/{job_id}/validate", json=mapping, headers=tenants["a"]).json()
    assert report["ok"] is True, report
    loaded = client.post(f"/api/v1/ingestion-jobs/{job_id}/load", json={"validation_id": report["validation_id"]},
                         headers=tenants["a"])
    assert loaded.status_code == 200, loaded.text
    # Sparse, as an upload: the default (8) is not stored.
    cells = db.execute(text("SELECT value FROM parameter_value WHERE parameter_def_id = :p"), {"p": parameter}).scalars().all()
    assert [float(v) for v in cells] == [12.0]


def test_a_mapping_names_exactly_one_target_of_its_own_domain(extracted, db):  # noqa: F811
    client, tenants, _, person, job, _ = extracted
    job_id = job(GOOD)
    both = client.post(f"/api/v1/ingestion-jobs/{job_id}/validate",
                       json={"entity_type_id": person, "parameter_id": 1, **MAPPING}, headers=tenants["a"])
    assert both.status_code == 422 and "exactly one" in both.text
    neither = client.post(f"/api/v1/ingestion-jobs/{job_id}/validate", json=MAPPING, headers=tenants["a"])
    assert neither.status_code == 422
    elsewhere = client.post(f"/api/v1/ingestion-jobs/{job_id}/validate",
                            json={"relationship_type_id": 999_999_999, **MAPPING}, headers=tenants["a"])
    assert elsewhere.status_code == 422 and "relationship type of this connection" in elsewhere.text
