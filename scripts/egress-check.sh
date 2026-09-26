#!/usr/bin/env bash
# OAAS O02: verify the running stack does not need public egress for smoke paths.
# Default: check that API health and frontend respond on localhost.
# With EGRESS_BLOCKED=1, also fail if the backend container can reach an external host.
set -euo pipefail

API_URL="${SMOKE_API_URL:-http://localhost:8010}"
WEB_URL="${SMOKE_WEB_URL:-http://localhost:3010}"

echo "==> Local reachability"
curl -fsS "$API_URL/api/health" | tee /tmp/solver-health.json
curl -fsS -o /dev/null -w "frontend HTTP %{http_code}\n" "$WEB_URL/"

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
