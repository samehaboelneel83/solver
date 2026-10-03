"""Number fields made from a date, a text and a linked record (benchmark, October 2026): what a
predictor or a rule can read, made once on the records themselves."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app
from tests.test_tenancy import tenants  # noqa: F401
from tests.test_v1_problem_run import db  # noqa: F401


def test_dates_texts_and_links_become_number_fields(tenants, db):  # noqa: F811
    http, h, domain = TestClient(app), tenants["a"], tenants["domain_a"]

    def post(path, body, ok=(200, 201)):
        got = http.post(path, json=body, headers=h)
        assert got.status_code in ok, got.text
        return got.json()

    road = post("/api/v1/entity-types", {"domain_id": domain, "name": "road", "role": "location"})
    post(f"/api/v1/entity-types/{road['id']}/attributes", {"name": "lanes", "data_type": "integer"})
    obs = post("/api/v1/entity-types", {"domain_id": domain, "name": "obs", "role": "other"})
    for field in ({"name": "day", "data_type": "date"}, {"name": "weather", "data_type": "text"},
                  {"name": "road", "data_type": "reference", "target_type_id": road["id"]}):
        post(f"/api/v1/entity-types/{obs['id']}/attributes", field)
    post("/api/v1/entities", {"entity_type_id": road["id"], "key": "R1", "attrs": {"lanes": 4}})
    post("/api/v1/entities", {"entity_type_id": obs["id"], "key": "o1", "attrs": {"day": "2026-10-02", "weather": "Dust storm", "road": "R1"}})
    post("/api/v1/entities", {"entity_type_id": obs["id"], "key": "o2", "attrs": {"day": "2026-01-05", "weather": "clear"}})

    parts = post(f"/api/v1/entity-types/{obs['id']}/derive", {"op": "date_parts", "field": "day"})
    assert parts["made"] == ["day_weekday", "day_month", "day_day_of_year"] and parts["records"] == 2
    kinds = post(f"/api/v1/entity-types/{obs['id']}/derive", {"op": "categories", "field": "weather"})
    assert kinds["made"] == ["weather_clear", "weather_dust_storm"]
    linked = post(f"/api/v1/entity-types/{obs['id']}/derive", {"op": "from_link", "field": "road", "of": "lanes"})
    assert linked == {"made": ["road_lanes"], "records": 1, "left_empty": 1}

    items = {e["key"]: e["attrs"] for e in http.get("/api/v1/entities", params={"entity_type_id": obs["id"]}, headers=h).json()["items"]}
    assert items["o1"]["day_weekday"] == 4 and items["o1"]["day_month"] == 10  # a Friday in October
    assert items["o1"]["weather_dust_storm"] == 1 and items["o1"]["weather_clear"] == 0
    assert items["o1"]["road_lanes"] == 4 and "road_lanes" not in items["o2"]

    refused = http.post(f"/api/v1/entity-types/{obs['id']}/derive", json={"op": "date_parts", "field": "road"}, headers=h)
    assert refused.status_code == 422
    assert http.post(f"/api/v1/entity-types/{obs['id']}/derive", json={"op": "date_parts", "field": "day"},
                     headers=tenants["b"]).status_code in (403, 404)


def test_a_formula_over_a_record_s_numbers_becomes_a_field(tenants, db):  # noqa: F811
    """Benchmark, October 2026: volume / capacity and length / speed could not be written."""
    http, h, domain = TestClient(app), tenants["a"], tenants["domain_a"]
    road = http.post("/api/v1/entity-types", json={"domain_id": domain, "name": "link", "role": "location"}, headers=h).json()
    for name in ("volume", "capacity", "label_text"):
        http.post(f"/api/v1/entity-types/{road['id']}/attributes",
                  json={"name": name, "data_type": "text" if name == "label_text" else "number"}, headers=h)
    for key, attrs in (("a", {"volume": 900, "capacity": 1200}), ("b", {"volume": 300, "capacity": 0}), ("c", {"volume": 50})):
        http.post("/api/v1/entities", json={"entity_type_id": road["id"], "key": key, "attrs": attrs}, headers=h)
    path = f"/api/v1/entity-types/{road['id']}/derive"
    done = http.post(path, json={"op": "formula", "field": "vc_ratio", "formula": "volume / capacity"}, headers=h)
    assert done.status_code == 200, done.text
    assert done.json()["records"] == 1 and sorted(done.json()["empty"]) == ["b", "c"]  # no division by zero, nothing missing made up
    items = {e["key"]: e["attrs"] for e in http.get("/api/v1/entities", params={"entity_type_id": road["id"]}, headers=h).json()["items"]}
    assert items["a"]["vc_ratio"] == 0.75 and "vc_ratio" not in items["b"]
    for bad in ("volume / label_text", "__import__('os')", "volume ** 2", "volume /"):
        assert http.post(path, json={"op": "formula", "field": "x", "formula": bad}, headers=h).status_code == 422, bad


def test_totals_of_linked_records_become_a_field(tenants, db):  # noqa: F811
    """Benchmark, October 2026: calls per district were counted outside the app."""
    http, h, domain = TestClient(app), tenants["a"], tenants["domain_a"]

    def post(path, body):
        got = http.post(path, json=body, headers=h)
        assert got.status_code in (200, 201), got.text
        return got.json()

    district = post("/api/v1/entity-types", {"domain_id": domain, "name": "district", "role": "location"})
    call = post("/api/v1/entity-types", {"domain_id": domain, "name": "call", "role": "other"})
    post(f"/api/v1/entity-types/{call['id']}/attributes", {"name": "minutes", "data_type": "number"})
    post(f"/api/v1/entity-types/{call['id']}/attributes", {"name": "district", "data_type": "reference", "target_type_id": district["id"]})
    for key in ("north", "south", "east"):
        post("/api/v1/entities", {"entity_type_id": district["id"], "key": key, "attrs": {}})
    for key, where, minutes in (("c1", "north", 10), ("c2", "north", 30), ("c3", "south", 5), ("c4", None, 99)):
        post("/api/v1/entities", {"entity_type_id": call["id"], "key": key, "attrs": {"minutes": minutes, **({"district": where} if where else {})}})

    path = f"/api/v1/entity-types/{district['id']}/derive"
    assert post(path, {"op": "linked_total", "field": "calls", "from_kind": "call", "link": "district"})["records"] == 3
    post(path, {"op": "linked_total", "field": "minutes_total", "from_kind": "call", "link": "district", "how": "sum", "of": "minutes"})
    post(path, {"op": "linked_total", "field": "minutes_mean", "from_kind": "call", "link": "district", "how": "mean", "of": "minutes"})
    items = {e["key"]: e["attrs"] for e in http.get("/api/v1/entities", params={"entity_type_id": district["id"]}, headers=h).json()["items"]}
    assert (items["north"]["calls"], items["south"]["calls"], items["east"]["calls"]) == (2, 1, 0)
    assert items["north"]["minutes_total"] == 40 and items["east"]["minutes_total"] == 0
    assert items["north"]["minutes_mean"] == 20 and "minutes_mean" not in items["east"]  # no mean of nothing
    for bad in ({"from_kind": "call", "link": "minutes"}, {"from_kind": "nope", "link": "district"},
                {"from_kind": "call", "link": "district", "how": "sum"}):
        got = http.post(path, json={"op": "linked_total", "field": "x", **bad}, headers=h)
        assert got.status_code == 422, (bad, got.text)


def test_data_values_computed_by_lookup_and_by_comparison(tenants, db):  # noqa: F811
    """Benchmark, October 2026: suitability by soil and crop, and "not last year's crop", were
    worked out in a spreadsheet and uploaded."""
    http, h, domain = TestClient(app), tenants["a"], tenants["domain_a"]

    def post(path, body):
        got = http.post(path, json=body, headers=h)
        assert got.status_code in (200, 201), got.text
        return got.json()

    soil = post("/api/v1/entity-types", {"domain_id": domain, "name": "soil", "role": "other"})
    crop = post("/api/v1/entity-types", {"domain_id": domain, "name": "crop", "role": "other"})
    parcel = post("/api/v1/entity-types", {"domain_id": domain, "name": "parcel", "role": "location"})
    post(f"/api/v1/entity-types/{parcel['id']}/attributes", {"name": "soil", "data_type": "reference", "target_type_id": soil["id"]})
    post(f"/api/v1/entity-types/{parcel['id']}/attributes", {"name": "prev_crop", "data_type": "text"})
    ids = {}
    for kind, key in ((soil, "clay"), (soil, "sand"), (crop, "wheat"), (crop, "maize")):
        ids[key] = post("/api/v1/entities", {"entity_type_id": kind["id"], "key": key, "attrs": {}})["id"]
    for key, attrs in (("p1", {"soil": "clay", "prev_crop": "Wheat"}), ("p2", {"soil": "sand", "prev_crop": "maize"}), ("p3", {})):
        ids[key] = post("/api/v1/entities", {"entity_type_id": parcel["id"], "key": key, "attrs": attrs})["id"]
    suit = post("/api/v1/parameters", {"domain_id": domain, "name": "suitability", "index_type_ids": [soil["id"], crop["id"]], "default_value": 0})
    cells = [{"entity_ids": [ids[s], ids[c]], "value": v} for s, c, v in
             (("clay", "wheat", 0.9), ("clay", "maize", 0.4), ("sand", "wheat", 0.3), ("sand", "maize", 0.8))]
    assert http.put(f"/api/v1/parameters/{suit['id']}/values", json={"cells": cells}, headers=h).status_code == 200

    path = f"/api/v1/domains/{domain}/derive-value"
    made = post(path, {"op": "lookup", "name": "parcel_suit", "kind": "parcel", "field": "soil", "source": "suitability"})
    assert made["cells"] == 4 and made["index"] == [parcel["id"], crop["id"]]
    grid = http.get(f"/api/v1/parameters/{made['parameter_id']}/values", headers=h).json()
    values = {tuple(c["entity_ids"]): c["value"] for c in grid["cells"]}
    assert values[(ids["p1"], ids["wheat"])] == 0.9 and values[(ids["p2"], ids["maize"])] == 0.8
    assert (ids["p3"], ids["wheat"]) not in values  # no soil: the default, nothing made up

    rot = post(path, {"op": "compare", "name": "rotation_ok", "kind": "parcel", "field": "prev_crop", "other": "crop", "compare": "!="})
    assert rot["cells"] == 6
    grid = http.get(f"/api/v1/parameters/{rot['parameter_id']}/values", headers=h).json()
    values = {tuple(c["entity_ids"]): c["value"] for c in grid["cells"]}
    assert values[(ids["p1"], ids["wheat"])] == 0 and values[(ids["p1"], ids["maize"])] == 1
    assert values[(ids["p3"], ids["wheat"])] == 1

    assert http.post(path, json={"op": "compare", "name": "rotation_ok", "kind": "parcel", "field": "prev_crop", "other": "crop"},
                     headers=h).status_code == 409
    for bad in ({"op": "lookup", "name": "x1", "kind": "parcel", "field": "prev_crop", "source": "suitability"},
                {"op": "lookup", "name": "x2", "kind": "crop", "field": "soil", "source": "suitability"},
                {"op": "compare", "name": "x3", "kind": "parcel", "field": "prev_crop", "other": "nope"}):
        assert http.post(path, json=bad, headers=h).status_code == 422, bad
    assert http.post(path, json={"op": "compare", "name": "x4", "kind": "parcel", "field": "prev_crop", "other": "crop"},
                     headers=tenants["b"]).status_code in (403, 404, 422)


def test_a_value_is_read_through_a_relationship_from_either_end(tenants, db):  # noqa: F811
    """Benchmark re-test, October 2026: "read through a link" offered no links where the kinds were
    linked by relationships (from the map, imported), not by a link field. A cell in two districts
    takes the mean of theirs."""
    http, h, domain = TestClient(app), tenants["a"], tenants["domain_a"]

    def post(path, body):
        got = http.post(path, json=body, headers=h)
        assert got.status_code in (200, 201), got.text
        return got.json()

    district = post("/api/v1/entity-types", {"domain_id": domain, "name": "district", "role": "location"})
    cell = post("/api/v1/entity-types", {"domain_id": domain, "name": "cell", "role": "location"})
    hour = post("/api/v1/entity-types", {"domain_id": domain, "name": "hour", "role": "time"})
    ids = {k: post("/api/v1/entities", {"entity_type_id": t["id"], "key": k, "attrs": {}})["id"]
           for t, k in ((district, "d1"), (district, "d2"), (cell, "c1"), (cell, "c2"), (cell, "c3"), (hour, "h1"))}
    in_district = post("/api/v1/relationship-types", {"domain_id": domain, "name": "in_district", "from_type_id": cell["id"],
                                                      "to_type_id": district["id"]})
    for c, d in (("c1", "d1"), ("c2", "d1"), ("c2", "d2")):
        post("/api/v1/relationships", {"relationship_type_id": in_district["id"], "from_entity_id": ids[c], "to_entity_id": ids[d]})
    rate = post("/api/v1/parameters", {"domain_id": domain, "name": "call_rate", "index_type_ids": [district["id"], hour["id"]], "default_value": 0})
    http.put(f"/api/v1/parameters/{rate['id']}/values", json={"cells": [
        {"entity_ids": [ids["d1"], ids["h1"]], "value": 4}, {"entity_ids": [ids["d2"], ids["h1"]], "value": 8}]}, headers=h)

    made = post(f"/api/v1/domains/{domain}/derive-value",
                {"op": "lookup", "name": "cell_rate", "kind": "cell", "field": "in_district", "source": "call_rate"})
    values = {tuple(c["entity_ids"]): c["value"] for c in
              http.get(f"/api/v1/parameters/{made['parameter_id']}/values", headers=h).json()["cells"]}
    assert values == {(ids["c1"], ids["h1"]): 4, (ids["c2"], ids["h1"]): 6}  # c3 in no district: the default

    # From the district end: a district reads its cells' value (the mean of them).
    pop = post("/api/v1/parameters", {"domain_id": domain, "name": "cell_pop", "index_type_ids": [cell["id"]], "default_value": 0})
    http.put(f"/api/v1/parameters/{pop['id']}/values", json={"cells": [
        {"entity_ids": [ids["c1"]], "value": 10}, {"entity_ids": [ids["c2"]], "value": 20}]}, headers=h)
    back = post(f"/api/v1/domains/{domain}/derive-value",
                {"op": "lookup", "name": "district_pop", "kind": "district", "field": "in_district", "source": "cell_pop"})
    values = {tuple(c["entity_ids"]): c["value"] for c in
              http.get(f"/api/v1/parameters/{back['parameter_id']}/values", headers=h).json()["cells"]}
    assert values == {(ids["d1"],): 15, (ids["d2"],): 20}


def test_records_are_linked_by_a_code_they_hold(tenants, db):  # noqa: F811
    """Benchmark re-test, October 2026: call history was linked to districts by `dist_code` only through
    a links file made outside the app."""
    http, h, domain = TestClient(app), tenants["a"], tenants["domain_a"]

    def post(path, body):
        got = http.post(path, json=body, headers=h)
        assert got.status_code in (200, 201), got.text
        return got.json()

    district = post("/api/v1/entity-types", {"domain_id": domain, "name": "district", "role": "location"})
    post(f"/api/v1/entity-types/{district['id']}/attributes", {"name": "code", "data_type": "text"})
    call = post("/api/v1/entity-types", {"domain_id": domain, "name": "call", "role": "other"})
    post(f"/api/v1/entity-types/{call['id']}/attributes", {"name": "dist_code", "data_type": "text"})
    post(f"/api/v1/entity-types/{call['id']}/attributes", {"name": "district_name", "data_type": "text"})
    for key, label, code in (("D1", "Dokki", "GZ-01"), ("D2", "Imbaba", "GZ-02")):
        post("/api/v1/entities", {"entity_type_id": district["id"], "key": key, "label": label, "attrs": {"code": code}})
    for key, code, name in (("c1", "gz-01", "dokki"), ("c2", "GZ-02 ", "Imbaba"), ("c3", "GZ-99", "nowhere"), ("c4", None, None)):
        post("/api/v1/entities", {"entity_type_id": call["id"], "key": key, "attrs": {k: v for k, v in (("dist_code", code), ("district_name", name)) if v}})

    path = f"/api/v1/entity-types/{call['id']}/derive"
    by_code = post(path, {"op": "link_by", "field": "in_district", "of": "dist_code", "to_kind": "district", "match": "code"})
    assert by_code["records"] == 2 and by_code["unmatched"] == ["c3: GZ-99"]
    items = {e["key"]: e["attrs"] for e in http.get("/api/v1/entities", params={"entity_type_id": call["id"]}, headers=h).json()["items"]}
    assert items["c1"]["in_district"] == "D1" and items["c2"]["in_district"] == "D2" and "in_district" not in items["c4"]
    # The links are there for a model to walk, and a total of linked records reads them.
    totals = post(f"/api/v1/entity-types/{district['id']}/derive", {"op": "linked_total", "field": "calls", "from_kind": "call", "link": "in_district"})
    assert totals["records"] == 2
    # By name (the label), into the same link: computed again, it replaces.
    by_name = post(path, {"op": "link_by", "field": "in_district", "of": "district_name", "to_kind": "district"})
    assert by_name["records"] == 2
    refused = http.post(path, json={"op": "link_by", "field": "dist_code", "of": "dist_code", "to_kind": "district"}, headers=h)
    assert refused.status_code == 409


def test_yes_no_fields_merge_spellings_and_put_the_rarest_values_together(tenants, db):  # noqa: F811
    """Benchmark round 3: 13 crop names (Wheat and WHEAT among them) were refused outright."""
    http, h, domain = TestClient(app), tenants["a"], tenants["domain_a"]
    obs = http.post("/api/v1/entity-types", json={"domain_id": domain, "name": "yield_row", "role": "other"}, headers=h).json()
    http.post(f"/api/v1/entity-types/{obs['id']}/attributes", json={"name": "crop", "data_type": "text"}, headers=h)
    crops = ["Wheat", "WHEAT ", "wheat"] + [f"crop {i}" for i in range(13) for _ in range(2)] + ["rare"]
    for i, crop in enumerate(crops):
        http.post("/api/v1/entities", json={"entity_type_id": obs["id"], "key": f"r{i}", "attrs": {"crop": crop}}, headers=h)
    done = http.post(f"/api/v1/entity-types/{obs['id']}/derive", json={"op": "categories", "field": "crop"}, headers=h)
    assert done.status_code == 200, done.text
    made = done.json()["made"]
    # 15 values once spellings are one: the 11 most common get a field each, the other 4 share crop_other.
    assert len(made) == 12 and made[-1] == "crop_other" and "crop_wheat" in made and "crop_rare" not in made
    assert done.json()["notes"] == ["4 rarer values of crop share crop_other"]
    items = {e["key"]: e["attrs"] for e in http.get("/api/v1/entities", params={"entity_type_id": obs["id"], "limit": 100}, headers=h).json()["items"]}
    assert items["r1"]["crop_wheat"] == 1 and items[f"r{len(crops) - 1}"]["crop_other"] == 1
