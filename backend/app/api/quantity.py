"""The platform's number, on the wire.

Since migration 0015 a quantity is `numeric(15, 6)` in the database and a
`Decimal` in Python. Neither of those is a JSON type, and the two obvious ways
to bridge that are both wrong on their own:

- Pydantic's default sends a `Decimal` as a **string** (`"0.000000"`). That is
  lossless, and it silently changes the wire contract for every existing
  client and every stored fixture -- a field that was `0` becomes `"0.000000"`
  and arithmetic on it in a browser becomes string concatenation.
- A bare `float` would be the right JSON shape and would lose precision on a
  wide value.

So: a JSON **number**, at a precision the column is bounded to make exact.
Fifteen significant digits is what an IEEE-754 double round-trips without
loss, which is why 0015 chose `numeric(15, 6)` -- the bridge is lossless
because the column was sized for it.

And an integral value keeps its integer shape, so `3` does not arrive as
`3.0`. That is the same decision `trim_scale` makes in `snapshot_dataset()`,
for the same reason: a model that has never used a decimal should not be able
to tell that decimals exist.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated

from pydantic import BeforeValidator, Field, PlainSerializer

# Nine integer digits and six decimal places: the widest `numeric(15, 6)`
# holds. Out of range reaches the driver as SQLSTATE 22003, which
# `translate_db_error` re-raises untouched -- a 500 where a 422 belongs.
NUMERIC_LIMIT = Decimal(10) ** 9 - Decimal(10) ** -6


def as_decimal(value):
    """A JSON number into an exact decimal, by way of its own text.

    `Decimal(0.1)` built from a float faithfully preserves binary floating
    point's error to fifty digits and then fails the `decimal_places` check;
    the shortest round-tripping repr recovers the number that was typed.

    `bool` and `str` are refused rather than converted, on the footing the
    integer version used: `isinstance(True, int)` is true in Python and would
    make a coefficient of `true` a silent 1, and a client sending `"5"` has a
    type bug that quietly parsing would leave in place.
    """
    if isinstance(value, bool):
        raise ValueError("a quantity is a number, not a boolean")
    if isinstance(value, (int, float)):
        return Decimal(str(value))
    if isinstance(value, Decimal):
        return value
    raise ValueError("a quantity is a JSON number")


def as_json_number(value: Decimal | None):
    """Out as a number, and as a whole one where it is whole."""
    if value is None:
        return None
    return int(value) if value == value.to_integral_value() else float(value)


#: Six decimal places — the scale of `numeric(15, 6)` (migration 0015).
QUANTITY_SCALE = Decimal("0.000001")


def report_quantity(value: float | int, *, integral: bool = False) -> float | int:
    """A solver float at the platform's precision.

    Branch-and-cut and simplex return IEEE doubles; writing them straight
    into `run.objective` lets two runs of the same continuous model disagree
    at the seventeenth digit. Quantising to six places matches the column
    and cuts the floating-point tail (e.g. milp's `53.99999999999999` for a
    true 54). An integral model still rounds to a whole number first — the
    same rule `_report` used before this lived in one place.
    """
    if integral:
        return round(value)
    return as_json_number(Decimal(str(value)).quantize(QUANTITY_SCALE))


#: Sent in, checked, and sent back out. The order of the metadata matters:
#: the constraints attach to the decimal and the converter wraps the result,
#: so a JSON number becomes an exact decimal first and is then measured.
#: Reversed, Pydantic has a function schema to attach `max_digits` to and
#: refuses to build the model at all.
Quantity = Annotated[
    Decimal,
    Field(max_digits=15, decimal_places=6, ge=-NUMERIC_LIMIT, le=NUMERIC_LIMIT),
    BeforeValidator(as_decimal),
    PlainSerializer(as_json_number, when_used="json"),
]

#: Read-only: a value the database produced, which needs no checking on the
#: way out but does need the same JSON shape.
QuantityOut = Annotated[Decimal, PlainSerializer(as_json_number, when_used="json")]
