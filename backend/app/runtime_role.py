"""Give `solver_runtime` a login, and print the URL the app should use.

`python -m app.runtime_role` connects as the owner (MIGRATION_DATABASE_URL,
else DATABASE_URL), sets a fresh random password on `solver_runtime`
(migration 0037), and prints `DATABASE_URL=<that role's URL>` on stdout --
nothing else, so `scripts/runtime_role.sh` can redirect it straight into
`.env.runtime` and the password is never shown. Running it again rotates
the password; the running services then need a restart to pick it up.
"""

from __future__ import annotations

import os
import secrets

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

ROLE = "solver_runtime"


def runtime_url(owner_url: str, password: str) -> str:
    """The owner's URL with the runtime role's name and password in it:
    same driver, host, port and database."""
    return (
        make_url(owner_url)
        .set(username=ROLE, password=password)
        .render_as_string(hide_password=False)
    )


def main() -> None:  # pragma: no cover -- run at deploy time
    owner_url = os.environ.get("MIGRATION_DATABASE_URL") or os.environ["DATABASE_URL"]
    if make_url(owner_url).username == ROLE:
        raise SystemExit(f"{ROLE} cannot set its own password; give this the owner's URL")
    password = secrets.token_urlsafe(32)
    engine = create_engine(owner_url)
    with engine.begin() as connection:
        connection.execute(
            text(f"ALTER ROLE {ROLE} WITH LOGIN PASSWORD :password"), {"password": password}
        )
    engine.dispose()
    print(f"DATABASE_URL={runtime_url(owner_url, password)}")


if __name__ == "__main__":  # pragma: no cover
    main()
