import json
import tempfile
import unittest
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from threading import Event
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import UUID

from app.integrations.contracts import ExtractionError, ExtractionLimits, ExtractionRequest, extract_batches
from app.integrations.postgres import PostgresConnector, PostgresSource, encode_value, resolve_address


class PostgresTests(unittest.TestCase):
    def setUp(self):
        self.source = PostgresSource(UUID(int=1), 2, "db.internal", "operations", "reader", "secret/ref",
                                     "planning", "staff", ("id", "cost"), ("10.0.0.0/8",), "local-ca.pem")
        self.request = ExtractionRequest(UUID(int=1), 2, "staff", ("id", "cost"), ExtractionLimits(batch_rows=2))

    def test_network_check_rejects_mixed_allowed_and_disallowed_dns(self):
        with patch("socket.getaddrinfo", return_value=[(None, None, None, None, ("10.2.3.4", 5432)),
                                                       (None, None, None, None, ("8.8.8.8", 5432))]):
            with self.assertRaises(ExtractionError):
                resolve_address(self.source)

    def test_scope_and_source_refusals_happen_before_credentials(self):
        secret = MagicMock()
        adapter = PostgresConnector(self.source, secret)
        for request in [replace(self.request, organization_id=UUID(int=9)),
                        replace(self.request, connection_id=8), replace(self.request, source_object="other"),
                        replace(self.request, columns=("password",))]:
            with self.subTest(request=request), self.assertRaises(ExtractionError):
                list(extract_batches(adapter, request, Event()))
        secret.assert_not_called()

    def test_readonly_bounded_extraction_preserves_precision_and_closes(self):
        connection = MagicMock()
        cursor = connection.cursor.return_value.__enter__.return_value
        cursor.fetchmany.side_effect = [[(2**60, Decimal("123.000100"))], []]
        cursor.description = [SimpleNamespace(name="id", type_code=20), SimpleNamespace(name="cost", type_code=1700)]
        secret = MagicMock(return_value="private-password")
        with tempfile.TemporaryDirectory() as tmp:
            cert = Path(tmp) / "ca.pem"
            cert.write_text("test fixture")
            hostile_table = 'staff"; DROP TABLE data;--'
            source = replace(self.source, root_certificate=str(cert), table=hostile_table)
            adapter = PostgresConnector(source, secret)
            with patch("app.integrations.postgres.resolve_address", return_value="10.2.3.4"), patch("psycopg2.connect", return_value=connection) as connect:
                rows = list(extract_batches(adapter, replace(self.request, source_object=hostile_table), Event()))
        self.assertEqual(json.loads(rows[0][0]), {"id": str(2**60), "cost": "123.000100"})
        self.assertEqual(connect.call_args.kwargs["sslmode"], "verify-full")
        self.assertEqual(connect.call_args.kwargs["hostaddr"], "10.2.3.4")
        connection.set_session.assert_called_once_with(readonly=True, isolation_level="REPEATABLE READ", autocommit=False)
        self.assertEqual(cursor.itersize, 2)
        connection.close.assert_called_once()
        self.assertEqual(adapter.source_schema[1]["postgres_oid"], 1700)
        self.assertNotIn("secret/ref", repr(source))
        from psycopg2 import sql
        self.assertIn(sql.Identifier(hostile_table), list(cursor.execute.call_args.args[0]))

    def test_nonfinite_decimal_is_refused(self):
        with self.assertRaises(ExtractionError):
            encode_value(Decimal("NaN"))


if __name__ == "__main__":
    unittest.main()
