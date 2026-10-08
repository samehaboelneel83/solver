"""Read-only HTTPS snapshot adapter: a REST endpoint's JSON list, or a CSV / Excel file served over HTTPS.

The same operator policy as a database source: the host must resolve inside the approved networks, TLS is verified
(against the operator's CA when one is configured, else the system's trust store), redirects are not followed (they
could leave the approved networks), the body is capped, and the credential -- a bearer token or a password -- is
decrypted only in the extraction child. Rows are the named columns of each record, like a table's.

A JSON answer may come in pages (`paging`): the next page's address in the answer (`next_link`, at `next_at`, e.g.
"next", "links.next" or "@odata.nextLink"), in a `Link: <...>; rel="next"` header (`link_header`), or by a page
number in the address (`page_number`, `page_param`, from `first_page`, until a page is empty). Every page is read
under the same policy: the same host (so the same approved network), https, no redirects, and one byte budget for all
of them; at most MAX_PAGES pages, and an address seen twice ends the reading.
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
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit
from uuid import UUID

from .contracts import ConnectorCapabilities, ExtractionCancelled, ExtractionError, ExtractionRequest

FORMATS = ("json", "csv", "xlsx")
AUTHS = ("none", "bearer", "basic")
#: The most a response may be -- all its pages together: the extraction's own byte budget.
MAX_BODY = 20 * 1024 * 1024
PAGINGS = ("none", "next_link", "link_header", "page_number")
#: The most pages one extraction reads.
MAX_PAGES = 1000


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
    paging: str = "none"
    next_at: str = ""  # next_link: where the next page's address is in the answer ("next", "links.next")
    page_param: str = ""  # page_number: the address's parameter for the page ("page")
    first_page: int = 1

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
        if self.paging not in PAGINGS:
            raise ValueError("Unknown paging")
        if self.paging != "none" and self.format != "json":
            raise ValueError("Pages are read for a JSON answer only")
        if self.paging == "next_link" and not self.next_at:
            raise ValueError("Paging by a next link needs where the link is in the answer (next_at)")
        if self.paging == "page_number" and not self.page_param:
            raise ValueError("Paging by page number needs the address's page parameter (page_param)")

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


def _at(data, path: str):
    """The value at a dotted path ("data.items", "links.next"); a whole key with dots in it ("@odata.nextLink")
    is found as it is. None when the path is not there."""
    if isinstance(data, dict) and path in data:
        return data[path]
    for part in [p for p in path.split(".") if p]:
        if isinstance(data, list):
            try:
                data = data[int(part)]
            except (ValueError, IndexError):
                return None
        elif isinstance(data, dict):
            if part not in data:
                return None
            data = data[part]
        else:
            return None
    return data


def _json_list(source: HttpSource, data) -> list[dict]:
    found = _at(data, source.records_at) if source.records_at else data
    if not isinstance(found, list) or any(not isinstance(r, dict) for r in found):
        raise ExtractionError("The answer is not a list of records at the given place", "format_invalid")
    return found


def _next_page(source: HttpSource, url: str, data, link: str, records: list, page: int) -> str | None:
    """The next page's address, checked to stay on the source's host over https; None when there is none."""
    if source.paging == "next_link":
        nxt = _at(data, source.next_at)
        if nxt in (None, "") or not isinstance(nxt, str):
            return None
    elif source.paging == "link_header":
        nxt = next((part.split(";")[0].strip().strip("<>") for part in (link or "").split(",")
                    if 'rel="next"' in part.replace("'", '"') or "rel=next" in part), None)
        if not nxt:
            return None
    elif source.paging == "page_number":
        if not records:
            return None
        parts = urlsplit(url)
        query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k != source.page_param]
        nxt = urlunsplit(parts._replace(query=urlencode([*query, (source.page_param, str(page + 1))])))
    else:
        return None
    nxt = urljoin(url, nxt)
    first, then = urlsplit(source.url), urlsplit(nxt)
    if then.scheme != "https" or then.hostname != first.hostname or then.port != first.port or then.username \
            or then.password:
        raise ExtractionError("The next page is on another address than the source's host", "network_not_allowed")
    return nxt


def _records(source: HttpSource, body: bytes) -> list[dict]:
    """The answer's records, each as {column: value}."""
    try:
        if source.format == "json":
            return _json_list(source, json.loads(body.decode("utf-8-sig")))
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
        records: list[dict] = []
        url: str | None = source.url
        if source.paging == "page_number":
            parts = urlsplit(url)
            query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k != source.page_param]
            url = urlunsplit(parts._replace(query=urlencode([*query, (source.page_param, str(source.first_page))])))
        page, seen, used = source.first_page, set(), 0
        while url is not None:
            if len(seen) >= MAX_PAGES:
                raise ExtractionError(f"The answer has more than {MAX_PAGES} pages", "limit_exceeded")
            seen.add(url)
            body, link = self._page(url, headers, auth, verify, cancelled, MAX_BODY - used)
            used += len(body)
            if source.paging == "none":
                records = _records(source, body)
                break
            try:
                data = json.loads(body.decode("utf-8-sig"))
            except Exception:
                raise ExtractionError("The answer could not be read as json", "format_invalid") from None
            got = _json_list(source, data)
            records.extend(got)
            url = _next_page(source, url, data, link, got, page)
            page += 1
            if url in seen:
                break  # an address seen before: the pages have come round
        present = set().union(*(r.keys() for r in records)) if records else set(request.columns)
        missing = [c for c in request.columns if c not in present]
        if missing:
            raise ExtractionError("Columns not in the answer: " + ", ".join(missing), "source_missing")
        self.source_schema = [{"name": c, "type": "text"} for c in request.columns]
        for record in records:
            if cancelled.is_set():
                raise ExtractionCancelled("Extraction cancelled")
            yield {c: _scalar(record.get(c)) for c in request.columns}

    def _page(self, url: str, headers: dict, auth, verify, cancelled: Event, budget: int) -> tuple[bytes, str]:
        """One page's body and its Link header, under the source's policy."""
        import httpx

        source = self.source
        try:
            with httpx.Client(verify=verify, timeout=source.timeout_seconds, follow_redirects=False,
                              transport=self._transport, trust_env=False) as client:
                with client.stream("GET", url, headers=headers, auth=auth) as answer:
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
                        if len(body) > budget:
                            raise ExtractionError("The answer is larger than one extraction allows", "limit_exceeded")
                    link = answer.headers.get("link", "")
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
        return bytes(body), link
