"""Runs scored on a what-if scenario, re-scored on the plan as asked (11 October 2026: the driver took the newest
run, and the Assistant had solved "Budget 400k" after the base plan). Prints only which run folders moved -- never
anything about a case -- so it can run over the hidden set.

    python bench/phase1/rebase_runs.py bench/phase1/runs/<folder> [...]     (from D:/solver/backend, on the host)
"""

from __future__ import annotations

import glob
import json
import os
import shutil
import subprocess
import sys
import urllib.parse
import urllib.request

API = "http://localhost:8010"


def _token() -> str:
    body = urllib.parse.urlencode({"username": "admin", "password": "change-me-admin"}).encode()
    req = urllib.request.Request(API + "/api/auth/login", body, {"Content-Type": "application/x-www-form-urlencoded"})
    return json.load(urllib.request.urlopen(req))["access_token"]


def _get(path: str, token: str) -> bytes:
    return urllib.request.urlopen(urllib.request.Request(API + path, headers={"Authorization": f"Bearer {token}"})).read()


def _base_run(problem_id: int) -> int | None:
    sql = (f"select max(r.id) from run r join scenario s on s.id = r.scenario_id where s.problem_id = {int(problem_id)} "
           "and s.patch = '{}'::jsonb and r.status in ('optimal', 'feasible')")
    out = subprocess.run(["docker", "compose", "exec", "-T", "postgres", "sh", "-c",
                          f'psql -U "$POSTGRES_USER" -d solver -At -c "{sql}"'],
                         capture_output=True, text=True, cwd="D:/solver").stdout.strip()
    return int(out) if out.isdigit() else None


def _module_and_case(folder: str) -> tuple[str, str]:
    name = os.path.basename(folder.rstrip("/"))
    case, size = name.split("-")[0], name.split("-")[1]
    if case.startswith("h"):
        module = os.path.basename(glob.glob(f"bench/hidden/{case}_*.py")[0])[:-3]
        return f"bench.hidden.{module}", f"bench/hidden/cases/{case}/{size}"
    module = os.path.basename(glob.glob(f"bench/phase1/{case}_*.py")[0])[:-3]
    return module, f"bench/phase1/cases/{case}/{size}"


def rebase(folder: str, token: str) -> str | None:
    try:
        run = json.load(open(os.path.join(folder, "run.json")))
    except (OSError, ValueError):
        return None
    scenario = json.loads(_get(f"/api/v1/scenarios/{run['scenario_id']}", token))
    if not scenario.get("patch"):
        return None
    base = _base_run(scenario["problem_id"])
    if base is None or base == run.get("id"):
        return f"{folder}: scored on a what-if run, and the problem has no solved base run"
    keep = os.path.join(folder, "scored-whatif")
    os.makedirs(keep, exist_ok=True)
    for f in ("run.json", "export.csv", "answer-map.json", "score.json", "result.json"):
        if os.path.exists(os.path.join(folder, f)):
            shutil.copy(os.path.join(folder, f), keep)
    for f, path in (("run.json", f"/api/v1/runs/{base}"), ("export.csv", f"/api/v1/runs/{base}/export?format=csv"),
                    ("answer-map.json", f"/api/v1/runs/{base}/answer-map")):
        open(os.path.join(folder, f), "wb").write(_get(path, token))
    result = json.load(open(os.path.join(folder, "result.json")))
    result["run"] = base
    json.dump(result, open(os.path.join(folder, "result.json"), "w"), indent=1)
    module, case_dir = _module_and_case(folder)
    rel = folder.replace("\\", "/")
    with open(os.path.join(folder, "score.json"), "w") as out:
        subprocess.run(["docker", "run", "--rm", "-v", "D:/solver/backend:/app", "-w", "/app", "solver-backend-test",
                        "python", "-m", "bench.phase1.score", module, case_dir, rel], stdout=out,
                       stderr=subprocess.DEVNULL, env={**os.environ, "MSYS_NO_PATHCONV": "1"})
    return f"{folder}: re-scored on the base plan"


if __name__ == "__main__":
    token = _token()
    for folder in sys.argv[1:]:
        said = rebase(folder, token)
        if said:
            print(said)
