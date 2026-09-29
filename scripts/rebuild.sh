#!/usr/bin/env bash
set -euo pipefail

# Neither the backend nor the frontend Docker image has a bind mount, so
# code changes under backend/ or frontend/ are invisible to the running
# containers until their images are rebuilt and the containers recreated
# from them. This script is the one-liner for that: rebuild both images
# and recreate both services, then confirm each is actually serving.

# `docker compose up -d --force-recreate` returns as soon as the containers
# are started, not once they're accepting connections -- a bare curl right
# after it is a normal startup race, not a real failure. Retry each health
# check for up to 15 attempts (2s apart, ~30s) before giving up for real.
wait_for_backend() {
    local attempt
    for attempt in $(seq 1 15); do
        if curl -fsS http://localhost:8010/api/health; then
            echo
            return 0
        fi
        echo "waiting for backend... (${attempt}/15)"
        sleep 2
    done
    echo "backend did not become healthy after 15 attempts" >&2
    return 1
}

wait_for_frontend() {
    local attempt
    for attempt in $(seq 1 15); do
        if curl -fsS -o /dev/null http://localhost:3010/; then
            return 0
        fi
        echo "waiting for frontend... (${attempt}/15)"
        sleep 2
    done
    echo "frontend did not become ready after 15 attempts" >&2
    return 1
}

echo "== Building backend and frontend images =="
docker compose build backend frontend

# New code can need new tables: bring the database to the migrations the
# fresh backend image carries before the containers start serving it.
echo "== Applying database migrations =="
docker compose run --rm backend alembic upgrade head

echo "== Recreating backend and frontend containers =="
docker compose up -d --force-recreate backend frontend

echo "== Checking backend health =="
wait_for_backend

echo "== Checking frontend is serving =="
wait_for_frontend

echo "== Rebuild complete =="
