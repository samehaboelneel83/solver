"""What every construct's expansion uses: the refusal, the field readers, and the term helpers."""

from __future__ import annotations

import copy
from typing import Any

from app.agent.files import FileRefused


class ConstructRefused(FileRefused):
    """A construct written so that it cannot be expanded: the message says what to write (a refusal like a
    file's, so the Assistant tells the model and the turn goes on)."""


def bindings(value: Any, what: str) -> list[dict[str, Any]]:
    """A field holding bindings (one, or a list): copied; an empty one is []."""
    if value in (None, []):
        return []
    value = [value] if isinstance(value, dict) else value
    if not isinstance(value, list) or not all(isinstance(b, dict) and b.get("index") and b.get("set") for b in value):
        raise ConstructRefused(f'{what} is a list of bindings like {{"index": "k", "set": "<record kind>"}}')
    return copy.deepcopy(value)


def var(value: Any, what: str) -> dict[str, Any]:
    """A field holding a decision reference: copied."""
    if not isinstance(value, dict) or not isinstance(value.get("var"), str):
        raise ConstructRefused(f'{what} is a decision: {{"var": "<name>", "index": [...]}}')
    return copy.deepcopy(value)


def body_object(body: Any) -> dict[str, Any]:
    """The construct's body, which is an object."""
    if not isinstance(body, dict):
        raise ConstructRefused("write it as an object")
    return body


def renamed(term: Any, old: str, new: str) -> Any:
    """The term with index `old` read as `new` (the period before)."""
    if isinstance(term, dict):
        out = {}
        for k, v in term.items():
            if k == "index" and isinstance(v, list):
                out[k] = [new if x == old else x for x in v]
            elif k == "of" and v == old:
                out[k] = new
            else:
                out[k] = renamed(v, old, new)
        return out
    if isinstance(term, list):
        return [renamed(v, old, new) for v in term]
    return term


def add(terms: list[Any]) -> Any:
    """The sum of the terms as the language writes it: none is 0, one is itself."""
    terms = [t for t in terms if t is not None]
    if not terms:
        return {"const": 0}
    return terms[0] if len(terms) == 1 else {"add": terms}


def neg(term: Any) -> Any:
    return {"mul": [{"const": -1}, term]}
