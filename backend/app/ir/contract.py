"""The problem IR contract, as the server reads it.

`contract.json` beside this module is the one artefact both languages
read -- the client restates it in `frontend/src/ir/contract.ts` and a
vitest parity test deep-compares the two, exactly as it already does for
`app/expressions/catalogue.json` (Ruling 37). Everything here is read
from the file rather than restated, so there is no Python copy to drift.

One thing is checked at import time rather than written down twice: every
name in `filterOperators` must exist in the expression catalogue's
`operators`. A filter inside a model is the *same* comparison the entity
filter already offers, and the whole point of importing
`app.expressions.catalogue` here is that adding an operator to the IR
that the platform does not have fails at import, not at request time.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from app.expressions.catalogue import OPERATORS

CONTRACT_PATH = Path(__file__).with_name("contract.json")

_RAW: dict[str, Any] = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))

#: Everything but the `//` commentary; JSON has no comments, so the file
#: carries its own as a key nothing reads.
CONTRACT: dict[str, Any] = {k: v for k, v in _RAW.items() if not k.startswith("//")}

IR_VERSION: int = CONTRACT["version"]
#: The versions a document may carry; `IR_VERSION` is the one written.
ACCEPTED_VERSIONS: tuple[int, ...] = tuple(CONTRACT["acceptedVersions"])

MAX_DEPTH: int = CONTRACT["limits"]["maxDepth"]
MAX_TERMS: int = CONTRACT["limits"]["maxTerms"]
MAX_INDICES: int = CONTRACT["limits"]["maxIndices"]
MAX_IR_BYTES: int = CONTRACT["limits"]["maxIrBytes"]

NAME_PATTERN: str = CONTRACT["namePattern"]
#: `re.fullmatch` on the unanchored body, never `re.match` on the anchored
#: form: Python's `$` also matches just before a trailing newline while
#: Postgres's does not, so `"employee\n"` would otherwise pass here and be
#: refused by `entity_type`'s own CHECK as a confusing 409 later
#: (`app/api/validation.py` records the same trap).
NAME_RE = re.compile(NAME_PATTERN.removeprefix("^").removesuffix("$"))

REQUIRED_KEYS: tuple[str, ...] = tuple(CONTRACT["topLevel"]["required"])
OPTIONAL_KEYS: tuple[str, ...] = tuple(CONTRACT["topLevel"]["optional"])
ALL_KEYS: frozenset[str] = frozenset(REQUIRED_KEYS + OPTIONAL_KEYS)

VARIABLE_DOMAINS: frozenset[str] = frozenset(CONTRACT["variableDomains"])
RELATIONS: frozenset[str] = frozenset(CONTRACT["relations"])
#: How far a `via` binding walks. `one` is a single edge; `any` is the
#: transitive closure; `any_or_self` is that plus the anchor itself, which is
#: the shape `entity_descendants()` has always returned ("node + everything
#: beneath it") and the one a planner means by "counting its sub-units".
TRAVERSAL_DEPTHS: frozenset[str] = frozenset(CONTRACT["traversalDepths"])
SEVERITIES: frozenset[str] = frozenset(CONTRACT["severities"])
SENSES: frozenset[str] = frozenset(CONTRACT["senses"])
OBJECTIVE_MODES: frozenset[str] = frozenset(CONTRACT["objectiveModes"])
TERM_KINDS: frozenset[str] = frozenset(CONTRACT["termKinds"])
FILTER_OPERATORS: frozenset[str] = frozenset(CONTRACT["filterOperators"])
ARITHMETIC_ATTR_TYPES: frozenset[str] = frozenset(CONTRACT["arithmeticAttrTypes"])

#: Every reason an IR can be refused, keyed by code. `where` is `shape`
#: (decidable from the document alone) or `domain` (needs the rows).
RULES: dict[str, dict[str, str]] = {r["code"]: r for r in CONTRACT["rules"]}
SHAPE_RULES: frozenset[str] = frozenset(c for c, r in RULES.items() if r["where"] == "shape")
DOMAIN_RULES: frozenset[str] = frozenset(c for c, r in RULES.items() if r["where"] == "domain")

#: The keys a constraint may carry. Not in the JSON as a list of its own:
#: they are the contract's prose, and a typo'd key is caught by
#: `constraint_key_unknown` against this tuple.
CONSTRAINT_KEYS: frozenset[str] = frozenset(
    {"id", "note", "forall", "left", "relation", "right", "severity", "weight"}
)

_missing_operators = sorted(FILTER_OPERATORS - set(OPERATORS))
if _missing_operators:  # pragma: no cover -- an import-time contradiction
    raise RuntimeError(
        "the IR contract names filter operators the expression catalogue does "
        f"not have: {_missing_operators}. There is one operator vocabulary on "
        "this platform; add them to app/expressions/catalogue.json or remove "
        "them here."
    )
