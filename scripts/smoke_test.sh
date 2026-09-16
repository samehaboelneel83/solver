#!/usr/bin/env bash
set -euo pipefail

# Prefer python3 (the standard on Linux/CI); fall back to python for
# environments (e.g. this Windows/Git Bash dev machine) where `python3` is
# on PATH but is a non-functional stub (e.g. the Windows Store shortcut) --
# so check that it actually runs, not just that `command -v` finds it.
PY=python3
python3 --version >/dev/null 2>&1 || PY=python

echo "== Bringing up full stack =="
docker compose up -d --build

echo "== Waiting for Postgres and ClickHouse to report healthy =="
for i in $(seq 1 30); do
  postgres_status=$(docker inspect --format '{{.State.Health.Status}}' "$(docker compose ps -q postgres)" 2>/dev/null || echo "")
  clickhouse_status=$(docker inspect --format '{{.State.Health.Status}}' "$(docker compose ps -q clickhouse)" 2>/dev/null || echo "")
  if [[ "$postgres_status" == "healthy" && "$clickhouse_status" == "healthy" ]]; then
    break
  fi
  sleep 2
done
if [[ "$postgres_status" != "healthy" || "$clickhouse_status" != "healthy" ]]; then
  echo "databases did not become healthy in time"
  exit 1
fi

echo "== Applying database migrations =="
# Run via a one-off container (not `exec` into the long-running backend
# service). On a cold start the backend service's own startup hook seeds
# admin data and crashes until migrations exist, and `restart: unless-stopped`
# keeps restarting that same container -- an `exec`'d alembic process
# attached to it would be killed mid-transaction by that restart, silently
# rolling back the whole (single-transaction) migration run. `run --rm
# --no-deps` applies migrations from an isolated container instead.
docker compose run --rm --no-deps -T backend alembic upgrade head

echo "== Restarting backend now that migrations are applied =="
# The backend service may have been crash-looping (its startup hook seeds
# admin data, which needs the tables the migration above just created) since
# `docker compose up -d`. Force a clean restart now rather than waiting out
# its restart backoff.
docker compose restart backend

echo "== Checking backend health =="
for i in $(seq 1 30); do
  if curl -sf http://localhost:8010/api/health -o /tmp/solver_health.json; then
    break
  fi
  sleep 2
done
cat /tmp/solver_health.json
grep -q '"postgres":"ok"' /tmp/solver_health.json
grep -q '"clickhouse":"ok"' /tmp/solver_health.json

echo "== Logging in as the seeded admin =="
TOKEN=$(curl -sf -X POST http://localhost:8010/api/auth/login \
  -d "username=${ADMIN_USERNAME:-admin}&password=${ADMIN_PASSWORD:-change-me-admin}" \
  | $PY -c "import sys,json;print(json.load(sys.stdin)['access_token'])")

echo "== Verifying the metadata endpoint lists all 31 registered tables =="
TABLE_COUNT=$(curl -sf -H "Authorization: Bearer $TOKEN" http://localhost:8010/api/meta/schema \
  | $PY -c "import sys,json;print(len(json.load(sys.stdin)))")
if [[ "$TABLE_COUNT" != "31" ]]; then
  echo "expected 31 registered tables, got $TABLE_COUNT"
  exit 1
fi

echo "== Creating an organization through the full stack =="
# Idempotent: delete any leftover row from a previous run of this script
# before creating a fresh one, since `code` is unique.
EXISTING_ORG_ID=$(curl -sf -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8010/api/iam/organization/?limit=500" \
  | $PY -c "import sys,json;items=json.load(sys.stdin)['items'];matches=[i['id'] for i in items if i['code']=='smoke-test-org'];print(matches[0] if matches else '')")
if [[ -n "$EXISTING_ORG_ID" ]]; then
  curl -sf -X DELETE -H "Authorization: Bearer $TOKEN" \
    "http://localhost:8010/api/iam/organization/$EXISTING_ORG_ID"
fi
curl -sf -X POST http://localhost:8010/api/iam/organization/ \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"code":"smoke-test-org","name":"Smoke Test Org","is_active":true}' | tee /tmp/solver_org.json
grep -q '"code":"smoke-test-org"' /tmp/solver_org.json

echo "== Checking the frontend serves and proxies /api to the backend =="
FRONTEND_STATUS=$(curl -sf -o /dev/null -w "%{http_code}" http://localhost:3010)
[[ "$FRONTEND_STATUS" == "200" ]]
curl -sf http://localhost:3010/api/health | grep -q '"postgres":"ok"'

echo "== All smoke checks passed =="
