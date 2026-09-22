"""API keys and the per-caller rate limit (migration 0035).

A token is `sk_<prefix>_<secret>`. The prefix (12 hex characters) finds the
row; the secret (43 URL-safe characters, 256 bits) is checked against a
keyed SHA-256 of it. Keyed with the JWT secret, so a copy of the table
alone cannot be used to test guesses; SHA-256 rather than bcrypt because
the secret is random, not chosen, and a key is checked on every request.
"""

from __future__ import annotations

import hashlib
import hmac
import math
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import get_settings

TOKEN_PREFIX = "sk_"
# Writing `last_used_at` on every request would turn every read into a
# write; once a minute says as much about whether a key is in use.
LAST_USED_RESOLUTION_SECONDS = 60


def mint() -> tuple[str, str, str]:
    """A new key's (prefix, secret hash, token). The token is shown once."""
    prefix = secrets.token_hex(6)
    secret = secrets.token_urlsafe(32)
    return prefix, hash_secret(secret), f"{TOKEN_PREFIX}{prefix}_{secret}"


def hash_secret(secret: str) -> str:
    key = get_settings().jwt_secret.encode("utf-8")
    return hmac.new(key, secret.encode("utf-8"), hashlib.sha256).hexdigest()


def is_api_key(token: str) -> bool:
    return token.startswith(TOKEN_PREFIX)


@dataclass
class ResolvedKey:
    id: str
    user_id: str
    capabilities: set[str]


def resolve(db: Session, token: str) -> ResolvedKey | None:
    """The live key a token names, or None: unknown, wrong secret, revoked
    or expired all look the same to the caller -- a 401."""
    try:
        _, prefix, secret = token.split("_", 2)
    except ValueError:
        return None
    row = db.execute(
        text(
            "SELECT id, user_id, secret_hash, capabilities, expires_at, revoked_at, last_used_at"
            "  FROM iam.api_key WHERE prefix = :p"
        ),
        {"p": prefix},
    ).mappings().one_or_none()
    if row is None or not hmac.compare_digest(row["secret_hash"], hash_secret(secret)):
        return None
    now = datetime.now(timezone.utc)
    if row["revoked_at"] is not None or (row["expires_at"] is not None and row["expires_at"] <= now):
        return None
    last = row["last_used_at"]
    if last is None or (now - last).total_seconds() >= LAST_USED_RESOLUTION_SECONDS:
        db.execute(text("UPDATE iam.api_key SET last_used_at = now() WHERE id = :k"), {"k": row["id"]})
        db.commit()
    return ResolvedKey(str(row["id"]), str(row["user_id"]), set(row["capabilities"]))


class RateLimited(Exception):
    def __init__(self, retry_after: int):
        super().__init__(f"too many requests; try again in {retry_after} s")
        self.retry_after = retry_after


def take_token(db: Session, caller: str, organization_id) -> None:
    """Spend one request from `caller`'s bucket, or raise `RateLimited`.

    A token bucket of one minute's allowance, refilled continuously at the
    organization's `requests_per_minute`, under a row lock so two requests
    at once cannot both spend the last token. A request refused does not
    spend one: waiting `Retry-After` is enough, however often it retried.
    """
    limit = db.execute(
        text("SELECT requests_per_minute FROM iam.quota WHERE organization_id = :o"),
        {"o": organization_id},
    ).scalar_one_or_none()
    if limit is None:
        return
    rate = limit / 60.0
    db.execute(
        text(
            "INSERT INTO iam.rate_bucket (caller, tokens, refilled_at) VALUES (:c, :cap, now())"
            " ON CONFLICT (caller) DO NOTHING"
        ),
        {"c": caller, "cap": float(limit)},
    )
    # Locked, so two requests at once cannot both spend the last token.
    available = float(db.execute(
        text(
            "SELECT least(:cap, tokens + extract(epoch FROM now() - refilled_at) * :rate)"
            "  FROM iam.rate_bucket WHERE caller = :c FOR UPDATE"
        ),
        {"c": caller, "cap": float(limit), "rate": rate},
    ).scalar_one())
    spend = available >= 1
    db.execute(
        text("UPDATE iam.rate_bucket SET tokens = :t, refilled_at = now() WHERE caller = :c"),
        {"c": caller, "t": available - 1 if spend else available},
    )
    db.commit()
    if not spend:
        raise RateLimited(max(1, math.ceil((1 - available) / rate)))
