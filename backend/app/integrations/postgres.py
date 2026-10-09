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
    #: The database engine (app/integrations/databases.py): postgres, mysql, sqlserver or oracle.
    engine: str = "postgres"
    #: A column that grows when a row changes (an update time, a version): lets a read take only what changed
    #: (migration 0118). One of `columns`; empty when the source is always read whole.
    changed_column: str = ""
    #: Further tables of the same database read with it, as one source (each `(table, columns, changed_column)`):
    #: one extraction, a sheet per table (handover of 8 October 2026).
    more_tables: tuple = ()

    def __post_init__(self):
        if self.engine not in ("postgres", "mysql", "sqlserver", "oracle"):
            raise ValueError("Unknown database engine")
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
        if self.changed_column and self.changed_column not in self.columns:
            raise ValueError("The changed column must be one of the columns read")
        names = [self.table]
        for entry in self.more_tables:
            table, columns, changed = (tuple(entry) + ("",))[:3]
            if not table or "\x00" in table or not columns or len(set(columns)) != len(columns) \
                    or any(not c or "\x00" in c for c in columns):
                raise ValueError("Invalid source identifiers")
            if changed and changed not in columns:
                raise ValueError("The changed column must be one of the columns read")
            names.append(table)
        if len(set(names)) != len(names):
            raise ValueError("A table is named twice")

    def tables(self) -> list[tuple[str, tuple[str, ...], str]]:
        """Every table the source reads: (table, columns, changed column), the first one first."""
        return [(self.table, tuple(self.columns), self.changed_column)] + [
            (str(t[0]), tuple(t[1]), str((tuple(t) + ("",))[2] or "")) for t in self.more_tables]

    def columns_of(self, table: str) -> tuple[str, ...] | None:
        return next((columns for name, columns, _ in self.tables() if name == table), None)


def resolve_address(source: PostgresSource) -> str:
    networks = [ipaddress.ip_network(network) for network in source.allowed_networks]
    try:
        addresses = sorted({item[4][0] for item in socket.getaddrinfo(source.host, source.port, type=socket.SOCK_STREAM)})
    except OSError:
        raise ExtractionError("The database host name does not resolve from the import worker", "source_unreachable") from None
    if not addresses or any(not any(ipaddress.ip_address(address) in network for network in networks) for address in addresses):
        raise ExtractionError("Database address is outside the allowed networks", "network_not_allowed")
    return addresses[0]


# SQLSTATE classes and codes (PostgreSQL appendix A) -> a safe failure class.
_STATE_CODES = {
    "28P01": "authentication_failed", "28000": "authentication_failed",
    "42501": "not_permitted",
    "3D000": "source_missing", "3F000": "source_missing", "42P01": "source_missing", "42703": "source_missing",
    "57014": "deadline_exceeded",
}
# libpq reports failures before the server answers (connect, TLS, startup) without a SQLSTATE; the class
# is read from its message here and only the class is kept -- the message itself is never stored or sent.
_CONNECT_PHRASES = (
    ("password authentication failed", "authentication_failed"),
    ("no pg_hba.conf entry", "authentication_failed"),
    ("role \"", "authentication_failed"),
    ("certificate", "tls_failed"),
    ("ssl", "tls_failed"),
    ("server does not support", "tls_failed"),
    ("database \"", "source_missing"),
    ("timeout expired", "source_unreachable"),
    ("could not connect", "source_unreachable"),
    ("connection refused", "source_unreachable"),
    ("could not translate host name", "source_unreachable"),
    ("no route to host", "source_unreachable"),
)


def failure_code(error: BaseException) -> str:
    """The safe class of a driver failure: what to fix, without the driver's words."""
    state = getattr(error, "pgcode", None)
    if state in _STATE_CODES:
        return _STATE_CODES[state]
    if state and state.startswith("28"):
        return "authentication_failed"
    if state and state.startswith("08"):
        return "source_unreachable"
    if isinstance(error, psycopg2.OperationalError) and not state:
        said = str(error).lower()
        for phrase, code in _CONNECT_PHRASES:
            if phrase in said:
                return code
        return "source_unreachable"
    return "extraction_failed"


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
        allowed = source.columns_of(request.source_object)
        if allowed is None or not set(request.columns).issubset(allowed):
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
                raise ExtractionError("Local database trust certificate is unavailable", "trust_unavailable")
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
                select = sql.SQL("SELECT {} FROM {}.{}").format(
                    sql.SQL(", ").join(sql.Identifier(column) for column in request.columns),
                    sql.Identifier(source.schema), sql.Identifier(request.source_object),
                )
                if request.since_column and request.since is not None:
                    # Only what changed since the last read; >= so rows stamped in the same instant are not lost.
                    cursor.execute(select + sql.SQL(" WHERE {} >= %s").format(sql.Identifier(request.since_column)),
                                   (request.since,))
                else:
                    cursor.execute(select)
                while True:
                    if cancelled.is_set():
                        raise ExtractionCancelled("Extraction cancelled")
                    if interrupted.is_set() or time.monotonic() >= deadline:
                        raise ExtractionError("Extraction deadline exceeded", "deadline_exceeded")
                    rows = cursor.fetchmany(request.limits.batch_rows)
                    if not self.source_schema:
                        self.source_schema = [{"name": column.name, "postgres_oid": column.type_code}
                                              for column in cursor.description]
                    if not rows:
                        break
                    for row in rows:
                        if interrupted.is_set() or time.monotonic() >= deadline:
                            raise ExtractionError("Extraction deadline exceeded", "deadline_exceeded")
                        yield dict(zip(request.columns, (encode_value(value) for value in row), strict=True))
        except ExtractionError:
            raise
        except Exception as error:
            if cancelled.is_set():
                raise ExtractionCancelled("Extraction cancelled") from None
            code = "deadline_exceeded" if interrupted.is_set() else failure_code(error)
            raise ExtractionError("PostgreSQL extraction failed; check connection and source permissions", code) from None
        finally:
            finished.set()
            if watcher is not None:
                watcher.join(timeout=1)
            if connection is not None:
                try:
                    connection.close()  # Closing rolls back the read-only transaction.
                except Exception:
                    raise ExtractionError("PostgreSQL connection cleanup failed") from None
