"""The problem IR: what a model is on this platform.

`contract.json` is the machine-readable half of
`docs/contracts/problem-ir.md` and the one artefact both languages read;
`contract.py` loads it; `validate.py` judges a document against it in two
halves, one of which needs no database.

Consumers import from here.
"""

from app.ir.contract import CONTRACT, CONTRACT_PATH, IR_VERSION, RULES
from app.ir.validate import Refusal, check_against_domain, check_shape, validate_ir

__all__ = [
    "CONTRACT",
    "CONTRACT_PATH",
    "IR_VERSION",
    "RULES",
    "Refusal",
    "check_against_domain",
    "check_shape",
    "validate_ir",
]
