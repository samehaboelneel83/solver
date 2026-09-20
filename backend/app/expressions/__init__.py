"""Server-side expression filtering (Task 14d).

The same document the browser builds (`frontend/src/expressions/`), read
off the wire and compiled to a parameterised SQL predicate over `entity`.

Two steps, in this order, and the order is the security property:

1. :func:`parse_expression` -- a pure function of a string. It has no
   `Session` in scope, so everything it refuses (malformed JSON, an
   unsupported version, a nest too deep, too many rules, a list too long,
   an unknown operator or function, a field id that is not one this version
   expresses, a value of the wrong JSON shape) is refused with no query
   executed, structurally rather than by good behaviour.
2. :func:`compile_expression` -- the part that needs `attribute_def` and
   `relationship_type` to know what the domain declares. It reads those two
   tables and nothing else, so even the refusals it makes (unknown
   attribute, wrong data type for a function, an operator that data type
   does not offer, an enum value outside `enum_values`) happen without
   `entity` being read.

Both raise :class:`ExpressionRefusal`, which carries a `path` into the
document. `app/api/entities.py` turns that into FastAPI's own 422 list
shape with `loc = ["query", "expr", *path]` (Ruling 19's one body shape;
Ruling 30's "consumers key on `loc`").

The catalogue of what may be named lives in `catalogue.json` beside this
module and is shared with the client -- see `catalogue.py`.
"""

from app.expressions.compiler import compile_expression
from app.expressions.parse import (
    ExpressionRefusal,
    ParsedDocument,
    ParsedGroup,
    ParsedRule,
    parse_expression,
)

__all__ = [
    "ExpressionRefusal",
    "ParsedDocument",
    "ParsedGroup",
    "ParsedRule",
    "compile_expression",
    "parse_expression",
]
