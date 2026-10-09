"""Reading an extraction's artifact from the API (Epic UX, U-4).

The worker writes `<root>/<organization>/<connection>/<artifact id>/` with
`rows.jsonl` and `manifest.json` (`snapshots.stage_snapshot`); the API reads it
through `OAAS_INTEGRATION_OUTPUT`, mounted read-only. A path is built only from
ids the database holds for the caller's organization, and must resolve inside
the root. A load reads every row and checks the SHA-256 against the manifest, so
what is loaded is exactly what was extracted and validated.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from uuid import UUID


class ArtifactUnavailable(Exception):
    """The artifact cannot be read here: no storage configured, or the files are gone."""


class ArtifactChanged(Exception):
    """The rows no longer hash to what the manifest (and the validation) recorded."""


def root() -> Path:
    configured = os.environ.get("OAAS_INTEGRATION_OUTPUT")
    if not configured:
        raise ArtifactUnavailable("this server has no integration artifact storage (OAAS_INTEGRATION_OUTPUT)")
    return Path(configured).resolve()


def folder(organization_id, connection_id: int, artifact_id) -> Path:
    base = root()
    path = (base / str(UUID(str(organization_id))) / str(int(connection_id)) / str(UUID(str(artifact_id)))).resolve()
    if base not in path.parents:
        raise ArtifactUnavailable("the artifact path is outside the storage root")
    if not (path / "manifest.json").is_file() or not (path / "rows.jsonl").is_file():
        raise ArtifactUnavailable("the extracted files are no longer in storage; run the extraction again")
    return path


def manifest(path: Path) -> dict:
    with (path / "manifest.json").open(encoding="utf-8") as handle:
        return json.load(handle)


def tables(manifest: dict) -> list[dict]:
    """The tables an extraction holds, the first first: each {file, source_object, columns, rows, sha256, ...}. A
    one-table extraction is its manifest's own fields in `rows.jsonl`."""
    listed = manifest.get("tables")
    if listed:
        return list(listed)
    return [{"file": "rows.jsonl", **{k: manifest.get(k) for k in ("source_object", "columns", "rows", "sha256",
                                                                     "changed_column", "high_water", "since")
                                      if manifest.get(k) is not None}}]


def table(manifest: dict, name: str | None) -> dict:
    """One table of an extraction by its name; the first when no name is given."""
    found = tables(manifest)
    if not name:
        return found[0]
    for entry in found:
        if entry.get("source_object") == name:
            return entry
    raise ArtifactUnavailable(f"this extraction has no table {name!r}")


def _file(path: Path, name: str) -> Path:
    target = (path / name).resolve()
    if target.parent != path or not target.name.startswith("rows") or not target.is_file():
        raise ArtifactUnavailable("the extracted files are no longer in storage; run the extraction again")
    return target


def head(path: Path, limit: int, file: str = "rows.jsonl") -> list[dict]:
    """The first `limit` rows, for a preview."""
    rows: list[dict] = []
    with _file(path, file).open("rb") as handle:
        for line in handle:
            if len(rows) >= limit:
                break
            rows.append(json.loads(line))
    return rows


def verified_rows(path: Path, expected_sha256: str, max_rows: int, file: str = "rows.jsonl") -> list[dict]:
    """Every row, checked against the manifest's hash. Raises `ArtifactChanged` if they differ."""
    digest = hashlib.sha256()
    rows: list[dict] = []
    with _file(path, file).open("rb") as handle:
        for line in handle:
            digest.update(line)
            if len(rows) >= max_rows:
                raise ArtifactUnavailable(f"the extraction has more than {max_rows:,} rows, more than one import takes")
            rows.append(json.loads(line))
    if digest.hexdigest() != expected_sha256:
        raise ArtifactChanged("the extracted rows changed since they were written; run the extraction again")
    return rows
