"""`q` on a list endpoint (Epic UX, U-1): one way to search every large collection.

A search is a case-insensitive substring of the item's name (or its other
text columns), and -- when the whole query is a number -- the item's own id,
so a planner who has an id from a link, an email or an audit row finds it
however long the list. `%` and `_` in the query are matched literally.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import String, cast, or_

#: Longer than any name the platform stores; a longer query matches nothing useful.
MAX_QUERY = 200


def _escaped(q: str) -> str:
    return q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def condition(q: str | None, *text_columns: Any, id_column: Any = None, number_columns: tuple = ()):
    """The WHERE condition for `q`, or None when there is nothing to search for."""
    if q is None:
        return None
    q = q.strip()[:MAX_QUERY]
    if not q:
        return None
    pattern = f"%{_escaped(q)}%"
    terms = [cast(column, String).ilike(pattern, escape="\\") for column in text_columns]
    if q.isdigit():
        if id_column is not None:
            terms.append(id_column == int(q))
        terms.extend(column == int(q) for column in number_columns)
    return or_(*terms)


def search_text(model: Any, *names: str) -> list[Any]:
    """The named text columns this model has -- `description` is optional on some tables."""
    return [getattr(model, name) for name in names if hasattr(model, name)]
