"""The shared catalogue, as the server reads it.

`catalogue.json` beside this module is the one artefact both languages
read: the client's TypeScript modules are pinned to it by a vitest parity
test (`frontend/src/expressions/parity.test.ts`), and everything here is
read from it rather than restated, so there is no Python copy to drift.

Two things are deliberately NOT in the shared file:

- :data:`MAX_EXPRESSION_BYTES`, because it is a transport limit rather than
  a fact about the expression language. The client cannot enforce it
  usefully (it would have to serialise to find out) and a document that
  reaches it is already past every limit that has a meaning.
- The SQL itself. Each catalogue entry carries a ``sql`` string, and that
  string is **documentation**: `compiler.py` keys a table of SQLAlchemy
  builders by the same names, so nothing in the JSON is ever formatted,
  concatenated or executed. `test_expressions_catalogue.py` asserts the two
  key sets are equal, which is what makes an entry declared here without an
  implementation -- or implemented without being declared -- a test
  failure rather than a surprise at run time.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

CATALOGUE_PATH = Path(__file__).with_name("catalogue.json")

_RAW: dict[str, Any] = json.loads(CATALOGUE_PATH.read_text(encoding="utf-8"))

#: Everything but the `//` commentary; JSON has no comments, so the file
#: carries its own as a key nothing reads.
CATALOGUE: dict[str, Any] = {k: v for k, v in _RAW.items() if not k.startswith("//")}

EXPRESSION_VERSION: int = CATALOGUE["version"]

MAX_DEPTH: int = CATALOGUE["limits"]["maxDepth"]
MAX_RULES: int = CATALOGUE["limits"]["maxRules"]
MAX_LIST_LENGTH: int = CATALOGUE["limits"]["maxListLength"]

#: How long the `expr` query parameter may be. 20 kB is roughly forty times
#: the largest document the limits above allow a builder to produce, and it
#: bounds the work `json.loads` does before any of the other limits can be
#: applied -- the one check that has to come first.
MAX_EXPRESSION_BYTES = 20_000

OPERATORS: dict[str, dict[str, str]] = CATALOGUE["operators"]
OPERATORS_BY_TYPE: dict[str, list[str]] = CATALOGUE["operatorsByType"]
NULL_OPERATORS: list[str] = CATALOGUE["nullOperators"]
FUNCTIONS: dict[str, dict[str, Any]] = CATALOGUE["functions"]
RELATIONSHIP_DIRECTIONS: list[str] = CATALOGUE["relationshipDirections"]

#: `key`, `label`, `sort_order`, `active` -- keyed by name, so a lookup is a
#: dict access and never a string that becomes SQL.
COLUMNS: dict[str, dict[str, Any]] = {c["column"]: c for c in CATALOGUE["columns"]}

#: The seven `attr_type` labels, from the operator table's own keys.
DATA_TYPES: frozenset[str] = frozenset(OPERATORS_BY_TYPE)


def operators_for(data_type: str, nullable: bool) -> list[str]:
    """The operators a field of this type offers -- the server's copy of
    `operators.ts`'s `operatorsForField`, reading the same table. A required
    attribute is guaranteed present by `entity_validate`, so "is empty"
    there is refused rather than silently answered false."""
    return [*OPERATORS_BY_TYPE[data_type], *(NULL_OPERATORS if nullable else [])]


def function_return_type(name: str, argument_type: str | None) -> str:
    """A call's data type. `argument_type` is None for `count`, which has no
    field argument."""
    returns = FUNCTIONS[name]["returns"]
    if returns != "argument":
        return returns
    # Only reachable for `abs`, whose argument types are both numeric.
    return argument_type or "number"
