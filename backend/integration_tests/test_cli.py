import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch
from uuid import UUID

from app.integrations.__main__ import main


class CommandTests(unittest.TestCase):
    def test_configuration_is_validated_and_secret_resolved_only_by_worker(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "source.json"
            config.write_text(json.dumps({
                "organization_id": str(UUID(int=1)), "connection_id": 2,
                "host": "db.internal", "database": "ops", "username": "reader",
                "secret_ref": "OAAS_TEST_SECRET", "schema": "planning", "table": "staff",
                "columns": ["id"], "allowed_networks": ["10.0.0.0/8"], "root_certificate": "ca.pem",
            }))
            output = io.StringIO()
            with patch("app.integrations.__main__.stage_snapshot", return_value=Path(tmp) / "result") as stage, redirect_stdout(output):
                self.assertEqual(main(["--config", str(config), "--output", tmp]), 0)
            self.assertEqual(stage.call_args.args[2].organization_id, UUID(int=1))
            self.assertIn("extracted_requires_mapping_validation", output.getvalue())

    def test_invalid_config_does_not_echo_contents_or_start_extraction(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "source.json"
            config.write_text('{"password":"private"}')
            output = io.StringIO()
            with patch("app.integrations.__main__.stage_snapshot") as stage, redirect_stderr(output):
                self.assertEqual(main(["--config", str(config), "--output", tmp]), 1)
            stage.assert_not_called()
            self.assertNotIn("private", output.getvalue())
