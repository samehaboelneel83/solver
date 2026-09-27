import base64
import json
import os
import unittest
from unittest.mock import patch
from uuid import UUID
from app.integrations.secrets import encrypt, decrypt, SecretUnavailable


class SecretTests(unittest.TestCase):
    def setUp(self):
        self.environment = patch.dict(os.environ, {
            "OAAS_INTEGRATION_KEYS": json.dumps({"a": base64.b64encode(b"a" * 32).decode(), "b": base64.b64encode(b"b" * 32).decode()}),
            "OAAS_INTEGRATION_ACTIVE_KEY": "a",
        })
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def test_binding_tamper_and_rotation(self):
        org = UUID(int=1)
        envelope = encrypt("sensitive", org, 2)
        self.assertNotIn("sensitive", json.dumps(envelope))
        self.assertEqual(decrypt(envelope, org, 2), "sensitive")
        for other_org, other_id in [(UUID(int=2), 2), (org, 3)]:
            with self.assertRaises(SecretUnavailable):
                decrypt(envelope, other_org, other_id)
        changed = dict(envelope, ciphertext=base64.b64encode(b"invalid").decode())
        with self.assertRaises(SecretUnavailable):
            decrypt(changed, org, 2)
        os.environ["OAAS_INTEGRATION_ACTIVE_KEY"] = "b"
        self.assertEqual(encrypt("next", org, 2)["key_id"], "b")
        self.assertEqual(decrypt(envelope, org, 2), "sensitive")

    def test_missing_key_fails_closed(self):
        os.environ["OAAS_INTEGRATION_KEYS"] = "{}"
        with self.assertRaises(SecretUnavailable):
            encrypt("sensitive", UUID(int=1), 1)
