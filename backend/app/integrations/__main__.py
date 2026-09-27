"""Operator-only offline extraction command; not an authenticated application API."""
import argparse
import json
import os
import signal
import sys
from pathlib import Path
from threading import Event
from uuid import UUID

from .contracts import ExtractionError, ExtractionLimits, ExtractionRequest
from .postgres import PostgresConnector, PostgresSource
from .snapshots import stage_snapshot


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Extract a permitted PostgreSQL table into a local staging snapshot.")
    parser.add_argument("--config", type=Path, required=True, help="Operator-owned connection JSON; no embedded password")
    parser.add_argument("--output", type=Path, required=True, help="Private local artifact root")
    parser.add_argument("--max-rows", type=int, default=100_000)
    parser.add_argument("--max-bytes", type=int, default=20 * 1024 * 1024)
    parser.add_argument("--batch-rows", type=int, default=1_000)
    args = parser.parse_args(argv)
    cancelled = Event()
    previous = signal.signal(signal.SIGINT, lambda *_: cancelled.set())
    try:
        config = json.loads(args.config.read_text(encoding="utf-8"))
        config["organization_id"] = UUID(config["organization_id"])
        config["columns"] = tuple(config["columns"])
        config["allowed_networks"] = tuple(config["allowed_networks"])
        source = PostgresSource(**config)
        limits = ExtractionLimits(args.max_rows, args.max_bytes, args.batch_rows)
        request = ExtractionRequest(source.organization_id, source.connection_id, source.table, source.columns, limits)

        def secret(reference):
            # A trusted operator chooses the environment reference. No secrets
            # are accepted on the command line or persisted in the manifest.
            value = os.environ.get(reference)
            if not value:
                raise ExtractionError("Connection secret is not available in the worker environment")
            return value

        target = stage_snapshot(args.output, PostgresConnector(source, secret), request, cancelled)
        print(json.dumps({"artifact": str(target), "status": "extracted_requires_mapping_validation"}))
        return 0
    except (ExtractionError, ValueError, TypeError, KeyError, OSError):
        # Configuration/driver errors may contain secrets or source details.
        print("Extraction failed. Check local configuration, trust, permissions and extraction limits. No completed artifact was published.", file=sys.stderr)
        return 1
    finally:
        signal.signal(signal.SIGINT, previous)


if __name__ == "__main__":
    raise SystemExit(main())
