from datetime import datetime, timedelta, timezone

import bcrypt
from jose import jwt

from app.core.config import get_settings

# bcrypt directly, not through passlib. passlib is unmaintained and imports
# the standard library's `crypt` module, which Python 3.13 removes: the first
# 3.13 image would have failed to hash or check any password, so nobody could
# sign in. Every stored hash is already plain bcrypt (`$2b$12$...`, which is
# what passlib wrote), so this reads them unchanged.
_ROUNDS = 12

# bcrypt only ever looks at the first 72 bytes of a password. passlib and
# bcrypt 4.0 cut the rest off silently; bcrypt 5 raises instead. Cutting it
# here keeps every existing hash verifying, and keeps a long passphrase
# working whichever version of the library is installed.
_BCRYPT_MAX_BYTES = 72


def _secret(password: str) -> bytes:
    return password.encode("utf-8")[:_BCRYPT_MAX_BYTES]


def hash_password(password: str) -> str:
    return bcrypt.hashpw(_secret(password), bcrypt.gensalt(rounds=_ROUNDS)).decode("ascii")


def verify_password(password: str, hashed: str) -> bool:
    # A malformed or non-bcrypt stored value makes bcrypt raise rather than
    # return False, which would surface as a 500 from /api/auth/login.
    # Treat any unverifiable hash as a failed login instead.
    try:
        return bcrypt.checkpw(_secret(password), hashed.encode("ascii"))
    except (ValueError, TypeError, UnicodeEncodeError):
        return False


def create_access_token(subject: str, expires_minutes: int | None = None) -> str:
    settings = get_settings()
    minutes = expires_minutes if expires_minutes is not None else settings.jwt_expire_minutes
    expire = datetime.now(timezone.utc) + timedelta(minutes=minutes)
    payload = {"sub": subject, "exp": expire}
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict:
    settings = get_settings()
    return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
