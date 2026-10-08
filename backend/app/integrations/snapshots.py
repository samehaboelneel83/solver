"""Atomic local extraction artifacts, deliberately not optimization-ready datasets."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from threading import Event
from uuid import uuid4

from .contracts import ExtractionCancelled, ExtractionRequest, SnapshotConnector, extract_batches, later


def stage_snapshot(
    root: Path, connector: SnapshotConnector, request: ExtractionRequest, cancelled: Event,
) -> Path:
    """Write rows and a manifest, then rename the complete directory into view.

    The root is an operator-controlled storage directory, not a user path. There
    is no mutable 'latest' pointer. Failed extraction never changes prior imports.
    Readers must ignore .pending-* directories. Only authorized worker code may
    call this function; it does not substitute for application grants or RLS.
    """
    folder = root.resolve() / str(request.organization_id) / str(request.connection_id)
    folder.mkdir(parents=True, exist_ok=True)
    pending = Path(tempfile.mkdtemp(prefix=".pending-", dir=folder))
    identity = str(uuid4())
    target = folder / identity
    started = datetime.now(timezone.utc).isoformat()
    count = size = 0
    digest = hashlib.sha256()
    high = None  # the highest value of the changed column read (migration 0118)
    watched = request.since_column
    try:
        stream = extract_batches(connector, request, cancelled)
        try:
            with (pending / "rows.jsonl").open("xb") as output:
                for batch in stream:
                    for row in batch:
                        output.write(row)
                        digest.update(row)
                        if watched:
                            high = later(high, json.loads(row).get(watched))
                        count += 1
                        size += len(row)
                output.flush()
                os.fsync(output.fileno())
        finally:
            stream.close()
        if cancelled.is_set():
            raise ExtractionCancelled("Extraction cancelled")
        manifest = {
            "format_version": 1, "id": identity,
            "organization_id": str(request.organization_id), "connection_id": request.connection_id,
            "source_object": request.source_object, "columns": list(request.columns),
            "connector": connector.capabilities.connector_id, "connector_version": connector.capabilities.version,
            "source_schema": getattr(connector, "source_schema", []),
            "encoding": "canonical-json-lines-v1",
            "conversion": "Decimals and unsafe integers are strings; temporal values are ISO 8601; UUIDs are strings. Mapping must declare target types.",
            "started_at": started, "completed_at": datetime.now(timezone.utc).isoformat(),
            "rows": count, "bytes": size, "sha256": digest.hexdigest(),
            "status": "extracted_requires_mapping_validation",
            # An incremental read says so, and every read of a source with a changed column keeps its highest
            # value: where the next incremental read starts.
            **({"changed_column": watched, "high_water": high} if watched else {}),
            **({"since": request.since} if watched and request.since is not None else {}),
        }
        with (pending / "manifest.json").open("x", encoding="utf-8") as output:
            json.dump(manifest, output, ensure_ascii=False, indent=2)
            output.flush()
            os.fsync(output.fileno())
        if cancelled.is_set():
            raise ExtractionCancelled("Extraction cancelled")
        pending.rename(target)
        return target
    except BaseException:
        # Only this invocation's generated staging directory is removed.
        shutil.rmtree(pending)
        raise
