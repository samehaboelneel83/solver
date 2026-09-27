"""Pure contract tests: no database, credentials, network, or migrations."""
import unittest
from decimal import Decimal
from threading import Event
from uuid import UUID

from app.integrations.contracts import (
    ConnectorCapabilities, ExtractionCancelled, ExtractionError,
    ExtractionLimitExceeded, ExtractionLimits, ExtractionRequest, extract_batches,
)


class MemoryConnector:
    capabilities = ConnectorCapabilities("test", "1")

    def __init__(self, rows):
        self.rows = rows
        self.closed = False

    def extract(self, request, cancelled):
        try:
            yield from self.rows
        finally:
            self.closed = True


class ContractTests(unittest.TestCase):
    def request(self, **limits):
        return ExtractionRequest(UUID(int=1), 2, "staff", ("id",), ExtractionLimits(batch_rows=1, **limits))

    def test_streams_immutable_canonical_batches_and_closes(self):
        source = MemoryConnector([{"id": 1}, {"id": 2}])
        self.assertEqual(list(extract_batches(source, self.request(), Event())), [(b'{"id":1}\n',), (b'{"id":2}\n',)])
        self.assertTrue(source.closed)

    def test_row_limit_failure_closes_source(self):
        source = MemoryConnector([{"id": 1}, {"id": 2}])
        with self.assertRaises(ExtractionLimitExceeded):
            list(extract_batches(source, self.request(max_rows=1), Event()))
        self.assertTrue(source.closed)

    def test_byte_limit_counts_utf8_and_newlines(self):
        with self.assertRaises(ExtractionLimitExceeded):
            list(extract_batches(MemoryConnector([{"id": "é"}]), self.request(max_bytes=11), Event()))

    def test_cancellation_between_batches_closes_source(self):
        source = MemoryConnector([{"id": 1}, {"id": 2}])
        cancelled = Event()
        stream = extract_batches(source, self.request(), cancelled)
        next(stream)
        cancelled.set()
        with self.assertRaises(ExtractionCancelled):
            next(stream)
        self.assertTrue(source.closed)

    def test_rejects_schema_drift(self):
        with self.assertRaises(ExtractionError):
            list(extract_batches(MemoryConnector([{"renamed": 1}]), self.request(), Event()))

    def test_rejects_lossy_or_nonfinite_values(self):
        for value in [2**53, float("nan"), float("inf"), Decimal("1.001")]:
            with self.subTest(value=value), self.assertRaises(ExtractionError):
                list(extract_batches(MemoryConnector([{"id": value}]), self.request(), Event()))

    def test_consumer_abort_closes_source(self):
        source = MemoryConnector([{"id": 1}, {"id": 2}])
        stream = extract_batches(source, self.request(), Event())
        next(stream)
        stream.close()
        self.assertTrue(source.closed)

    def test_invalid_limits(self):
        for value in [0, -1, True, 1.5]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                ExtractionLimits(max_rows=value)

    def test_driver_failure_does_not_expose_credentials(self):
        class BrokenConnector(MemoryConnector):
            def extract(self, request, cancelled):
                raise RuntimeError("password=private")
        with self.assertRaisesRegex(ExtractionError, "^Source extraction could not start$"):
            list(extract_batches(BrokenConnector([]), self.request(), Event()))

    def test_cancelled_job_never_opens_source(self):
        class UnopenedConnector(MemoryConnector):
            def extract(self, request, cancelled):
                self.fail = True
                raise AssertionError("must not open")
        cancelled = Event()
        cancelled.set()
        with self.assertRaises(ExtractionCancelled):
            list(extract_batches(UnopenedConnector([]), self.request(), cancelled))


if __name__ == "__main__":
    unittest.main()
