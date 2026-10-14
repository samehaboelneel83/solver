"""A case scored on another case's run (14 Oct: cases side by side, the driver took the platform's newest run):
re-fetch the case's own run into its folder and record it, then rescore. Prints only the folder and run ids.

    python bench/phase1/rescue_run.py <run folder> <run id> <domain id>      (host, from D:/solver/backend)
"""

from __future__ import annotations

import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path

API = "http://localhost:8010"


def _token() -> str:
    body = urllib.parse.urlencode({"username": "admin", "password": "change-me-admin"}).encode()
    req = urllib.request.Request(API + "/api/auth/login", body, {"Content-Type": "application/x-www-form-urlencoded"})
    return json.load(urllib.request.urlopen(req))["access_token"]


def _get(path: str, token: str) -> bytes:
    return urllib.request.urlopen(urllib.request.Request(API + path, headers={"Authorization": f"Bearer {token}"})).read()


def main(folder: Path, run_id: int, domain_id: int) -> None:
    token = _token()
    run = json.loads(_get(f"/api/v1/runs/{run_id}", token))
    scen = json.loads(_get(f"/api/v1/scenarios/{run['scenario_id']}", token))
    (folder / "run.json").write_bytes(_get(f"/api/v1/runs/{run_id}", token))
    (folder / "export.csv").write_bytes(_get(f"/api/v1/runs/{run_id}/export?format=csv", token))
    (folder / "answer-map.json").write_bytes(_get(f"/api/v1/runs/{run_id}/answer-map", token))
    for stale in ("run-page.txt", "run-page.png", "alternatives-run.json", "alternatives.txt", "alternatives.png"):
        (folder / stale).unlink(missing_ok=True)  # pages of the other case's run
    result = json.loads((folder / "result.json").read_text(encoding="utf-8"))
    result.update({"run": run_id, "scenario": run["scenario_id"], "problem": scen["problem_id"], "domain": domain_id,
                   "rescued": True})
    (folder / "result.json").write_text(json.dumps(result, indent=1), encoding="utf-8")
    print(f"{folder.name}: run {run_id}")


if __name__ == "__main__":
    main(Path(sys.argv[1]), int(sys.argv[2]), int(sys.argv[3]))
