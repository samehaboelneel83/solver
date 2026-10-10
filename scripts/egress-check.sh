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
