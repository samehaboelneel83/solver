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


def test_verify_password_returns_false_for_malformed_hash():
    """bcrypt raises on a malformed or non-bcrypt stored value; that
    must not escape as a 500 from /api/auth/login."""
    assert verify_password("anything", "not-a-real-bcrypt-hash") is False


def test_access_token_roundtrip():
    token = create_access_token(subject="admin")
    payload = decode_access_token(token)
    assert payload["sub"] == "admin"


def test_decode_rejects_garbage_token():
    with pytest.raises(JWTError):
        decode_access_token("not-a-real-token")


def test_a_hash_written_by_passlib_still_verifies():
    """Every account created before passlib was dropped holds a hash passlib
    wrote. This one is real passlib 1.7.4 output for this password, generated
    in the image that still had passlib, so the replacement is checked against
    the format actually sitting in the database."""
    written_by_passlib = "$2b$12$j9GgKtm/NSRLPTHrJBDHz./Z/IJp5QV53MyefD0wSNMcbOvRZ12J2"
    assert verify_password("correct horse battery staple", written_by_passlib)
    assert not verify_password("wrong password", written_by_passlib)
    # And a fresh hash is the same scheme and cost, so the two interchange.
    assert hash_password("correct horse battery staple")[:7] == "$2b$12$"


def test_a_password_past_72_bytes_still_signs_in():
    """bcrypt reads only 72 bytes. The library used to cut the rest silently
    and newer versions refuse instead; a long passphrase must keep working
    either way, as it did under passlib."""
    long_password = "x" * 100
    hashed = hash_password(long_password)
    assert verify_password(long_password, hashed)
    # ... and, as bcrypt always has, only the first 72 bytes count.
    assert verify_password("x" * 72 + "different tail", hashed)


def test_a_non_ascii_stored_value_is_a_failed_login_not_an_error():
    assert verify_password("anything", "$2b$12$éé") is False
