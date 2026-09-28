"""`predict`, compiled: a trained tree ensemble as exact rows (Epic ML).

A `predict` term reads a predictor the dataset froze (`snapshot_dataset()`,
migration 0087). Of data it is a number -- the model evaluated once, a
forecast. Of decisions it is the ensemble itself, written as a mixed-integer
program the way `connected` and `route` are written as rows, so every
backend that solves a MILP solves it and none needs to know what a tree is.

**The formulation.** For each tree, one binary per leaf the decisions can
reach, exactly one of them set; for each split on a leaf's path, a big-M row
that holds the split only while that leaf is the one chosen::

    z[t,l] in {0,1}                    sum_l z[t,l] = 1
    going left  (a_f <= theta):        a_f + M z[t,l] <= theta + M          M = hi_f - theta
    going right (a_f >  theta):        a_f - M z[t,l] >= theta + delta - M  M = theta + delta - lo_f

and the term is ``base + s * sum_t sum_l value[t,l] z[t,l]`` (``s = 1/T`` for
a mean, 1 for a sum). `a_f` is the f-th input, itself linear in the
decisions; `lo_f` and `hi_f` are the least and greatest it can be, from the
decisions' **declared** bounds -- the big-M rule of the rest of the compiler.
An input that reads a decision with no declared upper bound is refused: the
platform's guard ceiling is not a bound a model chose, and a big-M built on
it is too weak to trust.

Two reductions keep the program small:

- **Leaves the bounds rule out are dropped.** A leaf whose path needs
  ``a_f <= 3`` when ``a_f`` cannot go below 5 is never chosen.
- **A path's conditions on one input are merged**: ``x <= 7`` and ``x <= 4``
  on the way down is one row, ``x <= 4``.

`delta` sends an input sitting exactly on a threshold left, as scikit-learn
does. The same `predict` of the same inputs written twice is one set of
binaries.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from app.ml import trees as ml

LEAF = "__leaf"
ROW_ID = "__predict"
DELTA = Decimal("0.000001")
#: Reachable leaves, over every embedded prediction of one model version.
MAX_EMBEDDED_LEAVES = 20_000


@dataclass(frozen=True)
class PredictDef:
    """A prediction the model optimizes over: the predictor, its inputs as
    compiled, and the linear form in the leaf binaries that stands for it."""

    name: str
    model: dict[str, Any]
    arguments: tuple[Any, ...]
    expression: Any

    def inputs_at(self, assignments: dict[Any, Any]) -> list[float]:
        return [float(a.evaluated_at(assignments)) for a in self.arguments]

    def value_at(self, assignments: dict[Any, Any]) -> float:
        """What the trained model itself predicts at these inputs."""
        return ml.predict(self.model, self.inputs_at(assignments))

    def embedded_at(self, assignments: dict[Any, Any]) -> float:
        """What the rows say the prediction is at this assignment."""
        return float(self.expression.evaluated_at(assignments))

    def on_a_threshold(self, assignments: dict[Any, Any]) -> bool:
        """Whether an input sits within `DELTA` above a threshold it is split
        on: there the rows may take either side, and the check is waived."""
        xs = self.inputs_at(assignments)
        gap = float(DELTA) * 2
        for tree in self.model["trees"]:
            for node in tree["nodes"]:
                if "value" not in node and 0 <= xs[node["feature"]] - node["threshold"] <= gap:
                    return True
        return False


def evaluate(model: dict[str, Any], arguments: list[Any]) -> Decimal:
    """A prediction from data: the model's value at constant inputs."""
    value = ml.predict(model, [float(a.const) for a in arguments])
    return Decimal(repr(value))


def embed(compiler: Any, name: str, model: dict[str, Any], arguments: list[Any], where: str) -> Any:
    """The linear form standing for ``name(arguments)``; its rows and leaf
    binaries are added to ``compiler``."""
    from app.solve.compile import Constraint, Linear, Unsupported, Variable

    for existing in compiler._predictions:
        if existing.name == name and list(existing.arguments) == arguments:
            return existing.expression.copy()

    bounds: list[tuple[Decimal, Decimal]] = []
    for position, argument in enumerate(arguments):
        for key in argument.coeffs:
            if compiler.variables[key].default_upper:
                raise Unsupported(
                    f"input {position} of {name}{where} reads {key[0]}, which declares no upper bound; "
                    "a prediction over a decision needs the decision's bounds -- declare an upper one"
                )
        low, high = compiler._range(argument)
        if not (math.isfinite(low) and math.isfinite(high)):
            raise Unsupported(f"input {position} of {name}{where} has no finite range, so its splits cannot be written")
        bounds.append((Decimal(repr(low)), Decimal(repr(high))))

    number = len(compiler._predictions)
    one = Decimal(1)
    scale = one / len(model["trees"]) if model["aggregation"] == "mean" else one
    expression = Linear(const=Decimal(repr(float(model.get("base", 0)))))
    leaf_total = 0
    for t, tree in enumerate(model["trees"]):
        reachable = []
        for leaf in ml.leaves(tree["nodes"]):
            cut = _merged(leaf, bounds)
            if cut is not None:
                reachable.append((leaf, cut))
        leaf_total += len(reachable)
        compiler._embedded_leaves += len(reachable)
        if compiler._embedded_leaves > MAX_EMBEDDED_LEAVES:
            raise Unsupported(
                f"{name}{where} would add more than {MAX_EMBEDDED_LEAVES} leaf choices to the model; "
                "train it with fewer or shallower trees, or narrow its inputs' bounds"
            )
        if not reachable:  # pragma: no cover -- a tree always covers its whole input space
            raise Unsupported(f"no leaf of tree {t} of {name} is reachable within its inputs' bounds")
        if len(reachable) == 1:
            # The bounds decide this tree: its leaf is a constant.
            expression.const += Decimal(repr(reachable[0][0].value)) * scale
            continue
        choice = Linear()
        for l, (leaf, cut) in enumerate(reachable):
            z = (LEAF, (str(number), str(t), str(l)))
            compiler.variables[z] = Variable(z, "binary", Decimal(0), one)
            choice.coeffs[z] = one
            expression.coeffs[z] = Decimal(repr(leaf.value)) * scale
            label = {"predict": name, "tree": str(t), "leaf": str(l)}
            for f, (upper, lower) in cut.items():
                low, high = bounds[f]
                if upper is not None and high > upper:
                    m = high - upper
                    left = arguments[f].copy().add(Linear(coeffs={z: m}))
                    compiler.constraints.append(Constraint(ROW_ID, dict(label), left, "<=", Linear(const=upper + m)))
                if lower is not None and low < lower + DELTA:
                    m = lower + DELTA - low
                    left = arguments[f].copy().add(Linear(coeffs={z: -m}))
                    compiler.constraints.append(
                        Constraint(ROW_ID, dict(label), left, ">=", Linear(const=lower + DELTA - m))
                    )
        compiler.constraints.append(Constraint(ROW_ID, {"predict": name, "tree": str(t)}, choice, "=", Linear(const=one)))

    compiler._predictions.append(PredictDef(name, model, tuple(a.copy() for a in arguments), expression))
    return expression.copy()


def _merged(
    leaf: ml.Leaf, bounds: list[tuple[Decimal, Decimal]]
) -> dict[int, tuple[Decimal | None, Decimal | None]] | None:
    """The leaf's path as one (at most, greater than) pair per input, or None
    when the inputs' bounds leave the leaf unreachable."""
    at_most: dict[int, Decimal] = {}
    above: dict[int, Decimal] = {}
    for f, theta, goes_left in leaf.path:
        t = Decimal(repr(theta))
        if goes_left:
            at_most[f] = min(at_most.get(f, t), t)
        else:
            above[f] = max(above.get(f, t), t)
    for f in set(at_most) | set(above):
        low, high = bounds[f]
        least = max(low, above[f] + DELTA) if f in above else low
        most = min(high, at_most[f]) if f in at_most else high
        if least > most:
            return None
    return {f: (at_most.get(f), above.get(f)) for f in set(at_most) | set(above)}
