"""MySQL / MariaDB, SQL Server and Oracle sources (app/integrations/databases.py; plan of 8 October 2026, 4A).

The MySQL path runs against a real server when OAAS_TEST_MYSQL is set ("host:port:ca-file:user:password:schema"), as
in the test container (MariaDB with TLS). SQL Server and Oracle are checked here for what does not need a server:
quoting, the statement sent, defaults and failure classes; the sample compose has servers for them."""
from __future__ import annotations

import os
from threading import Event
from uuid import uuid4

import pytest

from app.integrations.contracts import ExtractionError, ExtractionLimits, ExtractionRequest, extract_batches
from app.integrations.databases import (DEFAULT_PORTS, MySqlConnector, OracleConnector, SqlServerConnector)
from app.integrations.policy import connector_for, source_for

ORG = uuid4()


def _source(engine: str, **over):
    config = {"engine": engine, "host": "db.example", "database": "planning", "username": "reader",
              "schema": "planning", "table": "products", "columns": ["id", "profit"], **over}
    return source_for({"config": config, "organization_id": ORG, "id": 7})


def test_each_engine_gets_its_connector_and_usual_port(monkeypatch):
    monkeypatch.setenv("OAAS_INTEGRATION_NETWORKS", "10.0.0.0/8")
    monkeypatch.setenv("OAAS_INTEGRATION_CA", "/ca.pem")
    for engine, kind in (("mysql", MySqlConnector), ("sqlserver", SqlServerConnector), ("oracle", OracleConnector)):
        source = _source(engine)
        assert source.port == DEFAULT_PORTS[engine] and source.engine == engine
        assert isinstance(connector_for(source, lambda _: ""), kind)
    assert _source("postgres").port == 5432
    with pytest.raises(ValueError):
        _source("db2")


@pytest.mark.parametrize("connector, sql", [
    (MySqlConnector, "SELECT `id`, `odd``name` FROM `planning`.`products`"),
    (SqlServerConnector, "SELECT [id], [odd`name] FROM [planning].[products]"),
    (OracleConnector, 'SELECT "id", "odd`name" FROM "planning"."products"'),
])
def test_identifiers_are_quoted_never_spliced(monkeypatch, connector, sql):
    monkeypatch.setenv("OAAS_INTEGRATION_NETWORKS", "10.0.0.0/8")
    monkeypatch.setenv("OAAS_INTEGRATION_CA", "/ca.pem")
    adapter = connector(_source(connector.engine), lambda _: "")
    assert adapter.select(("id", "odd`name")) == sql
    assert SqlServerConnector.quote(adapter, "a]b") == "[a]]b]" and OracleConnector.quote(adapter, 'a"b') == '"a""b"'


class _Err(Exception):
    pass


class _OracleInfo:
    def __init__(self, code):
        self.full_code = code


@pytest.mark.parametrize("connector, error, code", [
    (MySqlConnector, _Err(1045, "Access denied"), "authentication_failed"),
    (MySqlConnector, _Err(1142, "SELECT command denied"), "not_permitted"),
    (MySqlConnector, _Err(1146, "Table doesn't exist"), "source_missing"),
    (MySqlConnector, _Err(2003, "Can't connect"), "source_unreachable"),
    (MySqlConnector, _Err(3024, "maximum statement execution time exceeded"), "deadline_exceeded"),
    (SqlServerConnector, _Err(18456, b"Login failed for user"), "authentication_failed"),
    (SqlServerConnector, _Err(208, b"Invalid object name"), "source_missing"),
    (SqlServerConnector, _Err(229, b"The SELECT permission was denied"), "not_permitted"),
    (SqlServerConnector, _Err((20009, b"Unable to connect: Adaptive Server is unavailable"),), "source_unreachable"),
    (SqlServerConnector, _Err(b"SSL routines: certificate verify failed"), "tls_failed"),
    (OracleConnector, _Err(_OracleInfo("ORA-01017")), "authentication_failed"),
    (OracleConnector, _Err(_OracleInfo("ORA-00942")), "source_missing"),
    (OracleConnector, _Err(_OracleInfo("DPY-6005")), "source_unreachable"),
    (OracleConnector, _Err(_OracleInfo("DPY-4024")), "deadline_exceeded"),
    (OracleConnector, _Err(_OracleInfo("ORA-99999")), "extraction_failed"),
])
def test_driver_failures_become_safe_classes(monkeypatch, connector, error, code):
    monkeypatch.setenv("OAAS_INTEGRATION_NETWORKS", "10.0.0.0/8")
    monkeypatch.setenv("OAAS_INTEGRATION_CA", "/ca.pem")
    assert connector(_source(connector.engine), lambda _: "").failure_code(error) == code


def test_an_address_outside_the_networks_is_refused_before_any_credential(monkeypatch, tmp_path):
    monkeypatch.setenv("OAAS_INTEGRATION_NETWORKS", "10.0.0.0/8")
    monkeypatch.setenv("OAAS_INTEGRATION_CA", str(tmp_path / "ca.pem"))
    asked = []
    for connector in (MySqlConnector, SqlServerConnector, OracleConnector):
        adapter = connector(_source(connector.engine, host="localhost"), lambda ref: asked.append(ref) or "x")
        request = ExtractionRequest(ORG, 7, "products", ("id",), ExtractionLimits())
        with pytest.raises(ExtractionError) as refused:
            list(adapter.extract(request, Event()))
        assert refused.value.code == "network_not_allowed"
    assert asked == []


# -- a real MySQL / MariaDB ----------------------------------------------------------------------------------------
REAL = os.environ.get("OAAS_TEST_MYSQL")


@pytest.mark.skipif(not REAL, reason="no MySQL / MariaDB test server (OAAS_TEST_MYSQL)")
class TestRealMySql:
    def _adapter(self, monkeypatch, **over):
        host, port, ca, user, password, schema = REAL.split(":")
        monkeypatch.setenv("OAAS_INTEGRATION_NETWORKS", "127.0.0.0/8")
        monkeypatch.setenv("OAAS_INTEGRATION_CA", ca)
        config = {"engine": "mysql", "host": host, "port": int(port), "database": schema, "username": user,
                  "schema": schema, "table": "products", "columns": ["id", "profit", "hours", "made"], **over}
        source = source_for({"config": config, "organization_id": ORG, "id": 7})
        return connector_for(source, lambda _: over.get("_password", password)), source

    def test_a_table_is_read_over_verified_tls_in_a_read_only_transaction(self, monkeypatch):
        adapter, source = self._adapter(monkeypatch)
        request = ExtractionRequest(ORG, 7, "products", ("id", "profit", "hours", "made"), ExtractionLimits())
        rows = [line for batch in extract_batches(adapter, request, Event()) for line in batch]
        text = b"".join(rows).decode()
        assert '"id":"chair"' in text and '"profit":"30.50"' in text and '"made":"2026-10-01"' in text
        assert '"made":null' in text and len(rows) == 2

    def test_a_wrong_password_is_named(self, monkeypatch):
        adapter, _ = self._adapter(monkeypatch)
        adapter._resolve_secret = lambda _: "wrong"
        request = ExtractionRequest(ORG, 7, "products", ("id",), ExtractionLimits())
        with pytest.raises(ExtractionError) as failed:
            list(adapter.extract(request, Event()))
        assert failed.value.code == "authentication_failed"

    def test_a_missing_table_is_named(self, monkeypatch):
        adapter, _ = self._adapter(monkeypatch, table="nothing_here")
        request = ExtractionRequest(ORG, 7, "nothing_here", ("id",), ExtractionLimits())
        with pytest.raises(ExtractionError) as failed:
            list(adapter.extract(request, Event()))
        assert failed.value.code == "source_missing"

    def test_a_certificate_for_another_name_is_refused(self, monkeypatch):
        adapter, _ = self._adapter(monkeypatch, host="127.0.0.1")  # the certificate names localhost
        request = ExtractionRequest(ORG, 7, "products", ("id",), ExtractionLimits())
        with pytest.raises(ExtractionError) as failed:
            list(adapter.extract(request, Event()))
        assert failed.value.code == "tls_failed"


def test_an_incremental_read_asks_only_for_what_changed_in_each_engines_terms():
    """Migration 0118: SELECT ... WHERE <changed> >= <mark>, the mark bound as a parameter (never spliced), as a
    datetime or a number so each engine compares it by type."""
    from datetime import datetime
    from decimal import Decimal

    from app.integrations.contracts import later
    from app.integrations.databases import MySqlConnector, OracleConnector

    for cls, mark in ((MySqlConnector, "%s"), (OracleConnector, ":since")):
        connector = cls.__new__(cls)
        connector.source = type("S", (), {"schema": "plan", "table": "staff"})()
        sql = connector.select(("id", "updated_at"), "updated_at")
        assert sql.endswith(f"WHERE {connector.quote('updated_at')} >= {mark}") and "'" not in sql
        assert connector.since_value("2026-10-08T10:00:00") == datetime(2026, 10, 8, 10)
        assert connector.since_value("41") == Decimal("41")
    assert OracleConnector.params(OracleConnector.__new__(OracleConnector), 5) == {"since": 5}
    assert later("9", "10") == "10" and later("2026-10-08T09:00:00", "2026-10-08T10:00:00") == "2026-10-08T10:00:00"
    assert later(None, 3) == 3


def test_a_snapshot_keeps_the_highest_changed_value_and_the_mark_it_read_from(tmp_path):
    """The next incremental read starts from the manifest's high_water; an incremental read says its `since`."""
    import json

    from app.integrations.contracts import ConnectorCapabilities
    from app.integrations.snapshots import stage_snapshot

    class Rows:
        capabilities = ConnectorCapabilities("fake", "1")

        def extract(self, request, cancelled):
            yield from ({"id": 1, "updated_at": "2026-10-08T09:00:00"}, {"id": 2, "updated_at": "2026-10-08T11:30:00"},
                        {"id": 3, "updated_at": "2026-10-08T10:00:00"})

    org = uuid4()
    request = ExtractionRequest(org, 9, "staff", ("id", "updated_at"), ExtractionLimits(),
                                since_column="updated_at", since="2026-10-08T09:00:00")
    folder = stage_snapshot(tmp_path, Rows(), request, Event())
    manifest = json.loads((folder / "manifest.json").read_text())
    assert manifest["high_water"] == "2026-10-08T11:30:00" and manifest["since"] == "2026-10-08T09:00:00"
    with pytest.raises(ValueError):
        ExtractionRequest(org, 9, "staff", ("id",), ExtractionLimits(), since_column="updated_at")
