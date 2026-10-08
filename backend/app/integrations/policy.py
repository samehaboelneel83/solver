"""Operator-owned network, TLS and resource policy; never accepted from API bodies."""
import os
from .postgres import PostgresSource


def source_for(row):
    config = dict(row["config"])
    kind = config.pop("kind", "postgres")
    if kind == "http":
        from .http_source import HttpSource

        config["columns"] = tuple(config.get("columns") or ())
        return HttpSource(
            organization_id=row["organization_id"], connection_id=row["id"],
            secret_ref="encrypted-connection" if config.get("auth", "none") != "none" else "", **config,
            allowed_networks=tuple(filter(None, os.environ.get("OAAS_INTEGRATION_NETWORKS", "").split(","))),
            root_certificate=os.environ.get("OAAS_INTEGRATION_CA", ""),
        )
    from .databases import DEFAULT_PORTS

    config["engine"] = config.get("engine") or "postgres"
    if config.get("port") is None:
        config["port"] = DEFAULT_PORTS.get(config["engine"], 5432)
    return PostgresSource(
        organization_id=row["organization_id"], connection_id=row["id"],
        secret_ref="encrypted-connection", **config,
        allowed_networks=tuple(filter(None, os.environ.get("OAAS_INTEGRATION_NETWORKS", "").split(","))),
        root_certificate=os.environ.get("OAAS_INTEGRATION_CA", ""),
    )


def connector_for(source, resolve_secret):
    """The adapter that reads a source of this kind."""
    from .databases import CONNECTORS
    from .http_source import HttpConnector, HttpSource
    from .postgres import PostgresConnector

    if isinstance(source, HttpSource):
        return HttpConnector(source, resolve_secret)
    return CONNECTORS.get(source.engine, PostgresConnector)(source, resolve_secret)
