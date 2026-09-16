import pytest
from jose import JWTError

from app.core.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)


def test_hash_password_is_not_plaintext_and_verifies():
    hashed = hash_password("correct horse battery staple")
    assert hashed != "correct horse battery staple"
    assert verify_password("correct horse battery staple", hashed)


def test_verify_password_rejects_wrong_password():
    hashed = hash_password("correct horse battery staple")
    assert not verify_password("wrong password", hashed)


def test_access_token_roundtrip():
    token = create_access_token(subject="admin")
    payload = decode_access_token(token)
    assert payload["sub"] == "admin"


def test_decode_rejects_garbage_token():
    with pytest.raises(JWTError):
        decode_access_token("not-a-real-token")
