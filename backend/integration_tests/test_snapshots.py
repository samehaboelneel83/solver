import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from threading import Event
from uuid import UUID

from app.integrations.contracts import ConnectorCapabilities, ExtractionError, ExtractionLimits, ExtractionRequest
from app.integrations.snapshots import stage_snapshot


class Source:
    capabilities = ConnectorCapabilities("fixture", "1")

    def __init__(self, fail=False):
        self.fail = fail

    def extract(self, request, cancelled):
        yield {"id": 1}
        if self.fail:
            raise RuntimeError("driver secret")
        yield {"id": 2}


class SnapshotTests(unittest.TestCase):
    def test_manifest_matches_rows_and_failed_import_preserves_previous(self):
        request = ExtractionRequest(UUID(int=1), 2, "staff", ("id",), ExtractionLimits(batch_rows=1))
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = stage_snapshot(root, Source(), request, Event())
            data = (target / "rows.jsonl").read_bytes()
            manifest = json.loads((target / "manifest.json").read_text())
            self.assertEqual(manifest["rows"], 2)
            self.assertEqual(manifest["bytes"], len(data))
            self.assertEqual(manifest["sha256"], hashlib.sha256(data).hexdigest())
            self.assertEqual(manifest["status"], "extracted_requires_mapping_validation")
            with self.assertRaises(ExtractionError):
                stage_snapshot(root, Source(fail=True), request, Event())
            self.assertEqual(list(target.parent.iterdir()), [target])
            self.assertEqual((target / "rows.jsonl").read_bytes(), data)


if __name__ == "__main__":
    unittest.main()
