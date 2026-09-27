"""Operator-owned network, TLS and resource policy; never accepted from API bodies."""
import os
from .postgres import PostgresSource


def source_for(row):
    config = dict(row["config"])
    return PostgresSource(
        organization_id=row["organization_id"], connection_id=row["id"],
        secret_ref="encrypted-connection", **config,
        allowed_networks=tuple(filter(None, os.environ.get("OAAS_INTEGRATION_NETWORKS", "").split(","))),
        root_certificate=os.environ.get("OAAS_INTEGRATION_CA", ""),
    )
