"""Read-only HTTPS snapshot adapter: a REST endpoint's JSON list, or a CSV / Excel file served over HTTPS.

The same operator policy as a database source: the host must resolve inside the approved networks, TLS is verified
(against the operator's CA when one is configured, else the system's trust store), redirects are not followed (they
could leave the approved networks), the body is capped, and the credential -- a bearer token or a password -- is
decrypted only in the extraction child. Rows are the named columns of each record, like a table's.
"""
from __future__ import annotations

import csv
import io
import ipaddress
import json
import socket
from dataclasses import dataclass, field
from pathlib import Path
from threading import Event
from typing import Callable
from urllib.parse import urlsplit
from uuid import UUID

from .contracts import ConnectorCapabilities, ExtractionCancelled, ExtractionError, ExtractionRequest

FORMATS = ("json", "csv", "xlsx")
AUTHS = ("none", "bearer", "basic")
#: The most a response may be: the extraction's own byte budget.
MAX_BODY = 20 * 1024 * 1024


@dataclass(frozen=True)
class HttpSource:
    organization_id: UUID
    connection_id: int
    url: str
    format: str
    columns: tuple[str, ...]
    allowed_networks: tuple[str, ...]
    root_certificate: str
    secret_ref: str = field(default="", repr=False)
    auth: str = "none"
    username: str = ""
    sheet: str = ""
    records_at: str = ""  # a JSON answer's list, by dotted path: "data.items"; "" for a list at the top
    timeout_seconds: int = 30

    def __post_init__(self):
        parts = urlsplit(self.url or "")
        if parts.scheme != "https" or not parts.hostname or parts.username or parts.password:
            raise ValueError("An https:// address without a user name in it is required")
        if self.format not in FORMATS or self.auth not in AUTHS:
            raise ValueError("Unknown format or authentication")
        if not self.columns or len(set(self.columns)) != len(self.columns) or any(not c for c in self.columns):
            raise ValueError("Explicit, unique columns are required")
        if not self.allowed_networks:
            raise ValueError("Approved networks are required")
        for network in self.allowed_networks:
            ipaddress.ip_network(network)
        if self.auth == "basic" and not self.username:
            raise ValueError("Basic authentication needs a user name")

    @property
    def table(self) -> str:
        """The source object a manifest names: the sheet, or the address's last part."""
        return self.sheet or (urlsplit(self.url).path.rstrip("/").rsplit("/", 1)[-1] or urlsplit(self.url).hostname)


def resolve(source: HttpSource) -> str:
    host = urlsplit(source.url).hostname or ""
    networks = [ipaddress.ip_network(n) for n in source.allowed_networks]
    try:
        addresses = sorted({item[4][0] for item in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)})
    except OSError:
        raise ExtractionError("The host name does not resolve from the import worker", "source_unreachable") from None
    if not addresses or any(not any(ipaddress.ip_address(a) in n for n in networks) for a in addresses):
        raise ExtractionError("The address is outside the allowed networks", "network_not_allowed")
    return addresses[0]


def _scalar(value):
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if hasattr(value, "isoformat"):  # a date or time from a workbook
        return value.isoformat()
    if type(value).__name__ == "Decimal":
        value = float(value)
    if isinstance(value, float):
        return value if value == value and value not in (float("inf"), float("-inf")) else None
    return json.dumps(value, ensure_ascii=False, sort_keys=True)  # nested: kept, as text


def _records(source: HttpSource, body: bytes) -> list[dict]:
    """The answer's records, each as {column: value}."""
    try:
        if source.format == "json":
            data = json.loads(body.decode("utf-8-sig"))
            for part in [p for p in source.records_at.split(".") if p]:
                data = data[int(part)] if isinstance(data, list) else data[part]
            if not isinstance(data, list) or any(not isinstance(r, dict) for r in data):
                raise ExtractionError("The answer is not a list of records at the given place", "format_invalid")
            return data
        if source.format == "csv":
            text = body.decode("utf-8-sig")
            dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t") if text.strip() else csv.excel
            return list(csv.DictReader(io.StringIO(text), dialect=dialect))
        from openpyxl import load_workbook

        book = load_workbook(io.BytesIO(body), read_only=True, data_only=True)
        sheet = book[source.sheet] if source.sheet else book.worksheets[0]
        rows = sheet.iter_rows(values_only=True)
        header = [str(c).strip() if c is not None else "" for c in next(rows, [])]
        return [dict(zip(header, r)) for r in rows if any(c is not None for c in r)]
    except ExtractionError:
        raise
    except Exception:
        raise ExtractionError("The answer could not be read as " + source.format, "format_invalid") from None


class HttpConnector:
    capabilities = ConnectorCapabilities("https", "1")

    def __init__(self, source: HttpSource, resolve_secret: Callable[[str], str], transport=None):
        self.source = source
        self._resolve_secret = resolve_secret
        self._transport = transport  # tests only
        self.source_schema: list[dict] = []

    def extract(self, request: ExtractionRequest, cancelled: Event):
        import httpx

        source = self.source
        if (request.organization_id, request.connection_id) != (source.organization_id, source.connection_id):
            raise ExtractionError("Connection scope mismatch")
        if not set(request.columns).issubset(source.columns):
            raise ExtractionError("Source object or columns are not permitted")
        if cancelled.is_set():
            raise ExtractionCancelled("Extraction cancelled")
        if self._transport is None:
            resolve(source)
        verify: object = True
        if source.root_certificate:
            if not Path(source.root_certificate).is_file():
                raise ExtractionError("Local trust certificate is unavailable", "trust_unavailable")
            verify = source.root_certificate
        headers = {"Accept": "application/json" if source.format == "json" else "*/*"}
        auth = None
        if source.auth == "bearer":
            headers["Authorization"] = "Bearer " + self._resolve_secret(source.secret_ref)
        elif source.auth == "basic":
            auth = (source.username, self._resolve_secret(source.secret_ref))
        try:
            with httpx.Client(verify=verify, timeout=source.timeout_seconds, follow_redirects=False,
                              transport=self._transport, trust_env=False) as client:
                with client.stream("GET", source.url, headers=headers, auth=auth) as answer:
                    if answer.status_code in (401, 407):
                        raise ExtractionError("The source refused the credential", "authentication_failed")
                    if answer.status_code == 403:
                        raise ExtractionError("The credential may not read this", "not_permitted")
                    if answer.status_code in (404, 410):
                        raise ExtractionError("Nothing at this address", "source_missing")
                    if 300 <= answer.status_code < 400:
                        raise ExtractionError("The address redirects elsewhere; give the final address",
                                              "source_missing")
                    if answer.status_code >= 400:
                        raise ExtractionError("The source answered with an error", "source_unreachable")
                    body = bytearray()
                    for chunk in answer.iter_bytes():
                        if cancelled.is_set():
                            raise ExtractionCancelled("Extraction cancelled")
                        body += chunk
                        if len(body) > MAX_BODY:
                            raise ExtractionError("The answer is larger than one extraction allows", "limit_exceeded")
        except ExtractionError:
            raise
        except httpx.ConnectError as exc:
            said = str(exc).lower()
            code = "tls_failed" if "certificate" in said or "ssl" in said or "tls" in said else "source_unreachable"
            raise ExtractionError("The source could not be reached", code) from None
        except httpx.TimeoutException:
            raise ExtractionError("The source did not answer in time", "deadline_exceeded") from None
        except Exception:
            raise ExtractionError("The source could not be read", "extraction_failed") from None
        records = _records(source, bytes(body))
        present = set().union(*(r.keys() for r in records)) if records else set(request.columns)
        missing = [c for c in request.columns if c not in present]
        if missing:
            raise ExtractionError("Columns not in the answer: " + ", ".join(missing), "source_missing")
        self.source_schema = [{"name": c, "type": "text"} for c in request.columns]
        for record in records:
            if cancelled.is_set():
                raise ExtractionCancelled("Extraction cancelled")
            yield {c: _scalar(record.get(c)) for c in request.columns}
