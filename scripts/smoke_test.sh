#!/usr/bin/env bash
set -euo pipefail

# Full-stack smoke test, schema v1.
#
# ---------------------------------------------------------------------------
# Why this script was rewritten
# ---------------------------------------------------------------------------
# The v0 version ran, unconditionally and with no prompt:
#
#     docker compose up -d --build
#     docker compose run --rm --no-deps -T backend alembic upgrade head
#
# against the default compose stack -- whose database is the live `solver`.
# On this branch `alembic upgrade head` runs migration 0006, whose first
# statement is `DROP SCHEMA domain CASCADE`. Anyone running the documented
# smoke test to "check the stack still works" would have destroyed their
# data with no warning and no way back (0006/0007's downgrade drop the v1
# tables and recreate nothing). It then asserted `/api/meta/schema` lists
# 31 tables; schema v1 registers 7, so it would have failed *after* the
# destruction, which is the worst possible order.
#
# Two rules now hold, and they are the point of the rewrite:
#
#   1. **By default this script changes nothing.** It does not build, does
#      not create or recreate containers, and does not migrate. It checks a
#      stack that is already running. Run it as often as you like.
#
#   2. **Migrating requires an explicit opt-in AND passes a preflight.**
#      `--bootstrap` is the opt-in. Even then the script refuses unless the
#      target database is either empty or already on schema v1, and asks you
#      to type its name back. There is no flag that migrates a populated v0
#      database: that is a cutover, and it has a runbook --
#      `docs/runbooks/schema-v1-cutover.md`.
#
#      The one thing `--bootstrap` does before asking is start `postgres`
#      and `clickhouse` if they are not already running, because the
#      preflight has to query the database to decide. Starting a container
#      creates no data and changes no schema; everything that does happens
#      after the confirmation.
#
# ---------------------------------------------------------------------------
# Usage
# ---------------------------------------------------------------------------
#   ./scripts/smoke_test.sh                 # check only (the default)
#   ./scripts/smoke_test.sh --bootstrap     # also build, start and migrate
#
# Environment:
#   SMOKE_API_URL     default http://localhost:8010
#   SMOKE_WEB_URL     default http://localhost:3010
#   POSTGRES_USER     default solver      } used for the preflight query,
#   POSTGRES_DB       default solver      } and for the confirmation prompt
#   ADMIN_USERNAME    default admin
#   ADMIN_PASSWORD    default change-me-admin
#   SMOKE_CONFIRM     with --bootstrap, supplies the confirmation
#                     non-interactively; must equal $POSTGRES_DB
#
# To smoke-test a throwaway stack instead of your own, point SMOKE_API_URL /
# SMOKE_WEB_URL / POSTGRES_DB at it.
#
# What it writes: one `iam.organization` row coded `smoke-test-org`, deleted
# again in a trap whether the script passes or fails. Nothing else.

# Prefer python3 (the standard on Linux/CI); fall back to python for
# environments (e.g. this Windows/Git Bash dev machine) where `python3` is
# on PATH but is a non-functional stub (e.g. the Windows Store shortcut) --
# so check that it actually runs, not just that `command -v` finds it.
PY=python3
python3 --version >/dev/null 2>&1 || PY=python

API_URL="${SMOKE_API_URL:-http://localhost:8010}"
WEB_URL="${SMOKE_WEB_URL:-http://localhost:3010}"
PGUSER_NAME="${POSTGRES_USER:-solver}"
PGDB_NAME="${POSTGRES_DB:-solver}"

# schema v1 registers exactly seven tables in TABLE_REGISTRY: the four `iam`
# tables plus public.domain / template / problem. The eight DOMAIN tables,
# `scenario` and the four immutable RUN tables are deliberately excluded
# (see backend/app/api/routers.py). v0 registered 31.
EXPECTED_TABLE_COUNT=7

# Revision ids in backend/alembic/versions are zero-padded sequential
# numbers, so a plain string comparison orders them. 0005 is the last v0
# revision; anything above it is schema v1. Comparing rather than listing
# the v1 revisions means this does not need editing when 0010 is added.
LAST_V0_REVISION="0005"

BOOTSTRAP=0
case "${1:-}" in
  "")            ;;
  --bootstrap)   BOOTSTRAP=1 ;;
  -h|--help)     sed -n '/^# Usage$/,/^# What it writes/p' "$0" | sed 's/^#\{1,\} \{0,1\}//'; exit 0 ;;
  *)             echo "unknown argument: $1 (try --help)" >&2; exit 2 ;;
esac

psql_query() {
  docker compose exec -T postgres \
    psql -U "$PGUSER_NAME" -d "$PGDB_NAME" -tAc "$1"
}

# --------------------------------------------------------------------------
# --bootstrap: preflight, then confirm, then build/start/migrate
# --------------------------------------------------------------------------

if [[ "$BOOTSTRAP" == "1" ]]; then
  echo "== Preflight: is it safe to migrate '$PGDB_NAME'? =="

  if ! docker compose ps -q postgres >/dev/null 2>&1 || [[ -z "$(docker compose ps -q postgres)" ]]; then
    echo "Postgres is not running; starting only the database services."
    docker compose up -d postgres clickhouse
    for _ in $(seq 1 30); do
      [[ "$(docker inspect --format '{{.State.Health.Status}}' "$(docker compose ps -q postgres)" 2>/dev/null || echo "")" == "healthy" ]] && break
      sleep 2
    done
  fi

  # Absent alembic_version -> never migrated. Present but empty -> likewise.
  CURRENT_REVISION=$(psql_query \
    "SELECT coalesce((SELECT version_num FROM alembic_version LIMIT 1), '')" \
    2>/dev/null || echo "")
  CURRENT_REVISION=$(echo "$CURRENT_REVISION" | tr -d '[:space:]')

  # Anything the application owns, in any of its schemas.
  USER_TABLES=$(psql_query \
    "SELECT count(*) FROM information_schema.tables
      WHERE table_schema IN ('public','iam','domain','problem')
        AND table_name <> 'alembic_version'" 2>/dev/null || echo "0")
  USER_TABLES=$(echo "$USER_TABLES" | tr -d '[:space:]')

  if [[ -z "$CURRENT_REVISION" && "${USER_TABLES:-0}" == "0" ]]; then
    echo "  '$PGDB_NAME' is empty -- safe to migrate."
  elif [[ -n "$CURRENT_REVISION" && "$CURRENT_REVISION" > "$LAST_V0_REVISION" ]]; then
    echo "  '$PGDB_NAME' is already on schema v1 (revision $CURRENT_REVISION) -- safe to migrate."
  else
    cat >&2 <<EOF

REFUSING to migrate '$PGDB_NAME'.

  alembic revision : ${CURRENT_REVISION:-<none>}
  application tables: ${USER_TABLES:-0}

This database is neither empty nor already on schema v1, so \`alembic
upgrade head\` would run migration 0006 -- whose first statement is
\`DROP SCHEMA domain CASCADE\`. Everything in the v0 \`domain\` and
\`problem\` schemas would be destroyed, and the downgrade does not bring
it back.

That is a cutover, not a smoke test. It has a runbook:

    docs/runbooks/schema-v1-cutover.md

To smoke-test without migrating, run this script with no arguments
against a stack that is already migrated, or point POSTGRES_DB /
SMOKE_API_URL / SMOKE_WEB_URL at a throwaway stack.
EOF
    exit 1
  fi

  echo
  echo "--bootstrap will now, against the default compose stack:"
  echo "  * docker compose up -d --build   (rebuilds images, RECREATES containers)"
  echo "  * alembic upgrade head           (on database '$PGDB_NAME')"
  echo
  if [[ -n "${SMOKE_CONFIRM:-}" ]]; then
    CONFIRMATION="$SMOKE_CONFIRM"
    echo "Confirmation supplied by SMOKE_CONFIRM."
  else
    read -r -p "Type the database name ('$PGDB_NAME') to continue, anything else to abort: " CONFIRMATION
  fi
  if [[ "$CONFIRMATION" != "$PGDB_NAME" ]]; then
    echo "Aborted; nothing was changed." >&2
    exit 1
  fi

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
  docker compose restart backend
fi

# --------------------------------------------------------------------------
# Checks. These run in both modes and change nothing but the one
# `smoke-test-org` row, which the trap below removes again.
# --------------------------------------------------------------------------

echo "== Checking backend health at $API_URL =="
for i in $(seq 1 30); do
  if curl -sf "$API_URL/api/health" -o /tmp/solver_health.json; then
    break
  fi
  if [[ "$BOOTSTRAP" != "1" && "$i" == "5" ]]; then
    echo "$API_URL is not responding. This script does not start anything by" >&2
    echo "default -- bring the stack up yourself, or re-run with --bootstrap." >&2
    exit 1
  fi
  sleep 2
done
cat /tmp/solver_health.json
grep -q '"postgres":"ok"' /tmp/solver_health.json
grep -q '"clickhouse":"ok"' /tmp/solver_health.json

echo "== Logging in as the seeded admin =="
TOKEN=$(curl -sf -X POST "$API_URL/api/auth/login" \
  -d "username=${ADMIN_USERNAME:-admin}&password=${ADMIN_PASSWORD:-change-me-admin}" \
  | $PY -c "import sys,json;print(json.load(sys.stdin)['access_token'])")

echo "== Verifying the metadata endpoint lists the $EXPECTED_TABLE_COUNT registered v1 tables =="
TABLE_COUNT=$(curl -sf -H "Authorization: Bearer $TOKEN" "$API_URL/api/meta/schema" \
  | $PY -c "import sys,json;print(len(json.load(sys.stdin)))")
if [[ "$TABLE_COUNT" != "$EXPECTED_TABLE_COUNT" ]]; then
  echo "expected $EXPECTED_TABLE_COUNT registered tables, got $TABLE_COUNT"
  echo "(31 would mean this stack is still running the v0 schema and code)"
  exit 1
fi

echo "== Creating an organization through the full stack =="
SMOKE_ORG_ID=""
cleanup_org() {
  if [[ -n "$SMOKE_ORG_ID" ]]; then
    curl -sf -X DELETE -H "Authorization: Bearer $TOKEN" \
      "$API_URL/api/iam/organization/$SMOKE_ORG_ID" >/dev/null || true
  fi
}
trap cleanup_org EXIT

# Idempotent: delete any leftover row from an earlier run that died before
# its trap could fire, since `code` is unique.
EXISTING_ORG_ID=$(curl -sf -H "Authorization: Bearer $TOKEN" \
  "$API_URL/api/iam/organization/?limit=500" \
  | $PY -c "import sys,json;items=json.load(sys.stdin)['items'];matches=[i['id'] for i in items if i['code']=='smoke-test-org'];print(matches[0] if matches else '')")
if [[ -n "$EXISTING_ORG_ID" ]]; then
  curl -sf -X DELETE -H "Authorization: Bearer $TOKEN" \
    "$API_URL/api/iam/organization/$EXISTING_ORG_ID"
fi
# Held in a shell variable rather than a temp file: `$PY` may be a native
# Windows python, which cannot open the MSYS path `/tmp/...` that this
# shell would hand it.
ORG_JSON=$(curl -sf -X POST "$API_URL/api/iam/organization/" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"code":"smoke-test-org","name":"Smoke Test Org","is_active":true}')
echo "$ORG_JSON"
echo "$ORG_JSON" | grep -q '"code":"smoke-test-org"'
SMOKE_ORG_ID=$(echo "$ORG_JSON" | $PY -c "import sys,json;print(json.load(sys.stdin)['id'])")

echo "== Checking a NUL byte in a query parameter is a 422, not a 500 =="
# Regression guard for the request-level NUL guard (app/core/nul_guard.py):
# psycopg2 refuses to adapt a string containing U+0000 with a bare
# ValueError, which `translate_db_error` cannot see, so every one of these
# used to be an unhandled 500 reachable by pasting a URL.
NUL_STATUS=$(curl -s -o /dev/null -w "%{http_code}" -H "Authorization: Bearer $TOKEN" \
  "$API_URL/api/domain/?q=%00")
if [[ "$NUL_STATUS" != "422" ]]; then
  echo "expected 422 for a NUL in ?q=, got $NUL_STATUS"
  exit 1
fi

echo "== Checking the frontend serves and proxies /api to the backend =="
FRONTEND_STATUS=$(curl -sf -o /dev/null -w "%{http_code}" "$WEB_URL")
[[ "$FRONTEND_STATUS" == "200" ]]
curl -sf "$WEB_URL/api/health" | grep -q '"postgres":"ok"'

echo "== All smoke checks passed =="
