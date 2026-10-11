"""Gold models: for a case, the model that reached its reference, kept as {ir, data} and replayed without the
language model or the database (build-protocol plan, Phase 0.2). Prints only case ids and pass/fail, so it is
safe over the hidden set.

    python bench/phase1/gold.py capture <run folder> [...]        (host: reads the API and the dataset table)
    python -m bench.phase1.gold check [S] [case ...]               (test image: compile, solve, compare)

A gold is `bench/phase1/gold/<p>-S.json` (tuning) or `bench/hidden/gold/<h>-S.json` (hidden):
{"case": "p01", "size": "S", "run": 385, "ir": {...}, "data": {sets, parameters, relationships, parameter_defaults}}.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.parse
import urllib.request
from pathlib import Path

API = "http://localhost:8010"
HERE = Path(__file__).parent
TOLERANCE = 1e-4


def _token() -> str:
    body = urllib.parse.urlencode({"username": "admin", "password": "change-me-admin"}).encode()
    req = urllib.request.Request(API + "/api/auth/login", body, {"Content-Type": "application/x-www-form-urlencoded"})
    return json.load(urllib.request.urlopen(req))["access_token"]


def _get(path: str, token: str) -> dict:
    return json.load(urllib.request.urlopen(urllib.request.Request(API + path, headers={"Authorization": f"Bearer {token}"})))


def _frozen(dataset_id: int) -> dict:
    sql = f"select data from dataset where id = {int(dataset_id)}"
    out = subprocess.run(["docker", "compose", "exec", "-T", "postgres", "sh", "-c",
                          f'psql -U "$POSTGRES_USER" -d solver -At -c "{sql}"'],
                         capture_output=True, text=True, cwd=str(HERE.parents[2])).stdout.strip()
    return json.loads(out)


def _where(folder: Path) -> tuple[str, str, Path]:
    name = folder.name
    case, size = name.split("-")[0], name.split("-")[1]
    root = HERE.parent / "hidden" / "gold" if case.startswith("h") else HERE / "gold"
    return case, size, root / f"{case}-{size}.json"


def capture(folder: Path, token: str) -> str:
    result = json.loads((folder / "result.json").read_text())
    run_id = result.get("run")
    if not run_id:
        return f"{folder.name}: no run"
    run = _get(f"/api/v1/runs/{run_id}", token)
    scenario = _get(f"/api/v1/scenarios/{run['scenario_id']}", token)
    if scenario.get("patch"):
        return f"{folder.name}: a what-if run, not the plan"
    version = _get(f"/api/v1/versions/{scenario['model_version_id']}", token)
    data = _frozen(run["dataset_id"])
    case, size, path = _where(folder)
    path.parent.mkdir(parents=True, exist_ok=True)
    gold = {"case": case, "size": size, "run": run_id, "objective": run.get("objective"),
            "ir": version["ir"], "data": {k: data.get(k) for k in ("sets", "parameters", "relationships", "parameter_defaults", "labels")}}
    path.write_text(json.dumps(gold, ensure_ascii=False, indent=1), encoding="utf-8")
    return f"{case}-{size}: captured from run {run_id}"


def _expected(case: str, size: str) -> dict:
    root = HERE.parent / "hidden" / "cases" if case.startswith("h") else HERE / "cases"
    return json.loads((root / case / size / "expected.json").read_text(encoding="utf-8"))


def solve(gold: dict, seconds: float = 60.0) -> tuple[str, float | None]:
    """The gold compiled and solved as the trial does: (status, objective)."""
    from app.solve import sandbox
    from app.solve.backends import choose
    from app.solve.classify import classify
    from app.solve.compile import compile_model
    from app.solve.convexity import refine

    compiled = compile_model(gold["ir"], gold["data"])
    found = refine(classify(gold["ir"], gold["data"]), compiled)
    backend, _ = choose(found)
    result, reason = sandbox.run("app.solve.sandbox:solve_in_child",
                                 {"backend": backend.name, "compiled": compiled, "time_limit": seconds,
                                  "seed": 0, "workers": 1, "gap_rel": 0.0}, time_limit=seconds + 5)
    if result is None:
        return f"no answer ({str(reason or '')[:80]})", None
    return str(result.status), result.objective


def check(size: str, cases: list[str]) -> int:
    failed = 0
    roots = [HERE / "gold", HERE.parent / "hidden" / "gold"]
    paths = sorted(p for r in roots if r.exists() for p in r.glob(f"*-{size}.json"))
    for path in paths:
        gold = json.loads(path.read_text(encoding="utf-8"))
        if cases and gold["case"] not in cases:
            continue
        expected = _expected(gold["case"], gold["size"])
        status, objective = solve(gold)
        want = expected.get("goal")
        if expected.get("kind") == "bounded" or want is None:
            ok = objective is not None and status in ("optimal", "feasible")
            said = f"{status}, goal {objective}"
        else:
            ok = objective is not None and abs(float(objective) - float(want)) <= TOLERANCE * max(1.0, abs(float(want)))
            said = f"{status}, goal {objective} vs reference {want}"
        failed += not ok
        print(f"{gold['case']}-{gold['size']}: {'pass' if ok else 'FAIL'} ({said})")
    print(f"{len(paths) - failed} pass of {len(paths)}")
    return failed


if __name__ == "__main__":
    if sys.argv[1] == "capture":
        token = _token()
        for f in sys.argv[2:]:
            print(capture(Path(f), token))
    elif sys.argv[1] == "check":
        size = sys.argv[2] if len(sys.argv) > 2 and len(sys.argv[2]) == 1 else "S"
        cases = [a for a in sys.argv[2:] if len(a) != 1]
        sys.exit(1 if check(size, cases) else 0)
