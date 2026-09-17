#!/usr/bin/env bash
set -euo pipefail

# Neither the backend nor the frontend Docker image has a bind mount, so
# code changes under backend/ or frontend/ are invisible to the running
# containers until their images are rebuilt and the containers recreated
# from them. This script is the one-liner for that: rebuild both images
# and recreate both services, then confirm each is actually serving.

echo "== Building backend and frontend images =="
docker compose build backend frontend

echo "== Recreating backend and frontend containers =="
docker compose up -d --force-recreate backend frontend

echo "== Checking backend health =="
curl -fsS http://localhost:8010/api/health
echo
echo "== Checking frontend is serving =="
curl -fsS -o /dev/null http://localhost:3010/

echo "== Rebuild complete =="
