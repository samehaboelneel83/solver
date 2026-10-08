"""Driver-independent, bounded extraction contract (ENH-04).

Rows carry canonical JSON-compatible values. Precision-sensitive source values
must be encoded losslessly by adapters and described by their schema. This layer
does not store credentials, open connections, publish snapshots, or advance a
durable checkpoint: those are responsibilities of the authorized job worker.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from threading import Event
from typing import Iterable, Iterator, Mapping, Protocol
from uuid import UUID


# Why an extraction failed, safe to show: a class of cause, never driver text or credentials.
FAILURE_CODES = frozenset({
    "extraction_failed", "authentication_failed", "tls_failed", "source_unreachable", "network_not_allowed",
    "source_missing", "not_permitted", "trust_unavailable", "credential_unreadable", "deadline_exceeded",
    "limit_exceeded", "format_invalid",
})


class ExtractionError(Exception):
    """Safe public error; driver exception text must not be included."""

    def __init__(self, message: str = "", code: str = "extraction_failed"):
        super().__init__(message)
        self.code = code if code in FAILURE_CODES else "extraction_failed"


class ExtractionCancelled(ExtractionError):
    pass


class ExtractionLimitExceeded(ExtractionError):
    def __init__(self, message: str = "", code: str = "limit_exceeded"):
        super().__init__(message, code)


@dataclass(frozen=True)
class ConnectorCapabilities:
    connector_id: str
    version: str
    snapshot: bool = True
    incremental: bool = False
    deletes: bool = False
    publish: bool = False


@dataclass(frozen=True)
class ExtractionLimits:
    max_rows: int = 100_000
    max_bytes: int = 20 * 1024 * 1024
    batch_rows: int = 1_000

    def __post_init__(self) -> None:
        for value in (self.max_rows, self.max_bytes, self.batch_rows):
            if type(value) is not int or value <= 0:
                raise ValueError("Extraction limits must be positive integers")
        if self.batch_rows > self.max_rows:
            raise ValueError("Batch size must not exceed the row limit")


@dataclass(frozen=True)
class ExtractionRequest:
    organization_id: UUID
    connection_id: int
    source_object: str
    columns: tuple[str, ...]
    limits: ExtractionLimits = ExtractionLimits()

    def __post_init__(self) -> None:
        if not isinstance(self.organization_id, UUID):
            raise ValueError("Organization ID must be a UUID")
        if type(self.connection_id) is not int or self.connection_id <= 0:
            raise ValueError("Connection ID must be a positive integer")
        if not self.source_object or not self.columns or any(not column for column in self.columns):
            raise ValueError("A source and explicit columns are required")
        if len(set(self.columns)) != len(self.columns):
            raise ValueError("Columns must be unique")


class SnapshotConnector(Protocol):
    capabilities: ConnectorCapabilities

    def extract(self, request: ExtractionRequest, cancelled: Event) -> Iterable[Mapping[str, object]]:
        """Stream rows; enforce source timeout/cancellation and close driver resources.

        The job worker must authorize the connection against organization_id.
        Source identifiers are identifiers, never executable SQL fragments.
        """
        ...


def _canonical_value(value: object) -> bool:
    if value is None or type(value) in (str, bool):
        return True
    if type(value) is int:
        return abs(value) <= 2**53 - 1
    if type(value) is float:
        return math.isfinite(value)
    if type(value) is list:
        return all(_canonical_value(item) for item in value)
    if type(value) is dict:
        return all(type(key) is str and _canonical_value(item) for key, item in value.items())
    return False


def extract_batches(
    connector: SnapshotConnector, request: ExtractionRequest, cancelled: Event,
) -> Iterator[tuple[bytes, ...]]:
    """Yield immutable UTF-8 JSON lines within cumulative row/byte budgets.

    Output is staging data only. A consumer must never publish earlier batches
    if a later batch fails validation. Byte counts include newline delimiters.
    Driver prefetch/memory and blocking I/O deadlines need independent limits.
    """
    if not connector.capabilities.snapshot:
        raise ExtractionError("This connector does not support snapshot extraction")
    if cancelled.is_set():
        raise ExtractionCancelled("Extraction cancelled")
    try:
        rows = iter(connector.extract(request, cancelled))
    except Exception:
        raise ExtractionError("Source extraction could not start") from None
    batch: list[bytes] = []
    count = size = 0
    try:
        while True:
            if cancelled.is_set():
                raise ExtractionCancelled("Extraction cancelled")
            try:
                row = next(rows)
            except StopIteration:
                break
            if cancelled.is_set():
                raise ExtractionCancelled("Extraction cancelled")
            if set(row) != set(request.columns):
                raise ExtractionError("Source columns do not match the requested schema")
            record = dict(row)
            if not _canonical_value(record):
                raise ExtractionError("Source values require an explicit lossless conversion")
            encoded = (json.dumps(record, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":")) + "\n").encode("utf-8")
            count += 1
            size += len(encoded)
            if count > request.limits.max_rows or size > request.limits.max_bytes:
                raise ExtractionLimitExceeded("Extraction exceeded its row or byte budget")
            batch.append(encoded)
            if len(batch) == request.limits.batch_rows:
                yield tuple(batch)
                batch = []
        if batch:
            yield tuple(batch)
    except ExtractionError:
        raise
    except Exception:
        raise ExtractionError("Source extraction failed") from None
    finally:
        close = getattr(rows, "close", None)
        if close is not None:
            try:
                close()
            except Exception:
                raise ExtractionError("Source cleanup failed") from None
