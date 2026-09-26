"""An organization's own solver licences (queue R42): stored encrypted, read back by nobody, given
to that organization's solves only -- inside the sandboxed child, never the worker's environment.

**What an adapter needs** is declared in its manifest (`app.solve.adapters`):

    [licence]
    required = true               # no licence set: the solver is not offered to this organization
    env = ["XPAUTH_PATH", "GRB_WLSACCESSID", "GRB_WLSSECRET", "GRB_LICENSEID"]   # values it may set
    file = "gurobi.lic"           # a licence given as a file: written in the solve's own folder...
    file_env = "GRB_LICENSE_FILE" # ...its path put here

**What an organization gives** (`PUT /solver-licences/{adapter}`) is `{"env": {NAME: value},
"file": "the licence file's text"}` -- only the names and the file its manifest declares.

**The key** is `SOLVER_SECRETS_KEY` from the environment (a Fernet key); where none is set it is
derived from `JWT_SECRET`, which is already the platform's own secret -- so replacing that secret
without first setting `SOLVER_SECRETS_KEY` to the derived key makes every stored licence
unreadable, and each organization must give its licence again. A payload that cannot be decrypted
is treated as no licence, and the run says so.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session


class LicenceRefused(ValueError):
    """A licence that does not match what its adapter declares. `code` names why."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _fernet():
    from cryptography.fernet import Fernet

    key = os.environ.get("SOLVER_SECRETS_KEY")
    if not key:
        from app.core.config import get_settings

        digest = hashlib.sha256(b"solver-licence:" + get_settings().jwt_secret.encode()).digest()
        key = base64.urlsafe_b64encode(digest).decode()
    return Fernet(key.encode() if isinstance(key, str) else key)


def spec(manifest) -> dict[str, Any]:
    """What an adapter's manifest says a licence for it is; empty when it needs none."""
    return dict(getattr(manifest, "licence", None) or {})


def required(backend) -> bool:
    return bool(spec(backend.manifest).get("required")) if backend.manifest is not None else False


def checked(backend, given: dict[str, Any]) -> dict[str, Any]:
    """A licence as it will be stored: only the names and the file its manifest declares."""
    wanted = spec(backend.manifest)
    if backend.manifest is None:
        raise LicenceRefused("licence_not_an_adapter", f"{backend.name} is built in and takes no licence")
    env = given.get("env") or {}
    allowed = set(wanted.get("env") or [])
    stray = sorted(set(env) - allowed)
    if stray:
        raise LicenceRefused("licence_unknown_name",
                             f"{backend.name} takes {', '.join(sorted(allowed)) or 'no environment values'}, "
                             f"not {', '.join(stray)}")
    if not all(isinstance(v, str) and v for v in env.values()):
        raise LicenceRefused("licence_value", "every value is text, and not empty")
    file_text = given.get("file")
    if file_text is not None and not (wanted.get("file") and wanted.get("file_env")):
        raise LicenceRefused("licence_no_file", f"{backend.name} takes no licence file")
    if file_text is not None and (not isinstance(file_text, str) or not file_text.strip()):
        raise LicenceRefused("licence_value", "the licence file is text, and not empty")
    if not env and file_text is None:
        raise LicenceRefused("licence_empty", "give the values or the file this solver's licence is")
    return {"env": env, **({"file": file_text} if file_text is not None else {})}


def seal(licence: dict[str, Any]) -> tuple[bytes, str]:
    """The encrypted payload and a short fingerprint of the plaintext."""
    plain = json.dumps(licence, sort_keys=True).encode()
    return _fernet().encrypt(plain), hashlib.sha256(plain).hexdigest()[:12]


def unseal(payload: bytes) -> dict[str, Any] | None:
    from cryptography.fernet import InvalidToken

    try:
        return json.loads(_fernet().decrypt(bytes(payload)))
    except (InvalidToken, ValueError):
        return None


def for_solve(db: Session, organization_id, backend) -> tuple[dict | None, str | None]:
    """What a solve of this organization with this backend is given: the sandbox's licence form
    (`app.solve.sandbox.licensed`), or None; and, when the backend cannot run for want of one, why."""
    if backend.manifest is None:
        return None, None
    row = db.execute(
        text("SELECT payload FROM iam.solver_licence WHERE organization_id = :o AND adapter = :a"),
        {"o": organization_id, "a": backend.name},
    ).first()
    stored = unseal(row[0]) if row is not None else None
    if stored is None:
        if required(backend):
            why = "has not set" if row is None else "set a licence this platform can no longer read; set it again for"
            return None, f"{backend.name} needs a licence this organization {why} it"
        return None, None
    wanted = spec(backend.manifest)
    licence: dict[str, Any] = {"env": dict(stored.get("env") or {})}
    if stored.get("file") is not None:
        licence["file"] = {"name": wanted["file"], "text": stored["file"], "env": wanted["file_env"]}
    return licence, None


def solver_list(setting: str) -> set[str]:
    """A setting's comma-separated solver names."""
    return {name.strip() for name in (setting or "").split(",") if name.strip()}
