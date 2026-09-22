#!/usr/bin/env bash
#
# scripts/runtime_role.sh -- make the app log in as `solver_runtime`.
#
# Migration 0037 creates the role without a login; this gives it one, with
# a fresh random password, and writes the URL the backend and worker use to
# `.env.runtime` (gitignored). docker-compose.yml reads that file after
# `.env`, so its DATABASE_URL wins; migrations keep the owner's URL.
#
# Run it after `alembic upgrade head` has reached 0037, then restart:
#   bash scripts/runtime_role.sh
#   docker compose up -d --no-build backend worker
# Running it again rotates the password. Deleting `.env.runtime` and
# restarting goes back to the owner's login.
#
# The password is never printed: it goes from the container straight into
# the file.

set -euo pipefail
case "$(uname -s)" in
  MINGW*|MSYS*|CYGWIN*) export MSYS_NO_PATHCONV=1 MSYS2_ARG_CONV_EXCL='*' ;;
esac

cd "$(dirname "${BASH_SOURCE[0]}")/.."

tmp=".env.runtime.tmp"
umask 077
docker compose run --rm --no-deps -T backend python -m app.runtime_role > "$tmp"
if ! grep -q '^DATABASE_URL=postgresql[^:]*://solver_runtime:' "$tmp"; then
  rm -f "$tmp"
  echo "runtime_role: no URL came back; .env.runtime left as it was" >&2
  exit 1
fi
# Only the URL line: anything else compose printed would break env_file.
grep '^DATABASE_URL=' "$tmp" > .env.runtime
rm -f "$tmp"
echo "wrote .env.runtime; restart with: docker compose up -d --no-build backend worker"
