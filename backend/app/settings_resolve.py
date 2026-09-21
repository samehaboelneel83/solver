"""What a setting actually is, here, for this problem.

Three levels override in one direction -- problem beats domain beats platform
beats the built-in default -- and that is the whole rule. It is deliberately
the simplest rule that is useful: no inheritance graph, no priorities, no
merging of partial values. A rule a person cannot predict from the screen is
worse than no configurability at all, because then nobody can say why a run
took ninety seconds.

Every resolution can say **where** the value came from. A number nobody can
attribute is a number nobody can change with confidence: "60, from this
domain" tells you which of three places to edit, and "60, the built-in
default" tells you that nothing has been set anywhere.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

#: Most specific first. This tuple *is* the precedence rule.
_ORDER = ("problem", "domain", "platform")


@dataclass(frozen=True)
class Resolved:
    key: str
    value: Any
    #: "problem", "domain", "platform", or "default" when nothing is set.
    source: str
    value_type: str
    description: str


def resolve(db: Session, *, problem_id: int | None = None, domain_id: int | None = None) -> dict[str, Resolved]:
    """Every setting, with the value that applies and where it came from.

    `domain_id` is looked up from the problem when only a problem is given, so
    a caller cannot accidentally resolve a problem against the wrong domain.
    """
    if problem_id is not None and domain_id is None:
        domain_id = db.execute(
            text("SELECT domain_id FROM problem WHERE id = :p"), {"p": problem_id}
        ).scalar()

    keys = db.execute(
        text("SELECT key, value_type, default_value, description FROM setting_key ORDER BY key")
    ).mappings().all()

    rows = db.execute(
        text(
            "SELECT scope::text AS scope, key, value FROM setting"
            " WHERE scope = 'platform'"
            "    OR (scope = 'domain'  AND scope_id = :d)"
            "    OR (scope = 'problem' AND scope_id = :p)"
        ),
        {"d": domain_id, "p": problem_id},
    ).mappings().all()

    by_scope: dict[str, dict[str, Any]] = {scope: {} for scope in _ORDER}
    for row in rows:
        by_scope[row["scope"]][row["key"]] = row["value"]

    resolved: dict[str, Resolved] = {}
    for key in keys:
        name = key["key"]
        source, value = "default", key["default_value"]
        for scope in _ORDER:
            if name in by_scope[scope]:
                source, value = scope, by_scope[scope][name]
                break
        resolved[name] = Resolved(
            key=name,
            value=value,
            source=source,
            value_type=key["value_type"],
            description=key["description"],
        )
    return resolved


def value_of(db: Session, key: str, *, problem_id: int | None = None, default: Any = None) -> Any:
    """One setting's value, or `default` if the platform has no such key.

    `default` is for a caller that names a key this build may not have -- a
    missing key is a deployment fact, not a reason to fail a solve.
    """
    found = resolve(db, problem_id=problem_id).get(key)
    return default if found is None else found.value
