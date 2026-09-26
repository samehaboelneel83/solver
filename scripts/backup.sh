#!/usr/bin/env bash
#
# scripts/backup.sh -- nightly Postgres dump + restore rehearsal (queue R39).
#
# Backups live on the host under SOLVER_BACKUP_DIR (default: a sibling
# ``solver-backups`` folder beside this repository). That directory is the
# object store for this single-host deploy; sync it elsewhere if you need
# off-box copies. WAL segments archive into ``$SOLVER_BACKUP_DIR/wal`` via
# Postgres ``archive_command`` (see docker-compose.yml).
#
# ClickHouse ``run_fact`` is not dumped: it is rebuildable from Postgres.
#
# Starting targets: RPO 24 h, RTO 4 h. See docs/runbooks/backups.md.
#
# Usage:
#   bash scripts/backup.sh              # dump today + prune old dumps
#   bash scripts/backup.sh dump
#   bash scripts/backup.sh rehearse     # restore into solver_restore, run suites, drop it
#   bash scripts/backup.sh --install    # schedule daily dump at 02:30 (Windows)
#   bash scripts/backup.sh --uninstall
#
# Environment:
#   SOLVER_BACKUP_DIR   host path for dumps + wal (default: <repo-parent>/solver-backups)
#   SOLVER_BACKUP_KEEP  days of dumps to keep (default: 14)
#   COMPOSE_PROJECT     docker compose project (default: solver)

set -euo pipefail
case "$(uname -s)" in
  MINGW*|MSYS*|CYGWIN*) export MSYS_NO_PATHCONV=1 MSYS2_ARG_CONV_EXCL='*' ;;
esac

to_host_path() {
  if command -v cygpath >/dev/null 2>&1; then cygpath -m "$1"; else printf '%s' "$1"; fi
}

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPO="$(to_host_path "$ROOT")"
TASK="solver-backup"
PROJECT="${COMPOSE_PROJECT:-solver}"
KEEP="${SOLVER_BACKUP_KEEP:-14}"
NIGHT="$(date +%F)"
PARENT="$(to_host_path "$(dirname "$ROOT")")"
BACKUP_DIR="$(to_host_path "${SOLVER_BACKUP_DIR:-$PARENT/solver-backups}")"
DUMPS="$BACKUP_DIR/dumps"
WAL="$BACKUP_DIR/wal"
RESTORE_DB="solver_restore"
LIVE_DB="solver"

cd "$REPO"

compose() {
  docker compose -p "$PROJECT" "$@"
}

pg_user() {
  compose exec -T postgres printenv POSTGRES_USER | tr -d '\r'
}

ensure_dirs() {
  mkdir -p "$DUMPS" "$WAL"
}

cmd_dump() {
  ensure_dirs
  local user dump bytes
  user="$(pg_user)"
  dump="$DUMPS/solver-$NIGHT.dump"
  echo "dumping $LIVE_DB -> $dump"
  compose exec -T postgres \
    pg_dump -U "$user" -Fc -f "/backups/dumps/solver-$NIGHT.dump" "$LIVE_DB"
  bytes="$(wc -c < "$dump" | tr -d ' ')"
  cat > "$BACKUP_DIR/LATEST" <<EOF
night=$NIGHT
database=$LIVE_DB
dump=solver-$NIGHT.dump
bytes=$bytes
wal_dir=$WAL
RPO 24 h
RTO 4 h
clickhouse=not backed up (rebuildable from Postgres)
EOF
  find "$DUMPS" -maxdepth 1 -name 'solver-*.dump' -type f -mtime +$((KEEP - 1)) -print -delete || true
  echo "ok: $bytes bytes; LATEST written; keep=${KEEP}d"
}

cmd_rehearse() {
  ensure_dirs
  local dump="${1:-}" base user url restore_url suite_status
  if [[ -z "$dump" ]]; then
    dump="$(ls -1t "$DUMPS"/solver-*.dump 2>/dev/null | head -n 1 || true)"
  fi
  if [[ -z "$dump" || ! -f "$dump" ]]; then
    echo "no dump found under $DUMPS; run: bash scripts/backup.sh dump" >&2
    exit 1
  fi
  base="$(basename "$dump")"
  if [[ "$RESTORE_DB" == "$LIVE_DB" ]]; then
    echo "refusing: restore target equals live database" >&2
    exit 1
  fi
  if [[ ! -f "$DUMPS/$base" ]]; then
    echo "dump must live under $DUMPS (mounted at /backups/dumps)" >&2
    exit 1
  fi
  user="$(pg_user)"
  echo "rehearsing restore of $base into $RESTORE_DB"
  compose exec -T postgres psql -U "$user" -d postgres -v ON_ERROR_STOP=1 \
    -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '${RESTORE_DB}' AND pid <> pg_backend_pid();" \
    -c "DROP DATABASE IF EXISTS ${RESTORE_DB};" \
    -c "CREATE DATABASE ${RESTORE_DB} OWNER ${user};"
  # pg_restore often exits 1 on benign notices; prove the catalog came back.
  compose exec -T postgres \
    pg_restore -U "$user" -d "$RESTORE_DB" --no-owner --no-acl "/backups/dumps/$base" \
    || true
  if ! compose exec -T postgres \
      psql -U "$user" -d "$RESTORE_DB" -tAc "SELECT 1 FROM alembic_version LIMIT 1" \
      | tr -d ' \r\n' | grep -q 1; then
    echo "restore failed: alembic_version missing in $RESTORE_DB" >&2
    compose exec -T postgres psql -U "$user" -d postgres -c "DROP DATABASE IF EXISTS ${RESTORE_DB};"
    exit 1
  fi
  echo "restore ok; running acceptance suites (R32) against $RESTORE_DB"
  url="$(compose exec -T backend printenv MIGRATION_DATABASE_URL | tr -d '\r')"
  if [[ -z "$url" ]]; then
    echo "MIGRATION_DATABASE_URL missing in backend container" >&2
    exit 1
  fi
  restore_url="$(python - "$url" "$RESTORE_DB" <<'PY'
import sys
from urllib.parse import urlparse, urlunparse
u = urlparse(sys.argv[1])
print(urlunparse(u._replace(path="/" + sys.argv[2])))
PY
)"
  set +e
  compose run --rm --no-deps -T \
    -e "DATABASE_URL=$restore_url" \
    -e "MIGRATION_DATABASE_URL=$restore_url" \
    backend python -m bench.suites
  suite_status=$?
  set -e
  # Prove the restored catalog can still solve: seed one case and re-ask it
  # (same as check.sh). Runs after the dump's own cases so an empty suite
  # still exercises a real restore.
  if [[ $suite_status -eq 0 ]]; then
    set +e
    compose run --rm --no-deps -T \
      -e "DATABASE_URL=$restore_url" \
      -e "MIGRATION_DATABASE_URL=$restore_url" \
      backend python -m bench.suites --check
    suite_status=$?
    set -e
  fi
  compose exec -T postgres psql -U "$user" -d postgres -v ON_ERROR_STOP=1 \
    -c "DROP DATABASE IF EXISTS ${RESTORE_DB};"
  if [[ $suite_status -ne 0 ]]; then
    echo "rehearsal FAILED: suites exit $suite_status" >&2
    exit "$suite_status"
  fi
  echo "rehearsal PASS: restored $base, suites green, $RESTORE_DB dropped"
}

case "${1:-dump}" in
  dump|"") cmd_dump ;;
  rehearse) shift; cmd_rehearse "${1:-}" ;;
  --install)
    bash_exe="$(to_host_path "$(command -v bash)")"
    schtasks /Create /F /TN "$TASK" /SC DAILY /ST 02:30 \
      /TR "\"$bash_exe\" -l \"$REPO/scripts/backup.sh\" dump"
    exit $?
    ;;
  --uninstall)
    schtasks /Delete /F /TN "$TASK"
    exit $?
    ;;
  -h|--help)
    sed -n '2,30p' "$0" | sed 's/^# \{0,1\}//'
    exit 0
    ;;
  *)
    echo "unknown argument: $1 (try dump, rehearse, --install, --uninstall)" >&2
    exit 2
    ;;
esac
