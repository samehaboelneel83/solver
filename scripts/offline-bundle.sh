#!/usr/bin/env bash
# Build a transferrable offline image bundle (OAAS O01).
# Usage: bash scripts/offline-bundle.sh [outdir]
# Writes digests.txt, *.tar archives, and copies offline docs into outdir.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="${1:-$ROOT/dist/offline-bundle}"
mkdir -p "$OUT"

echo "==> Building app images"
docker compose -f "$ROOT/docker-compose.yml" build backend frontend

IMAGES=(
  "solver-backend:latest"
  "solver-frontend:latest"
  "postgres:16"
  "clickhouse/clickhouse-server:24.8"
)

# Pull base images if missing (online build host only).
for img in "postgres:16" "clickhouse/clickhouse-server:24.8"; do
  docker image inspect "$img" >/dev/null 2>&1 || docker pull "$img"
done

# Frontend compose service may not tag solver-frontend:latest — ensure a tag.
if ! docker image inspect solver-frontend:latest >/dev/null 2>&1; then
  # Prefer the compose project image name if present.
  CID="$(docker compose -f "$ROOT/docker-compose.yml" images -q frontend 2>/dev/null | head -n1 || true)"
  if [[ -n "${CID:-}" ]]; then
    docker tag "$CID" solver-frontend:latest
  fi
fi

: >"$OUT/digests.txt"
for img in "${IMAGES[@]}"; do
  if ! docker image inspect "$img" >/dev/null 2>&1; then
    echo "missing image: $img" >&2
    exit 1
  fi
  digest="$(docker image inspect --format '{{index .RepoDigests 0}}' "$img" 2>/dev/null || true)"
  id="$(docker image inspect --format '{{.Id}}' "$img")"
  echo "$img  id=$id  digest=${digest:-none}" | tee -a "$OUT/digests.txt"
  safe="$(echo "$img" | tr '/:' '__')"
  echo "==> Saving $img -> $safe.tar"
  docker save -o "$OUT/$safe.tar" "$img"
done

cp "$ROOT/docs/runbooks/offline-install.md" "$OUT/"
cp "$ROOT/docs/offline-dependency-manifest.md" "$OUT/"
cp "$ROOT/docs/coverage-acceptance-matrix.md" "$OUT/"
cp "$ROOT/deploy/compose/docker-compose.digests.example.yml" "$OUT/" 2>/dev/null || true

(
  cd "$OUT"
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum ./*.tar digests.txt > SHA256SUMS
  elif command -v shasum >/dev/null 2>&1; then
    shasum -a 256 ./*.tar digests.txt > SHA256SUMS
  fi
)

echo "==> Bundle ready in $OUT"
cat "$OUT/digests.txt"
