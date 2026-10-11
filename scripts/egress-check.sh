#!/usr/bin/env bash
# OAAS O02: verify the running stack does not need public egress for smoke paths.
# Default: check that API health and frontend respond on localhost.
# With EGRESS_BLOCKED=1, also fail if the backend container can reach an external host.
set -euo pipefail

API_URL="${SMOKE_API_URL:-http://localhost:8010}"
WEB_URL="${SMOKE_WEB_URL:-http://localhost:3010}"

echo "==> Local reachability"
curl -fsS "$API_URL/api/health" | tee /tmp/solver-health.json
# The page goes down a pipe, not to curl's own "-o /dev/null": under check.sh on Windows (MSYS_NO_PATHCONV=1)
# a native curl takes that as a file on the drive and fails with exit 23.
web_code="$(curl -fsS -w '%{http_code}' "$WEB_URL/" | tail -c 3)"
printf 'frontend HTTP %s\n' "$web_code"

echo "==> The tile server (setting spatial.tiles_index), as the backend reaches it for reports and terrain"
if docker compose exec -T backend python - <<'PY' 2>/dev/null; then
import sys
from app.core.db import SessionLocal
from app.settings_resolve import resolve
from app.spatial.terrain import candidates, fetch_bytes
with SessionLocal() as db:
    url = str(resolve(db)["spatial.tiles_index"].value or "").strip()
if not url:
    print("no tile index named: maps show no background (set spatial.tiles_index to the local tile server)")
    sys.exit(0)
for address in candidates(url):
    try:
        if fetch_bytes(address, timeout=5):
            print(f"OK: tile index at {address}")
            sys.exit(0)
    except Exception:
        pass
print(f"WARN: the tile index {url} did not answer from the backend container")
sys.exit(1)
PY
  :
else
  echo "WARN: tile index unreachable from the backend (reports and terrain reads will have no map)" >&2
fi

echo "==> The Assistant's model (LLM_BASE_URL, inside the network; a warning only: the rest serves without it)"
if docker compose exec -T backend python - <<'PY' 2>/dev/null; then
import os, sys, urllib.request
url = os.environ.get("LLM_BASE_URL", "").rstrip("/") + "/models"
req = urllib.request.Request(url, headers={"Authorization": "Bearer " + os.environ.get("LLM_API_KEY", "x")})
try:
    with urllib.request.urlopen(req, timeout=5) as r:
        sys.exit(0 if r.status < 300 else 1)
except Exception:
    sys.exit(1)
PY
  echo "OK: model reachable"
else
  echo "WARN: the model at LLM_BASE_URL did not answer; the Assistant will say so, everything else works" >&2
fi

if [[ "${EGRESS_BLOCKED:-0}" != "1" ]]; then
  echo "EGRESS_BLOCKED not set; skipping outbound probe (set EGRESS_BLOCKED=1 on an isolated host)."
  exit 0
fi

echo "==> Probing that backend cannot reach the public internet"
# Expect failure (non-zero). A successful fetch means egress is still open.
if docker compose exec -T backend \
  python -c "import urllib.request; urllib.request.urlopen('https://example.com', timeout=5)" 2>/dev/null; then
  echo "FAIL: backend reached https://example.com — public egress is still open" >&2
  exit 1
fi
echo "OK: backend could not reach https://example.com"
