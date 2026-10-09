"""`join` (network design): the links built join the places -- checked against brute force and against NetworkX.

Every place joined: the spanning lane (Kruskal) is the minimum spanning tree NetworkX finds and the optimum a MIP
solver proves on the flow rows. Every place joined to a source: the minimum spanning forest. With `use`, which
places to join is the model's choice: the flow rows agree with brute force over every set of links.
"""
from __future__ import annotations

import itertools
import json
import random

import networkx as nx
import pytest

from app.ir.validate import check_shape
from app.solve import compile_model, join
from app.solve.backends import by_name
from app.solve.compile import Unsupported
from app.solve.service import solve_compiled


def _graph(n: int, seed: int, extra: float = 0.35):
    """A connected random graph on n places (a random tree plus extra links), with a cost per link."""
    rnd = random.Random(seed)
    places = [f"p{i}" for i in range(n)]
    pairs = {(places[rnd.randrange(i)], places[i]) for i in range(1, n)}
    for a, b in itertools.combinations(places, 2):
        if rnd.random() < extra:
            pairs.add((a, b))
    links = [(f"l{i}", a, b, rnd.randint(-2 if seed % 3 == 0 else 1, 20)) for i, (a, b) in enumerate(sorted(pairs))]
    return places, links


def _model(places, links, *, sources=None, use=False, prize=None, required=(), forced=(), banned=(),
           sense="minimize"):
    ir = {
        "version": 2, "sets": ["site", "segment"], "relationships": ["seg_a", "seg_b"],
        "parameters": {"cost": {"index": ["segment"]}},
        "variables": {"lay": {"index": ["segment"], "domain": "binary"}},
        "constraints": [{"id": "c_join", "severity": "hard", "join": {
            "links": {"index": "l", "set": "segment"}, "build": {"var": "lay", "index": ["l"]},
            "ends": ["seg_a", "seg_b"], "places": {"index": "p", "set": "site"}}}],
        "objective": {"sense": sense, "terms": [{"id": "o_cost", "weight": 1 if sense == "minimize" else -1,
                                                 "expression": {"sum": {"mul": [{"par": "cost", "index": ["l"]},
                                                                                {"var": "lay", "index": ["l"]}]},
                                                                "over": [{"index": "l", "set": "segment"}]}}]},
    }
    body = ir["constraints"][0]["join"]
    if sources is not None:
        body["sources"] = "exchange"
    if use:
        ir["variables"]["serve"] = {"index": ["site"], "domain": "binary"}
        body["use"] = {"var": "serve", "index": ["p"]}
        ir["parameters"]["prize"] = {"index": ["site"]}
        ir["parameters"]["required"] = {"index": ["site"]}
        ir["objective"]["terms"].append({"id": "o_prize", "weight": -1, "expression": {
            "sum": {"mul": [{"par": "prize", "index": ["p"]}, {"var": "serve", "index": ["p"]}]},
            "over": [{"index": "p", "set": "site"}]}})
        ir["constraints"].append({"id": "c_required", "severity": "hard", "forall": [{"index": "p", "set": "site"}],
                                  "left": {"var": "serve", "index": ["p"]}, "relation": ">=",
                                  "right": {"par": "required", "index": ["p"]}})
    ir["parameters"].update({"forced": {"index": ["segment"]}, "banned": {"index": ["segment"]}})
    ir["constraints"] += [
        {"id": "c_forced", "severity": "hard", "forall": [{"index": "l", "set": "segment"}],
         "left": {"var": "lay", "index": ["l"]}, "relation": ">=", "right": {"par": "forced", "index": ["l"]}},
        {"id": "c_banned", "severity": "hard", "forall": [{"index": "l", "set": "segment"}],
         "left": {"mul": [{"par": "banned", "index": ["l"]}, {"var": "lay", "index": ["l"]}]}, "relation": "<=",
         "right": {"const": 0}}]
    data = {
        "sets": {"site": [{"id": p, "exchange": 1 if sources and p in sources else 0} for p in places],
                 "segment": [{"id": l} for l, *_ in links]},
        "parameters": {"cost": [{"segment": l, "value": c} for l, _, _, c in links],
                       "forced": [{"segment": l, "value": 1 if l in forced else 0} for l, *_ in links],
                       "banned": [{"segment": l, "value": 1 if l in banned else 0} for l, *_ in links]},
        "parameter_defaults": {},
        "relationships": {"seg_a": [{"from": l, "to": a} for l, a, _, _ in links],
                          "seg_b": [{"from": l, "to": b} for l, _, b, _ in links]},
    }
    if use:
        data["parameters"]["prize"] = [{"site": p, "value": (prize or {}).get(p, 0)} for p in places]
        data["parameters"]["required"] = [{"site": p, "value": 1 if p in required else 0} for p in places]
    return ir, data


def _holds(compiled, values) -> bool:
    for c in compiled.constraints:
        left = float(c.left.evaluated_at(values)) - float(c.right.evaluated_at(values))
        if (c.relation == "<=" and left > 1e-9) or (c.relation == ">=" and left < -1e-9) or (
                c.relation in ("=", "==") and abs(left) > 1e-9):
            return False
    return True


def _mip(compiled, backend="highs"):
    result, _ = solve_compiled(by_name(backend), compiled, time_limit=60, seed=1, workers=1)
    return result


def _nx_mst(places, links, sources=None, forced=(), banned=()):
    """The expected cost: paying and forced links taken, the rest a minimum spanning forest (NetworkX)."""
    taken = 0
    union = nx.utils.UnionFind(places + ["root"])
    for s_ in sources or ():
        union.union("root", s_)
    for l, a, b, c in links:
        if l not in banned and (l in forced or c < 0):
            taken += c
            union.union(a, b)
    graph = nx.MultiGraph()
    for l, a, b, c in links:
        if l not in banned and not (l in forced or c < 0):
            graph.add_edge(union[a], union[b], weight=c)
    contracted = nx.Graph()
    contracted.add_nodes_from({union[p] for p in places + (["root"] if sources else [])})
    for a, b, d in graph.edges(data=True):
        if a != b and (not contracted.has_edge(a, b) or contracted[a][b]["weight"] > d["weight"]):
            contracted.add_edge(a, b, weight=d["weight"])
    if not nx.is_connected(contracted):
        return None
    return taken + sum(d["weight"] for _, _, d in nx.minimum_spanning_edges(contracted, data=True))


def test_the_rule_is_valid_and_its_mistakes_are_said():
    places, links = _graph(5, 1)
    ir, _ = _model(places, links, sources={"p0"}, use=True)
    assert check_shape(ir) is None
    body = ir["constraints"][0]["join"]
    for change, code in (({"ends": "seg_a"}, "join_malformed"), ({"ends": ["seg_a", "nope"]}, "join_ends_invalid"),
                         ({"build": {"var": "lay", "index": ["p"]}}, "join_index_mismatch"),
                         ({"extra": 1}, "join_malformed"), ({"sources": 3}, "join_malformed"),
                         ({"use": {"var": "lay", "index": ["p"]}}, None)):
        ir["constraints"][0]["join"] = {**body, **change}
        refused = check_shape(ir)
        if code is None:
            assert refused is not None  # lay is indexed by segment, read per site
        else:
            assert refused is not None and refused.code == code, (change, refused)
    ir["constraints"][0]["join"] = {k: v for k, v in body.items() if k != "places"}
    assert check_shape(ir).code == "join_malformed"
    ir["constraints"][0]["join"] = body
    ir["constraints"][0]["severity"] = "soft"
    ir["constraints"][0]["weight"] = 3
    assert check_shape(ir).code == "join_on_soft"
    ir["constraints"][0].pop("weight")
    ir["constraints"][0]["severity"] = "hard"
    ir["variables"]["serve"]["domain"] = "integer"
    assert check_shape(ir).code == "join_not_binary"
    v1 = dict(ir, version=1)
    assert check_shape(v1) is not None


@pytest.mark.parametrize("seed", range(10))
def test_every_place_joined_is_the_minimum_spanning_tree(seed):
    places, links = _graph(8, seed)
    compiled = compile_model(*_model(places, links))
    assert join.applies(compiled) is None
    ours = join.solve(compiled).solution
    assert ours.status == "optimal" and ours.optimal
    assert ours.objective == _nx_mst(places, links)
    assert _holds(compiled, ours.assignments)  # the flow it sets keeps every row
    if seed < 4:
        theirs = _mip(compiled, "highs" if seed % 2 else "cp-sat")
        assert theirs.status == "optimal" and round(float(theirs.objective)) == ours.objective


@pytest.mark.parametrize("seed", range(8))
def test_every_place_joined_to_a_source_is_the_minimum_spanning_forest(seed):
    places, links = _graph(9, 100 + seed)
    sources = {"p0", places[-1]} if seed % 2 else {"p3"}
    forced = [links[seed % len(links)][0]] if seed % 3 == 1 else []
    banned = [links[(seed * 7) % len(links)][0]] if seed % 3 == 2 else []
    banned = [l for l in banned if l not in forced]
    compiled = compile_model(*_model(places, links, sources=sources, forced=forced, banned=banned))
    assert join.applies(compiled) is None
    ours = join.solve(compiled).solution
    expected = _nx_mst(places, links, sources, forced, banned)
    if expected is None:
        assert ours.status == "infeasible"
        return
    assert ours.status == "optimal" and ours.objective == expected
    assert _holds(compiled, ours.assignments)
    theirs = _mip(compiled)
    assert theirs.status == "optimal" and round(float(theirs.objective)) == expected


def test_a_maximized_goal_and_the_networkx_solver_by_name():
    places, links = _graph(7, 5)
    ir, data = _model(places, links, sense="maximize")
    compiled = compile_model(ir, data)
    result, _ = solve_compiled(by_name("networkx"), compiled, time_limit=10, seed=1)
    assert result.status == "optimal" and "Kruskal" in result.solver
    assert -result.objective == _nx_mst(places, links)


def test_places_no_link_can_join_are_said_before_solving():
    places, links = _graph(6, 2)
    links = [*links, ("lonely", "q1", "q2", 3)]
    ir, data = _model([*places, "q1", "q2"], links)
    with pytest.raises(Unsupported, match="no links could join"):
        compile_model(ir, data)
    ir, data = _model([*places, "q1", "q2"], links, sources={"p0"})
    with pytest.raises(Unsupported, match="never be joined to a source"):
        compile_model(ir, data)
    ir, data = _model([*places, "q1", "q2"], links, sources={"p9"})
    with pytest.raises(Unsupported, match="is a source"):
        compile_model(ir, data)


def test_banning_a_bridge_is_proven_impossible():
    places = ["a", "b", "c"]
    links = [("ab", "a", "b", 1), ("bc", "b", "c", 1)]
    compiled = compile_model(*_model(places, links, banned=["bc"]))
    assert join.solve(compiled).solution.status == "infeasible"
    assert _mip(compiled).status == "infeasible"


def _brute_use(places, links, sources, prize, required):
    """The best of every set of links: the places used are its ends (a component each reaching a source, or one
    component) plus sources or a lone place worth keeping."""
    best = None
    for k in range(len(links) + 1):
        for chosen in itertools.combinations(links, k):
            g = nx.Graph()
            g.add_edges_from((a, b) for _, a, b, _ in chosen)
            parts = list(nx.connected_components(g)) if chosen else []
            if sources is None:
                if len(parts) > 1:
                    continue
                used_sets = [set(parts[0])] if parts else [set()] + [{p} for p in places]
            else:
                if any(not (part & sources) for part in parts):
                    continue
                base = set().union(*parts) if parts else set()
                extra = {s for s in sources if s not in base and prize.get(s, 0) > 0}
                used_sets = [base | extra | {s for s in sources if s in required}]
            cost = sum(c for _, _, _, c in chosen)
            for used in used_sets:
                if not set(required) <= used:
                    continue
                value = cost - sum(prize.get(p, 0) for p in used)
                best = value if best is None else min(best, value)
    return best


@pytest.mark.parametrize("seed", range(8))
def test_with_use_the_flow_agrees_with_every_set_of_links(seed):
    rnd = random.Random(seed)
    places, links = _graph(6, 200 + seed, extra=0.15)
    links = links[:9]
    sources = {"p0"} if seed % 2 else None
    prize = {p: rnd.randint(0, 12) for p in places}
    required = {places[-1]} if seed % 3 == 0 else set()
    ir, data = _model(places, links, sources=sources, use=True, prize=prize, required=required)
    try:
        compiled = compile_model(ir, data)
    except Unsupported:
        pytest.skip("links[:9] left a place out of reach")
    assert join.applies(compiled) is not None  # use: a Steiner network, left to the solver
    expected = _brute_use(places, links, sources, prize, required)
    result = _mip(compiled, "cp-sat" if seed % 2 else "highs")
    if expected is None:
        assert result.status == "infeasible"
        return
    assert result.status == "optimal" and round(float(result.objective)) == expected, (seed, result.objective,
                                                                                       expected)


@pytest.mark.parametrize("seed", range(5))
def test_the_start_keeps_the_join_rule(seed):
    places, links = _graph(10, 300 + seed)
    sources = {"p0"} if seed % 2 else None
    required = {places[3], places[7], places[9]}
    ir, data = _model(places, links, sources=sources, use=True, prize={}, required=required)
    compiled = compile_model(ir, data)
    assert join.start_applies(compiled) is None
    hint, record = join.start(compiled)
    assert record["how"].startswith("places chosen" if sources else "Steiner") and hint
    values = {k: hint.get(k, 0) for k in compiled.variables}
    assert _holds(compiled, values), record
    # Without use: the spanning tree, in a model with a budget row the exact lane does not take.
    ir, data = _model(places, links, sources=sources)
    ir["parameters"]["pair"] = {"index": ["segment"]}
    data["parameters"]["pair"] = [{"segment": l, "value": 1 if i < 2 else 0} for i, (l, *_) in enumerate(links)]
    ir["constraints"].append({"id": "c_degree", "severity": "hard", "left": {"sum": {"mul": [
        {"par": "pair", "index": ["l"]}, {"var": "lay", "index": ["l"]}]}, "over": [{"index": "l", "set": "segment"}]},
        "relation": "<=", "right": {"const": 2}})
    compiled = compile_model(ir, data)
    assert "more than one decision" in join.applies(compiled)
    hint, record = join.start(compiled)
    assert _holds(compiled, {k: hint.get(k, 0) for k in compiled.variables})
    result = _mip(compiled)
    assert result.status == "optimal" and round(float(result.objective)) == _nx_mst(places, links, sources)


from tests.test_quadratic import empty_queue  # noqa: E402,F401
from tests.test_v1_problem_run import db  # noqa: E402,F401


def _domain_run(db, places, links, *, use=False, required=()):  # noqa: F811
    """The model on a real domain: sites, segments, their two ends, a cost per segment; one run, worked."""
    from sqlalchemy import text

    from app.solve.service import enqueue_run
    from app.worker import work_once
    from tests.test_v1_domain_triggers import make_relationship, make_relationship_type
    from tests.test_v1_problem_run import (make_domain, make_entity, make_entity_type, make_model_version,
                                           make_parameter_def, make_parameter_value, make_problem)

    domain = make_domain(db, "network design")
    site, segment = make_entity_type(db, domain, "site"), make_entity_type(db, domain, "segment")
    ids = {p: make_entity(db, site, p) for p in places}
    ids.update({l: make_entity(db, segment, l) for l, *_ in links})
    ends = [make_relationship_type(db, domain, name, segment, site) for name in ("seg_a", "seg_b")]
    cost = make_parameter_def(db, domain, "cost", [segment])
    for name in ("forced", "banned"):
        make_parameter_def(db, domain, name, [segment])
    for l, a, b, c in links:
        make_relationship(db, ends[0], ids[l], ids[a])
        make_relationship(db, ends[1], ids[l], ids[b])
        make_parameter_value(db, cost, [ids[l]], c)
    if use:
        make_parameter_def(db, domain, "prize", [site])
        need = make_parameter_def(db, domain, "required", [site])
        for p in required:
            make_parameter_value(db, need, [ids[p]], 1)
    ir, _ = _model(places, links, use=use, required=required, prize={})
    from app.ir.validate import validate_ir

    assert validate_ir(db, domain, ir) is None
    wrong = make_relationship_type(db, domain, "near", site, site)
    bad = json.loads(json.dumps(ir))
    bad["relationships"].append("near")
    bad["constraints"][0]["join"]["ends"] = ["seg_a", "near"]
    refused = validate_ir(db, domain, bad)
    assert refused is not None and refused.code == "join_ends_mismatch" and refused.loc[-2:] == ["ends", 1], refused
    bad["constraints"][0]["join"]["ends"] = ["seg_a", "seg_b"]
    bad["constraints"][0]["join"]["sources"] = "is_exchange"
    refused = validate_ir(db, domain, bad)
    assert refused is not None and refused.code == "join_sources_invalid", refused
    from tests.test_v1_problem_run import make_attribute_def

    make_attribute_def(db, site, "is_exchange", "boolean")
    make_attribute_def(db, site, "label_text", "text")
    assert validate_ir(db, domain, bad) is None
    bad["constraints"][0]["join"]["demand"] = "label_text"
    refused = validate_ir(db, domain, bad)
    assert refused is not None and refused.code == "join_field_invalid" and "as text" in refused.message, refused
    assert wrong
    version = make_model_version(db, make_problem(db, domain), ir)
    problem = db.execute(text("SELECT problem_id FROM model_version WHERE id = :v"), {"v": version}).scalar_one()
    scenario = db.execute(text("INSERT INTO scenario (problem_id, model_version_id, name) VALUES (:p, :v, 'base') "
                               "RETURNING id"), {"p": problem, "v": version}).scalar_one()
    db.commit()
    run_id = enqueue_run(db, scenario, time_limit=20.0)
    for _ in range(5):
        if db.execute(text("SELECT status FROM run WHERE id = :r"), {"r": run_id}).scalar_one() != "queued":
            break
        work_once(db)
    return db.execute(text("SELECT status, optimality, objective, solver_version, params, error FROM run "
                           "WHERE id = :r"), {"r": run_id}).mappings().one()


def test_a_run_of_a_spanning_network_is_solved_by_kruskal_and_proven(db, empty_queue):  # noqa: F811
    places, links = _graph(12, 41)
    row = _domain_run(db, places, links)
    assert row["status"] == "optimal" and row["optimality"] == "global", row["error"]
    assert row["solver_version"].startswith("minimum spanning tree")
    assert row["params"]["network_run"]["kind"] == "spanning"
    assert round(float(row["objective"])) == _nx_mst(places, links)


def test_a_run_choosing_its_places_starts_from_a_steiner_tree(db, empty_queue):  # noqa: F811
    places, links = _graph(10, 43)
    row = _domain_run(db, places, links, use=True, required=("p2", "p5", "p9"))
    assert row["status"] == "optimal", row["error"]
    start = row["params"]["join_start_run"]
    assert start["used"] is True and start["how"].startswith("Steiner"), start


# --- what each place takes, carried along the built links (capacitated network design) -------------------------


def _capacitated(places, links, sources, need, cap, *, supply=None, unit=None):
    """Sources feed every place its need along built links of limited capacity; a link costs to build and, with
    `unit`, per unit carried (read through a carry variable)."""
    ir, data = _model(places, links, sources=sources)
    body = ir["constraints"][0]["join"]
    body["demand"] = "need"
    if cap is not None:
        body["capacity"] = "cap"
    if supply is not None:
        body["supply"] = "supply"
    for row in data["sets"]["site"]:
        row["need"] = need.get(row["id"], 0)
        if supply is not None and row["id"] in supply:
            row["supply"] = supply[row["id"]]
    for row in data["sets"]["segment"]:
        if cap is not None:
            row["cap"] = cap[row["id"]]
    if unit is not None:
        ir["variables"]["carry"] = {"index": ["segment"], "domain": "integer", "lower": 0, "upper": 1000}
        body["carry"] = {"var": "carry", "index": ["l"]}
        ir["parameters"]["unit"] = {"index": ["segment"]}
        data["parameters"]["unit"] = [{"segment": l, "value": unit[l]} for l, *_ in links]
        ir["objective"]["terms"].append({"id": "o_carry", "weight": 1, "expression": {
            "sum": {"mul": [{"par": "unit", "index": ["l"]}, {"var": "carry", "index": ["l"]}]},
            "over": [{"index": "l", "set": "segment"}]}})
    return ir, data


def _brute_capacitated(places, links, sources, need, cap, supply=None, unit=None):
    """The cheapest set of links that joins every place to a source and can carry every need (a min-cost flow on
    the links built), over every set of links."""
    best = None
    total = sum(need.get(p, 0) for p in places if p not in sources)
    for k in range(len(links) + 1):
        for chosen in itertools.combinations(links, k):
            g = nx.Graph()
            g.add_nodes_from(places)
            g.add_edges_from((a, b) for _, a, b, _ in chosen)
            if any(not (nx.node_connected_component(g, p) & sources) for p in places):
                continue
            flow = nx.DiGraph()
            flow.add_node("S", demand=-total)
            for p in places:
                flow.add_node(p, demand=0 if p in sources else need.get(p, 0))
            for s in sources:
                flow.add_edge("S", s, capacity=(supply or {}).get(s, total), weight=0)
            for l, a, b, _ in chosen:
                if a == b:
                    continue
                for u, v in ((a, b), (b, a)):
                    # one direction is enough at an optimum: a link's capacity shared both ways
                    flow.add_edge(u, v, capacity=(cap or {}).get(l, total), weight=(unit or {}).get(l, 0)) \
                        if not flow.has_edge(u, v) else None
            try:
                moved = nx.min_cost_flow_cost(flow) if unit else (nx.min_cost_flow(flow) and 0)
            except nx.NetworkXUnfeasible:
                continue
            value = sum(c for *_, c in chosen) + moved
            best = value if best is None else min(best, value)
    return best


@pytest.mark.parametrize("seed", range(8))
def test_capacities_and_needs_agree_with_every_set_of_links(seed):
    rnd = random.Random(seed)
    places, links = _graph(6, 400 + seed, extra=0.3)
    links = [(l, a, b, abs(c) + 1) for l, a, b, c in links[:9]]
    sources = {"p0"} if seed % 3 else {"p0", "p5"}
    need = {p: rnd.randint(0, 4) for p in places if p not in sources}
    cap = {l: rnd.randint(2, 8) for l, *_ in links}
    supply = {s: 6 + seed for s in sources} if seed % 2 else None
    unit = {l: rnd.randint(0, 3) for l, *_ in links} if seed % 4 >= 2 else None
    try:
        compiled = compile_model(*_capacitated(places, links, sources, need, cap, supply=supply, unit=unit))
    except Unsupported as refused:
        pytest.skip(str(refused))  # a place no link reaches, or too little supply in all
    assert "capacitated" in join.applies(compiled)
    expected = _brute_capacitated(places, links, sources, need, cap, supply, unit)
    result = _mip(compiled, "cp-sat" if seed % 2 else "highs")
    if expected is None:
        assert result.status == "infeasible"
        return
    assert result.status == "optimal" and round(float(result.objective)) == expected, (seed, result.objective, expected)
    if unit:
        flows = {k[1][1]: v for k, v in result.assignments.items() if k[0] == join.DEMAND}
        assert flows  # the carry variable reads the demand flow
        carried = {k[1][0]: v for k, v in result.assignments.items() if k[0] == "carry"}
        for l, *_ in links:
            both = sum(v for (rule, link, way), v in ((k[1], v) for k, v in result.assignments.items()
                                                     if k[0] == join.DEMAND) if link == l)
            assert round(float(carried[l])) == round(float(both))


def test_needs_without_capacity_still_solve_as_a_spanning_forest():
    places, links = _graph(9, 7)
    sources = {"p0"}
    need = {p: 2.5 for p in places if p != "p0"}
    compiled = compile_model(*_capacitated(places, links, sources, need, None))
    assert join.applies(compiled) is None
    ours = join.solve(compiled).solution
    assert ours.status == "optimal" and ours.objective == _nx_mst(places, links, sources)
    assert _holds(compiled, ours.assignments)  # the demand flow (decimal) is set too


def test_what_a_capacitated_rule_needs_is_said():
    places, links = _graph(5, 3)
    ir, data = _capacitated(places, links, {"p0"}, {"p1": 3}, {l: 1 for l, *_ in links})
    assert check_shape(ir) is None
    body = ir["constraints"][0]["join"]
    for change, drop, code in (({}, "sources", "join_malformed"), ({}, "demand", "join_malformed"),
                               ({"demand": 3}, None, "join_malformed"),
                               ({"carry": {"var": "lay", "index": ["l"]}}, None, "join_carry_invalid"),
                               ({"carry": {"var": "lay", "index": ["p"]}}, None, "join_index_mismatch")):
        trial = {k: v for k, v in {**body, **change}.items() if k != drop}
        ir["constraints"][0]["join"] = trial
        refused = check_shape(ir)
        assert refused is not None and refused.code == code, (change, drop, refused)
    ir["constraints"][0]["join"] = body
    data["sets"]["site"][1]["need"] = -1
    with pytest.raises(Unsupported, match="0 or more"):
        compile_model(ir, data)
    data["sets"]["site"][1]["need"] = 3
    for row in data["sets"]["site"]:
        row["supply"] = 1
    body["supply"] = "supply"
    with pytest.raises(Unsupported, match="supply 1 in all"):
        compile_model(ir, data)


def test_the_start_of_a_capacitated_network_carries_every_demand_within_capacity():
    places = ["s", "a", "b", "c"]
    links = [("sa", "s", "a", 1), ("ab", "a", "b", 1), ("bc", "b", "c", 1), ("sc", "s", "c", 5)]
    compiled = compile_model(*_capacitated(places, links, {"s"}, {"a": 1, "b": 1, "c": 1}, {l: 2 for l, *_ in links}))
    hint, record = join.start(compiled)
    assert record["how"].startswith("capacity-aware"), record  # the spanning tree would overload s-a
    values = {k: hint.get(k, 0) for k in compiled.variables}
    assert _holds(compiled, values)
    assert float(compiled.objective.evaluated_at(values)) == 7 == record["estimate"]  # s-a, a-b and s-c: the optimum
    result = _mip(compiled)
    assert result.status == "optimal" and round(float(result.objective)) == 7


@pytest.mark.parametrize("seed", range(12))
def test_the_capacity_aware_start_keeps_every_row_and_is_near_the_optimum(seed):
    rnd = random.Random(seed)
    places, links = _graph(7, 500 + seed, extra=0.4)
    links = [(l, a, b, abs(c) + 1) for l, a, b, c in links]
    sources = {"p0"} if seed % 3 else {"p0", "p6"}
    need = {p: rnd.randint(0, 5) for p in places if p not in sources}
    cap = {l: rnd.randint(3, 9) for l, *_ in links}
    supply = {s: 12 + seed for s in sources} if seed % 2 else None
    unit = {l: rnd.randint(0, 3) for l, *_ in links}
    try:
        compiled = compile_model(*_capacitated(places, links, sources, need, cap, supply=supply, unit=unit))
    except Unsupported:
        pytest.skip("not every place can be fed")
    hint, record = join.start(compiled)
    result = _mip(compiled)
    if result.status == "infeasible":
        assert "design_why" in record or not record.get("how", "").startswith("capacity")
        return
    assert record["how"].startswith("capacity-aware"), record
    values = {k: hint.get(k, 0) for k in compiled.variables}
    assert _holds(compiled, values), seed
    ours = float(compiled.objective.evaluated_at(values))
    assert ours == pytest.approx(record["estimate"])
    best = float(result.objective)
    assert best - 1e-6 <= ours <= best * 1.5 + 1e-6, (seed, ours, best)


def test_demand_no_design_can_carry_is_refused_with_the_shortfall():
    places = ["s", "a", "b"]
    links = [("sa", "s", "a", 1), ("ab", "a", "b", 1), ("sb", "s", "b", 1)]
    with pytest.raises(Unsupported, match="at most 5 of the 6"):
        compile_model(*_capacitated(places, links, {"s"}, {"a": 3, "b": 3}, {"sa": 2, "ab": 5, "sb": 3}))
    compiled = compile_model(*_capacitated(places, links, {"s"}, {"a": 3, "b": 2}, {"sa": 2, "ab": 5, "sb": 3}))
    assert _mip(compiled).status == "optimal"


def _prize_capacitated(seed, n=7):
    """Sources, places worth a prize when fed (and some that must be), demands, capacities, per-unit costs."""
    rnd = random.Random(seed)
    places, links = _graph(n, 600 + seed, extra=0.35)
    links = [(l, a, b, abs(c) + 1) for l, a, b, c in links]
    sources = {"p0"}
    need = {p: rnd.randint(0, 4) for p in places if p not in sources}
    cap = {l: rnd.randint(3, 10) for l, *_ in links}
    unit = {l: rnd.randint(0, 2) for l, *_ in links}
    prize = {p: rnd.choice([0, 0, 10, 25, 40]) for p in places}
    required = {places[-1]} if seed % 2 else set()
    ir, data = _capacitated(places, links, sources, need, cap, unit=unit)
    use_ir, use_data = _model(places, links, sources=sources, use=True, prize=prize, required=required)
    ir["variables"]["serve"] = use_ir["variables"]["serve"]
    ir["constraints"][0]["join"]["use"] = {"var": "serve", "index": ["p"]}
    for name in ("prize", "required"):
        ir["parameters"][name] = use_ir["parameters"][name]
        data["parameters"][name] = use_data["parameters"][name]
    ir["objective"]["terms"].append(next(t for t in use_ir["objective"]["terms"] if t["id"] == "o_prize"))
    ir["constraints"].append(next(c for c in use_ir["constraints"] if c["id"] == "c_required"))
    return ir, data


@pytest.mark.parametrize("seed", range(10))
def test_with_use_the_start_chooses_places_that_pay_and_keeps_every_row(seed):
    compiled = compile_model(*_prize_capacitated(seed))
    hint, record = join.start(compiled)
    result = _mip(compiled)
    if result.status == "infeasible":
        return
    assert result.status == "optimal"
    assert record["how"].startswith("places chosen"), record
    values = {k: hint.get(k, 0) for k in compiled.variables}
    assert _holds(compiled, values), (seed, record)
    ours, best = float(compiled.objective.evaluated_at(values)), float(result.objective)
    assert ours == pytest.approx(record["estimate"])
    assert best - 1e-6 <= ours <= best + 0.25 * abs(best) + 10, (seed, ours, best)
