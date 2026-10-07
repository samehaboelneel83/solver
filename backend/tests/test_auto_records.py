"""Map data to records for a whole domain (app/gis/auto_records.py): every layer onto the kind it belongs to."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.main import app
from tests.test_tenancy import tenants  # noqa: F401
from tests.test_v1_problem_run import db  # noqa: F401


def _point(lon, lat, **props):
    return {"type": "Feature", "properties": props, "geometry": {"type": "Point", "coordinates": [lon, lat]}}


def _square(lon, lat, **props):
    d = 0.001
    ring = [[lon, lat], [lon + d, lat], [lon + d, lat + d], [lon, lat + d], [lon, lat]]
    return {"type": "Feature", "properties": props, "geometry": {"type": "Polygon", "coordinates": [ring]}}


SITE = {"type": "FeatureCollection", "features": [
    # Names records the domain already has (W1, W2) and one it does not (W9): the "well" kind, keyed by well_id.
    _point(31.20, 30.05, layer="WELLS_EXISTING", well_id="W1", depth=40, owner="north"),
    _point(31.21, 30.05, layer="WELLS_EXISTING", well_id="W2", depth=55, owner="south"),
    _point(31.22, 30.05, layer="WELLS_EXISTING", well_id="W9", depth=61, owner="south"),
    # Named like the "hospital" kind, which has no records yet.
    _point(31.23, 30.06, layer="Hospitals", name="Kasr", beds=900),
    # Like nothing in the domain: a new kind.
    _square(31.20, 30.07, layer="Parcels", parcel_no="P-1", zoning="farm"),
    _square(31.21, 30.07, layer="Parcels", parcel_no="P-2", zoning="farm"),
]}


@pytest.fixture
def domain(tenants):  # noqa: F811
    client = TestClient(app)
    spec = {"domain_name": "Water", "problem_name": "Wells",
            "seed": {"entity_types": [
                {"name": "well", "role": "resource", "attributes": [{"name": "depth", "data_type": "integer"}]},
                {"name": "hospital", "attributes": [{"name": "beds", "data_type": "integer"}]},
                {"name": "crew", "attributes": [{"name": "size", "data_type": "integer", "required": True}]}],
                "entities": [{"type": "well", "key": "W1", "attrs": {"depth": 38}},
                             {"type": "well", "key": "W2", "attrs": {"depth": 50}},
                             {"type": "crew", "key": "C1", "attrs": {"size": 4}}]},
            "ir": {"version": 2, "sets": ["well"], "parameters": {},
                   "variables": {"use": {"index": ["well"], "domain": "binary"}}, "constraints": []}}
    made = client.post("/api/v1/problems/from-spec", json=spec, headers=tenants["b"])
    assert made.status_code == 200, made.text
    domain_id = made.json()["domain_id"]
    up = client.post("/api/v1/gis/uploads", headers=tenants["b"], data={"domain_id": str(domain_id)},
                     files={"file": ("site.geojson", json.dumps(SITE), "application/geo+json")})
    assert up.status_code == 201, up.text
    ds = client.post("/api/v1/gis/datasets", headers=tenants["b"], json={
        "upload_id": up.json()["upload_id"], "domain_id": domain_id, "name": "Site survey",
        "placement": {"kind": "epsg", "code": 4326}})
    assert ds.status_code == 201, ds.text
    return client, tenants["b"], domain_id, ds.json()["id"]


def _by_layer(proposal):
    return {m["layer"]: m for m in proposal["mappings"]}


def test_every_layer_is_mapped_onto_the_kind_it_belongs_to(domain, db):
    client, headers, domain_id, _ = domain
    proposal = client.post(f"/api/v1/gis/domains/{domain_id}/records/propose", json={}, headers=headers)
    assert proposal.status_code == 200, proposal.text
    m = _by_layer(proposal.json())

    wells = m["WELLS_EXISTING"]
    assert (wells["action"], wells["type"], wells["key"]) == ("existing", "well", "well_id")
    assert (wells["updates"], wells["creates"]) == (2, 1)
    assert any("2 of 3 features name a well record" in r for r in wells["reasons"])
    fields = {f["property"]: f for f in wells["fields"]}
    assert fields["depth"]["name"] == "depth" and not fields["depth"]["new"] and not fields["depth"]["skip"]
    assert fields["owner"]["new"] and fields["owner"]["skip"]  # not a well field: left out unless asked

    assert (m["Hospitals"]["action"], m["Hospitals"]["type"]) == ("existing", "hospital")
    assert (m["Parcels"]["action"], m["Parcels"]["type"]) == ("new", "parcel")
    assert {f["name"] for f in m["Parcels"]["fields"] if not f["skip"]} >= {"zoning"}
    # Nothing was written.
    assert db.execute(text("SELECT count(*) FROM entity_type WHERE domain_id = :d AND name = 'parcel'"),
                      {"d": domain_id}).scalar() == 0


def test_applying_updates_existing_records_and_adds_the_rest_with_their_shapes(domain, db):
    client, headers, domain_id, _ = domain
    proposal = client.post(f"/api/v1/gis/domains/{domain_id}/records/propose", json={}, headers=headers).json()
    done = client.post(f"/api/v1/gis/domains/{domain_id}/records", json={"mappings": proposal["mappings"]}, headers=headers)
    assert done.status_code == 201, done.text
    results = {r["layer"]: r for r in done.json()["results"]}
    assert (results["WELLS_EXISTING"]["updated"], results["WELLS_EXISTING"]["made"]) == (2, 1)

    rows = {r["key"]: r["attrs"] for r in db.execute(text(
        "SELECT e.key, e.attrs FROM entity e JOIN entity_type t ON t.id = e.entity_type_id"
        " WHERE t.domain_id = :d AND t.name = 'well' ORDER BY e.key"), {"d": domain_id}).mappings()}
    assert set(rows) == {"W1", "W2", "W9"}
    assert rows["W1"]["depth"] == 40 and rows["W1"]["shape"]["type"] == "Point"  # refreshed from the map
    assert "owner" not in rows["W1"]
    parcels = db.execute(text("SELECT count(*), min(e.attrs->>'area_m2') FROM entity e JOIN entity_type t"
                              " ON t.id = e.entity_type_id WHERE t.domain_id = :d AND t.name = 'parcel'"),
                         {"d": domain_id}).one()
    assert parcels[0] == 2 and float(parcels[1]) > 10_000

    # Again: the same records, refreshed by key, none added.
    again = client.post(f"/api/v1/gis/domains/{domain_id}/records", json={"mappings": proposal["mappings"]}, headers=headers)
    assert {r["layer"]: r["made"] for r in again.json()["results"]} == {"WELLS_EXISTING": 0, "Hospitals": 0, "Parcels": 0}


def test_a_choice_maps_a_layer_again_or_leaves_it_out_and_faults_stop_everything(domain, db):
    client, headers, domain_id, dataset_id = domain
    redo = client.post(f"/api/v1/gis/domains/{domain_id}/records/propose", headers=headers, json={"choices": [
        {"dataset_id": dataset_id, "layer": "Parcels", "type": "crew"},
        {"dataset_id": dataset_id, "layer": "Hospitals", "type": None}]}).json()
    m = _by_layer(redo)
    assert m["Hospitals"]["action"] == "skip"
    crew = m["Parcels"]
    assert crew["type"] == "crew" and crew["required_unfilled"] == ["size"] and crew["create_missing"] is False

    wells = m["WELLS_EXISTING"]
    next(f for f in wells["fields"] if f["property"] == "owner").update({"skip": False, "name": "depth"})  # text into an integer
    refused = client.post(f"/api/v1/gis/domains/{domain_id}/records", json={"mappings": [wells]}, headers=headers)
    assert refused.status_code == 422 and refused.json()["detail"]["faults"]
    assert db.execute(text("SELECT count(*) FROM entity e JOIN entity_type t ON t.id = e.entity_type_id"
                           " WHERE t.domain_id = :d AND t.name = 'well'"), {"d": domain_id}).scalar() == 2


def test_only_editors_apply_and_only_their_own_domains(domain, tenants):  # noqa: F811
    client, headers, domain_id, _ = domain
    assert client.post(f"/api/v1/gis/domains/{domain_id}/records/propose", json={}, headers=tenants["a"]).status_code == 404
    assert client.post(f"/api/v1/gis/domains/{domain_id}/records", json={"mappings": [{"layer": "x"}]},
                       headers=tenants["a"]).status_code == 404


def test_a_chosen_key_is_used_and_counted(domain):
    client, headers, domain_id, dataset_id = domain
    m = _by_layer(client.post(f"/api/v1/gis/domains/{domain_id}/records/propose", headers=headers, json={"choices": [
        {"dataset_id": dataset_id, "layer": "WELLS_EXISTING", "type": "well", "key": "owner"}]}).json())
    wells = m["WELLS_EXISTING"]
    assert wells["key"] == "owner" and (wells["updates"], wells["creates"]) == (0, 3)
    assert any(f["property"] == "well_id" for f in wells["fields"])


def test_the_assistant_may_preview_the_mapping_in_problem_description_mode(domain, monkeypatch):
    from app.agent import core
    from app.api import agent as agent_api
    from tests.test_agent import ScriptedLLM, _chat, _in_process_caller

    client, headers, domain_id, _ = domain
    monkeypatch.setattr(agent_api, "make_caller", _in_process_caller)
    monkeypatch.setattr(core, "llm_chat", ScriptedLLM([
        ("call_api", {"method": "POST", "path": f"/api/v1/gis/domains/{domain_id}/records/propose", "body": {}}),
        ("call_api", {"method": "POST", "path": f"/api/v1/gis/domains/{domain_id}/records", "body": {"mappings": []}}),
        "Layer WELLS_EXISTING matches your wells.",
    ]))
    events = _chat(headers, mode="model", text="use my map data", context={"domain_id": domain_id})
    results = [e for e in events if e["type"] == "result"]
    assert results[0]["ok"] and "\"mappings\"" in results[0]["preview"]
    # Applying is data preparation, allowed since the camp-bed evaluation (DATA FIRST); an empty list is refused
    # by the endpoint itself, not by the mode.
    assert not results[1]["preview"].startswith("Refused") and '"status": 422' in results[1]["preview"]


def test_a_short_mapping_is_completed_from_the_proposal_and_a_bad_one_is_a_422_not_a_500(domain, db):
    """The camp test (October 2026): the Assistant sent {"layer", "type", "key", "fields": {"name": "feature"},
    "geometry": "geometry"}; the endpoint failed with a 500 twice and nothing was made from the drawing."""
    client, headers, domain_id, dataset_id = domain
    short = {"dataset_id": dataset_id, "layer": "Parcels", "type": "parcel", "key": "parcel_no",
             "fields": {"zone_use": "zoning"}, "geometry": "geometry"}
    done = client.post(f"/api/v1/gis/domains/{domain_id}/records", json={"mappings": [short]}, headers=headers)
    assert done.status_code == 201, done.text
    assert done.json()["results"][0]["made"] == 2
    rows = db.execute(text("SELECT e.key, e.attrs FROM entity e JOIN entity_type t ON t.id = e.entity_type_id"
                           " WHERE t.domain_id = :d AND t.name = 'parcel' ORDER BY e.key"), {"d": domain_id}).all()
    assert [r[0] for r in rows] == ["P-1", "P-2"] and rows[0][1]["zone_use"] == "farm"
    # Just the layer and the kind: everything else from the proposal.
    bare = client.post(f"/api/v1/gis/domains/{domain_id}/records", headers=headers, json={"mappings": [
        {"dataset_id": dataset_id, "layer": "Hospitals", "type": "hospital"}]})
    assert bare.status_code == 201, bare.text
    for wrong, says in (({"layer": "Parcels", "type": "parcel"}, '"dataset_id" is missing'),
                        ({"dataset_id": dataset_id, "layer": "Parcels", "type": "parcel", "fields": ["zoning"]},
                         '"fields" is neither'),
                        ({"dataset_id": dataset_id, "layer": "Parcels", "type": "parcel", "fields": {"x": "nope"}},
                         "has no column 'nope'"),
                        ({"dataset_id": dataset_id, "layer": "Nowhere", "type": "parcel"}, 'no layer "Nowhere"')):
        refused = client.post(f"/api/v1/gis/domains/{domain_id}/records", json={"mappings": [wrong]}, headers=headers)
        assert refused.status_code == 422, (wrong, refused.text)
        assert says in refused.json()["detail"]["faults"][0], refused.text
    assert client.post(f"/api/v1/gis/domains/{domain_id}/records", json={"mappings": ["Parcels"]},
                       headers=headers).status_code == 422
