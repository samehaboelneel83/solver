"""Read-only PostgreSQL snapshot adapter; configured by trusted local operators.

No HTTP endpoint accepts this configuration. Secrets are resolved only after
scope, source and network checks. Existing psycopg2 is used without new packages.
"""
from __future__ import annotations

import ipaddress
import socket
import time
from dataclasses import dataclass, field
from datetime import date, datetime, time as daytime
from decimal import Decimal
from pathlib import Path
from threading import Event, Thread
from typing import Callable
from uuid import UUID

import psycopg2
from psycopg2 import sql

from .contracts import ConnectorCapabilities, ExtractionCancelled, ExtractionError, ExtractionRequest


@dataclass(frozen=True)
class PostgresSource:
    organization_id: UUID
    connection_id: int
    host: str
    database: str
    username: str
    secret_ref: str = field(repr=False)
    schema: str
    table: str
    columns: tuple[str, ...]
    allowed_networks: tuple[str, ...]
    root_certificate: str
    port: int = 5432
    connect_timeout_seconds: int = 10
    statement_timeout_ms: int = 30_000
    extraction_timeout_seconds: int = 300

    def __post_init__(self):
        if not isinstance(self.organization_id, UUID) or type(self.connection_id) is not int or self.connection_id <= 0:
            raise ValueError("Invalid connection scope")
        if not self.host or any(character in self.host for character in (",", "/", "\\", "\x00")):
            raise ValueError("A single database host is required")
        if not all((self.database, self.username, self.secret_ref, self.schema, self.table, self.columns, self.allowed_networks, self.root_certificate)):
            raise ValueError("Connection, trust and source settings are required")
        if len(set(self.columns)) != len(self.columns) or any(not name or "\x00" in name for name in (*self.columns, self.schema, self.table)):
            raise ValueError("Invalid source identifiers")
        if type(self.port) is not int or not 1 <= self.port <= 65535:
            raise ValueError("Invalid database port")
        for value in (self.connect_timeout_seconds, self.statement_timeout_ms, self.extraction_timeout_seconds):
            if type(value) is not int or value <= 0:
                raise ValueError("Timeouts must be positive integers")
        for network in self.allowed_networks:
            ipaddress.ip_network(network)


def resolve_address(source: PostgresSource) -> str:
    networks = [ipaddress.ip_network(network) for network in source.allowed_networks]
    addresses = sorted({item[4][0] for item in socket.getaddrinfo(source.host, source.port, type=socket.SOCK_STREAM)})
    if not addresses or any(not any(ipaddress.ip_address(address) in network for network in networks) for address in addresses):
        raise ExtractionError("Database address is outside the allowed networks")
    return addresses[0]


def encode_value(value):
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ExtractionError("Nonfinite source decimal")
        return str(value)
    if type(value) is int and abs(value) > 2**53 - 1:
        return str(value)
    if isinstance(value, (datetime, date, daytime)):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    # Other values pass through the strict canonical validator, which refuses
    # unsupported binary, array elements and nonfinite values without coercion.
    return value


class PostgresConnector:
    capabilities = ConnectorCapabilities("postgresql", "1")

    def __init__(self, source: PostgresSource, resolve_secret: Callable[[str], str]):
        self.source = source
        self._resolve_secret = resolve_secret
        self.source_schema: list[dict] = []

    def extract(self, request: ExtractionRequest, cancelled: Event):
        source = self.source
        self.source_schema = []
        if (request.organization_id, request.connection_id) != (source.organization_id, source.connection_id):
            raise ExtractionError("Connection scope mismatch")
        if request.source_object != source.table or not set(request.columns).issubset(source.columns):
            raise ExtractionError("Source object or columns are not permitted")
        if cancelled.is_set():
            raise ExtractionCancelled("Extraction cancelled")
        connection = None
        finished = Event()
        interrupted = Event()
        watcher = None
        try:
            address = resolve_address(source)
            if not Path(source.root_certificate).is_file():
                raise ExtractionError("Local database trust certificate is unavailable")
            connection = psycopg2.connect(
                host=source.host, hostaddr=address, port=source.port,
                dbname=source.database, user=source.username,
                password=self._resolve_secret(source.secret_ref),
                sslmode="verify-full", sslrootcert=source.root_certificate,
                connect_timeout=source.connect_timeout_seconds,
                application_name="oaas-extraction",
                options=f"-c statement_timeout={source.statement_timeout_ms} -c idle_in_transaction_session_timeout={source.statement_timeout_ms}",
            )
            connection.set_session(readonly=True, isolation_level="REPEATABLE READ", autocommit=False)
            deadline = time.monotonic() + source.extraction_timeout_seconds

            def watch():
                while not finished.wait(0.05):
                    if cancelled.is_set() or time.monotonic() >= deadline:
                        interrupted.set()
                        try:
                            connection.cancel()
                        except Exception:
                            pass  # Query timeout and worker deadline remain independent bounds.
                        return

            watcher = Thread(target=watch, daemon=True)
            watcher.start()
            with connection.cursor(name="oaas_snapshot") as cursor:
                cursor.itersize = request.limits.batch_rows
                cursor.execute(sql.SQL("SELECT {} FROM {}.{}").format(
                    sql.SQL(", ").join(sql.Identifier(column) for column in request.columns),
                    sql.Identifier(source.schema), sql.Identifier(source.table),
                ))
                while True:
                    if cancelled.is_set():
                        raise ExtractionCancelled("Extraction cancelled")
                    if interrupted.is_set() or time.monotonic() >= deadline:
                        raise ExtractionError("Extraction deadline exceeded")
                    rows = cursor.fetchmany(request.limits.batch_rows)
                    if not self.source_schema:
                        self.source_schema = [{"name": column.name, "postgres_oid": column.type_code}
                                              for column in cursor.description]
                    if not rows:
                        break
                    for row in rows:
                        if interrupted.is_set() or time.monotonic() >= deadline:
                            raise ExtractionError("Extraction deadline exceeded")
                        yield dict(zip(request.columns, (encode_value(value) for value in row), strict=True))
        except ExtractionError:
            raise
        except Exception:
            if cancelled.is_set():
                raise ExtractionCancelled("Extraction cancelled") from None
            raise ExtractionError("PostgreSQL extraction failed; check connection and source permissions") from None
        finally:
            finished.set()
            if watcher is not None:
                watcher.join(timeout=1)
            if connection is not None:
                try:
                    connection.close()  # Closing rolls back the read-only transaction.
                except Exception:
                    raise ExtractionError("PostgreSQL connection cleanup failed") from None
