"""AES-GCM envelopes bound to an organization and connection; local keyring only."""
import base64
import json
import os
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class SecretUnavailable(Exception):
    pass


def _key(key_id):
    try:
        keys = json.loads(os.environ["OAAS_INTEGRATION_KEYS"])
        key = base64.b64decode(keys[key_id], validate=True)
        if len(key) != 32:
            raise ValueError()
        return key
    except Exception:
        raise SecretUnavailable("Integration keyring is unavailable") from None


def _aad(organization_id, connection_id):
    return f"oaas:connection:v1:{organization_id}:{connection_id}".encode()


def encrypt(password, organization_id, connection_id):
    key_id = os.environ.get("OAAS_INTEGRATION_ACTIVE_KEY", "")
    key = _key(key_id)
    nonce = os.urandom(12)
    ciphertext = AESGCM(key).encrypt(nonce, password.encode(), _aad(organization_id, connection_id))
    return {"key_id": key_id, "nonce": base64.b64encode(nonce).decode(), "ciphertext": base64.b64encode(ciphertext).decode()}


def decrypt(envelope, organization_id, connection_id):
    try:
        return AESGCM(_key(envelope["key_id"])).decrypt(
            base64.b64decode(envelope["nonce"], validate=True),
            base64.b64decode(envelope["ciphertext"], validate=True),
            _aad(organization_id, connection_id),
        ).decode()
    except Exception:
        raise SecretUnavailable("Integration credential could not be opened") from None
