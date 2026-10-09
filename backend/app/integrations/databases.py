"""Read-only snapshot adapters for MySQL / MariaDB, SQL Server and Oracle (plan of 8 October 2026, phase 4A).

One contract for every engine, the same as PostgreSQL's (`postgres.py`):
- the address is checked against the operator's approved networks before any credential is used;
- TLS is required and the server's certificate is verified against the operator's CA, by host name;
- a read-only transaction where the engine has one, a statement timeout, and the worker's own deadline;
- identifiers are quoted, never spliced as SQL; only `SELECT <columns> FROM <schema>.<table>` is sent;
- a failure is reported as one of the safe classes in `contracts.FAILURE_CODES`, never with driver text.

Drivers are pure Python or ship their native parts in the wheel (no system libraries): PyMySQL, pymssql (FreeTDS
inside) and python-oracledb in thin mode (no Oracle client).

MySQL is reached on the address that was checked (the socket is opened here and handed to the driver). SQL Server
and Oracle drivers open their own sockets by host name: the name is checked first, and TLS proves the server is the
one named, so a later answer for that name can only reach the certificate's holder.
"""
from __future__ import annotations

import os
import socket
import ssl
import tempfile
import time
from pathlib import Path
from threading import Event, Thread
from typing import Any, Callable

from .contracts import ConnectorCapabilities, ExtractionCancelled, ExtractionError, ExtractionRequest
from .postgres import PostgresSource, encode_value, resolve_address

#: Each engine's usual port, when a connection gives none.
DEFAULT_PORTS = {"postgres": 5432, "mysql": 3306, "sqlserver": 1433, "oracle": 1521}
ENGINE_NAMES = {"postgres": "PostgreSQL", "mysql": "MySQL / MariaDB", "sqlserver": "SQL Server", "oracle": "Oracle"}


def _phrase_code(said: str, phrases: tuple[tuple[str, str], ...], default: str) -> str:
    said = said.lower()
    return next((code for phrase, code in phrases if phrase in said), default)


_TLS_PHRASES = (("certificate", "tls_failed"), ("ssl", "tls_failed"), ("tls", "tls_failed"), ("handshake", "tls_failed"))


class _DatabaseConnector:
    """The extraction loop every engine shares; an engine supplies connect, quoting, cancel and failure classes."""

    engine = ""
    capabilities = ConnectorCapabilities("database", "1")

    def __init__(self, source: PostgresSource, resolve_secret: Callable[[str], str]):
        self.source = source
        self._resolve_secret = resolve_secret
        self.source_schema: list[dict] = []

    # -- what an engine supplies ----------------------------------------------------------------------------------
    def connect(self, address: str, password: str) -> Any:
        raise NotImplementedError

    def quote(self, name: str) -> str:
        raise NotImplementedError

    def begin(self, connection: Any) -> None:
        """Start the read-only transaction and set the statement timeout."""

    def cursor(self, connection: Any) -> Any:
        return connection.cursor()

    def cancel(self, connection: Any) -> None:
        connection.cancel()

    def failure_code(self, error: BaseException) -> str:
        return "extraction_failed"

    def close(self, connection: Any) -> None:
        connection.close()

    # -- shared ---------------------------------------------------------------------------------------------------
    #: How the engine's driver marks a parameter in a statement.
    placeholder = "%s"

    def select(self, columns: tuple[str, ...], since_column: str = "", table: str = "") -> str:
        return (f"SELECT {', '.join(self.quote(c) for c in columns)} FROM "
                f"{self.quote(self.source.schema)}.{self.quote(table or self.source.table)}"
                + (f" WHERE {self.quote(since_column)} >= {self.placeholder}" if since_column else ""))

    def since_value(self, since: object) -> object:
        """The mark as the driver should be given it: a time as a datetime, a number as a number, so the engine
        compares it by its type (Oracle reads a text '2026-10-08T…' by its own date format, not ISO 8601)."""
        if isinstance(since, str):
            from datetime import datetime
            from decimal import Decimal, InvalidOperation

            try:
                return Decimal(since)
            except InvalidOperation:
                pass
            try:
                return datetime.fromisoformat(since)
            except ValueError:
                return since
        return since

    def params(self, value: object) -> object:
        return (value,)

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
        finished, interrupted = Event(), Event()
        watcher = None
        name = ENGINE_NAMES.get(self.engine, self.engine)
        try:
            address = resolve_address(source)
            if not Path(source.root_certificate).is_file():
                raise ExtractionError("Local database trust certificate is unavailable", "trust_unavailable")
            connection = self.connect(address, self._resolve_secret(source.secret_ref))
            self.begin(connection)
            deadline = time.monotonic() + source.extraction_timeout_seconds

            def watch():
                while not finished.wait(0.05):
                    if cancelled.is_set() or time.monotonic() >= deadline:
                        interrupted.set()
                        try:
                            self.cancel(connection)
                        except Exception:
                            pass  # the statement timeout and the worker's deadline remain independent bounds
                        return

            watcher = Thread(target=watch, daemon=True)
            watcher.start()
            cursor = self.cursor(connection)
            try:
                if request.since_column and request.since is not None:
                    # Only what changed since the last read; >= so rows stamped in the same instant are not lost.
                    cursor.execute(self.select(request.columns, request.since_column, request.source_object),
                                   self.params(self.since_value(request.since)))
                else:
                    cursor.execute(self.select(request.columns, table=request.source_object))
                while True:
                    if cancelled.is_set():
                        raise ExtractionCancelled("Extraction cancelled")
                    if interrupted.is_set() or time.monotonic() >= deadline:
                        raise ExtractionError("Extraction deadline exceeded", "deadline_exceeded")
                    rows = cursor.fetchmany(request.limits.batch_rows)
                    if not self.source_schema and cursor.description:
                        self.source_schema = [{"name": d[0], "engine": self.engine, "type_code": str(d[1])}
                                              for d in cursor.description]
                    if not rows:
                        break
                    for row in rows:
                        if interrupted.is_set() or time.monotonic() >= deadline:
                            raise ExtractionError("Extraction deadline exceeded", "deadline_exceeded")
                        yield dict(zip(request.columns, (encode_value(value) for value in row), strict=True))
            finally:
                try:
                    cursor.close()
                except Exception:
                    pass
        except ExtractionError:
            raise
        except Exception as error:
            if cancelled.is_set():
                raise ExtractionCancelled("Extraction cancelled") from None
            code = "deadline_exceeded" if interrupted.is_set() else self.failure_code(error)
            raise ExtractionError(f"{name} extraction failed; check connection and source permissions", code) from None
        finally:
            finished.set()
            if watcher is not None:
                watcher.join(timeout=1)
            if connection is not None:
                try:
                    self.close(connection)  # closing ends the read-only transaction
                except Exception:
                    pass


# -- MySQL / MariaDB ------------------------------------------------------------------------------------------------
_MYSQL_CODES = {
    1045: "authentication_failed", 1698: "authentication_failed", 1251: "authentication_failed",
    1044: "not_permitted", 1142: "not_permitted", 1143: "not_permitted", 1227: "not_permitted",
    1049: "source_missing", 1146: "source_missing", 1054: "source_missing",
    3024: "deadline_exceeded", 1969: "deadline_exceeded", 1317: "deadline_exceeded",
    2003: "source_unreachable", 2005: "source_unreachable", 2006: "source_unreachable", 2013: "source_unreachable",
    2026: "tls_failed",
}


class MySqlConnector(_DatabaseConnector):
    engine = "mysql"
    capabilities = ConnectorCapabilities("mysql", "1")

    def connect(self, address: str, password: str):
        import pymysql
        import pymysql.cursors

        source = self.source
        context = ssl.create_default_context(cafile=source.root_certificate)
        context.check_hostname = True
        connection = pymysql.connections.Connection(
            host=source.host, port=source.port, user=source.username, password=password, database=source.database,
            ssl=context, connect_timeout=source.connect_timeout_seconds,
            read_timeout=max(1, source.statement_timeout_ms // 1000 + 5), program_name="oaas-extraction",
            cursorclass=pymysql.cursors.SSCursor, autocommit=False, defer_connect=True, charset="utf8mb4")
        # The socket goes to the address that was checked; TLS then verifies the certificate for the host name.
        sock = socket.create_connection((address, source.port), timeout=source.connect_timeout_seconds)
        try:
            connection.connect(sock)
        except BaseException:
            sock.close()
            raise
        return connection

    def quote(self, name: str) -> str:
        return "`" + name.replace("`", "``") + "`"

    def begin(self, connection) -> None:
        with connection.cursor() as cursor:
            try:  # MySQL: milliseconds per SELECT
                cursor.execute(f"SET SESSION MAX_EXECUTION_TIME = {int(self.source.statement_timeout_ms)}")
            except Exception:  # MariaDB: seconds per statement
                cursor.execute(f"SET SESSION max_statement_time = {self.source.statement_timeout_ms / 1000:.3f}")
            cursor.execute("SET SESSION TRANSACTION ISOLATION LEVEL REPEATABLE READ")
            cursor.execute("START TRANSACTION READ ONLY")

    def cancel(self, connection) -> None:
        sock = getattr(connection, "_sock", None)
        if sock is not None:
            sock.shutdown(socket.SHUT_RDWR)

    def failure_code(self, error: BaseException) -> str:
        code = error.args[0] if error.args and isinstance(error.args[0], int) else None
        if code == 2003 and _phrase_code(str(error), _TLS_PHRASES, "") == "tls_failed":
            return "tls_failed"  # PyMySQL reports a failed handshake as "can't connect"
        if code in _MYSQL_CODES:
            return _MYSQL_CODES[code]
        if isinstance(error, (ssl.SSLError, ssl.CertificateError)):
            return "tls_failed"
        if isinstance(error, (socket.timeout, ConnectionError, OSError)) and not isinstance(error, ssl.SSLError):
            return "source_unreachable"
        return _phrase_code(str(error), _TLS_PHRASES, "extraction_failed")


# -- SQL Server -----------------------------------------------------------------------------------------------------
_MSSQL_CODES = {
    18456: "authentication_failed", 18452: "authentication_failed", 18486: "authentication_failed",
    229: "not_permitted", 230: "not_permitted", 916: "not_permitted",
    4060: "source_missing", 208: "source_missing", 207: "source_missing", 911: "source_missing",
    20009: "source_unreachable", 20002: "source_unreachable", 20003: "deadline_exceeded",
    20017: "source_unreachable", 20004: "source_unreachable",
}
_MSSQL_PHRASES = (("login failed", "authentication_failed"), ("certificate", "tls_failed"), ("ssl", "tls_failed"),
                  ("tls", "tls_failed"), ("timeout", "deadline_exceeded"), ("unable to connect", "source_unreachable"),
                  ("adaptive server is unavailable", "source_unreachable"))


class SqlServerConnector(_DatabaseConnector):
    engine = "sqlserver"
    capabilities = ConnectorCapabilities("sqlserver", "1")

    def connect(self, address: str, password: str):
        import pymssql

        source = self.source
        # FreeTDS reads its TLS settings from a configuration file: one per extraction, naming the operator's CA,
        # requiring encryption and checking the certificate against the host name.
        folder = tempfile.mkdtemp(prefix="oaas-tds-")
        conf = Path(folder) / "freetds.conf"
        conf.write_text("[global]\n\tencryption = require\n\tcheck certificate hostname = yes\n"
                        f"\tca file = {source.root_certificate}\n")
        self._conf = conf
        os.environ["FREETDSCONF"] = str(conf)
        return pymssql.connect(
            server=source.host, port=str(source.port), user=source.username, password=password,
            database=source.database, login_timeout=source.connect_timeout_seconds,
            timeout=max(1, source.statement_timeout_ms // 1000), appname="oaas-extraction", encryption="require",
            read_only=True, tds_version="7.4", autocommit=False)

    def quote(self, name: str) -> str:
        return "[" + name.replace("]", "]]") + "]"

    def begin(self, connection) -> None:
        cursor = connection.cursor()
        # A snapshot of committed rows, without blocking writers longer than the statement timeout.
        cursor.execute("SET TRANSACTION ISOLATION LEVEL READ COMMITTED")
        cursor.execute(f"SET LOCK_TIMEOUT {int(self.source.statement_timeout_ms)}")
        cursor.close()

    def cancel(self, connection) -> None:
        inner = getattr(connection, "_conn", None)
        (inner or connection).cancel()

    def close(self, connection) -> None:
        try:
            connection.close()
        finally:
            conf = getattr(self, "_conf", None)
            if conf is not None:
                conf.unlink(missing_ok=True)
                conf.parent.rmdir()

    def failure_code(self, error: BaseException) -> str:
        numbers = [a for a in getattr(error, "args", ()) if isinstance(a, int)]
        for args in (getattr(error, "args", ()) or ()):
            if isinstance(args, tuple):
                numbers += [a for a in args if isinstance(a, int)]
        for number in numbers:
            if number in _MSSQL_CODES:
                return _MSSQL_CODES[number]
        said = " ".join(a.decode("utf-8", "replace") if isinstance(a, bytes) else str(a) for a in error.args)
        return _phrase_code(said, _MSSQL_PHRASES, "extraction_failed")


# -- Oracle ---------------------------------------------------------------------------------------------------------
_ORACLE_CODES = {
    "ORA-01017": "authentication_failed", "ORA-28000": "authentication_failed", "ORA-28001": "authentication_failed",
    "ORA-01031": "not_permitted", "ORA-01045": "not_permitted",
    "ORA-00942": "source_missing", "ORA-00904": "source_missing", "ORA-12514": "source_missing",
    "ORA-12505": "source_missing",
    "ORA-03156": "deadline_exceeded", "DPY-4024": "deadline_exceeded", "ORA-01013": "deadline_exceeded",
    "DPY-6005": "source_unreachable", "DPY-6000": "source_unreachable", "ORA-12541": "source_unreachable",
    "ORA-12170": "source_unreachable", "DPY-4011": "source_unreachable",
    "ORA-29024": "tls_failed", "ORA-28860": "tls_failed", "DPY-6004": "tls_failed",
}


class OracleConnector(_DatabaseConnector):
    engine = "oracle"
    capabilities = ConnectorCapabilities("oracle", "1")

    def connect(self, address: str, password: str):
        import oracledb

        source = self.source
        context = ssl.create_default_context(cafile=source.root_certificate)
        context.check_hostname = True
        params = oracledb.ConnectParams(
            host=source.host, port=source.port, service_name=source.database, protocol="tcps",
            ssl_context=context, ssl_server_dn_match=True, tcp_connect_timeout=float(source.connect_timeout_seconds))
        connection = oracledb.connect(user=source.username, password=password, params=params)  # thin mode
        connection.call_timeout = int(source.statement_timeout_ms)
        return connection

    placeholder = ":since"

    def params(self, value: object) -> object:
        return {"since": value}

    def quote(self, name: str) -> str:
        return '"' + name.replace('"', '""') + '"'

    def begin(self, connection) -> None:
        cursor = connection.cursor()
        cursor.execute("SET TRANSACTION READ ONLY")
        cursor.close()

    def cursor(self, connection):
        cursor = connection.cursor()
        cursor.arraysize = 1000
        return cursor

    def failure_code(self, error: BaseException) -> str:
        info = error.args[0] if error.args else None
        code = getattr(info, "full_code", None) or ""
        if code in _ORACLE_CODES:
            return _ORACLE_CODES[code]
        return _phrase_code(str(error), _TLS_PHRASES, "extraction_failed")


CONNECTORS = {"mysql": MySqlConnector, "sqlserver": SqlServerConnector, "oracle": OracleConnector}
