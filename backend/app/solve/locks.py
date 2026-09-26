"""Locks: parts of a plan held fixed while the rest is solved again (queue R24).

A scenario's `patch.lock` lists them. Each is one of three shapes:

- a cell -- ``{"var": "assign", "index": ["ann", "mon", "early"], "value": 1}``;
- a slice of an earlier run -- ``{"var": "assign", "where": {"day": ["mon"]}, "from_run": 812}``:
  every cell of `assign` whose `day` is listed takes its value in run 812, a cell that run left
  at zero included, so locking a day locks who works it *and* who does not. A set that appears
  twice in the variable's index (`[stop, stop]`) must match at every position;
- a horizon -- ``{"before": "2026-10-01", "attr": "date", "set": "day", "from_run": 812}``: every
  cell of every variable indexed by `day` whose day's `date` is before the cut-off takes its value
  in run 812 (``"vars": [...]`` narrows it to some variables). Both strings compare as text, which
  orders ISO dates; both numbers compare as numbers; anything else is refused.

**Rows, not bounds.** Each locked cell is a row `x = value` named ``lock:N`` (N counts the locks
from 1, as listed). A bound would be as exact, but the conflict finder works over rows: when a
lock makes the model infeasible, the answer must be able to say "lock 2" beside the rules it
fights. The name cannot collide with a rule's, which the IR's name pattern keeps to lower-case
letters, digits and underscores.

A lock that cannot be kept as written -- a value outside the decision's bounds today, an amount
the earlier run did not keep, an attribute a day lacks -- is refused with `LockRefused`, whose
`code` is the same the API refuses a scenario with. A lock that is merely incompatible with the
rules is not refused: that is a planning fact, and the run says it is infeasible and why.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal
from typing import Any

from app.solve.compile import Compiled, Constraint, Linear, Unsupported, VarKey

#: The prefix of every lock row's id; the rest is the lock's position in the patch, from 1.
PREFIX = "lock:"


class LockRefused(Unsupported):
    """A lock that cannot be kept as written. `code` names the reason, as the API refuses it."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class Base:
    """What an earlier run decided: its roster and, where it kept them, its amounts."""

    assignments: dict[str, list[list[str]]]
    amounts: dict[str, list[dict[str, Any]]] | None

    def value(self, key: VarKey, domain: str) -> Decimal | None:
        """The run's value for one cell, or None when it used the cell and kept no amount."""
        name, index = key
        used = [tuple(row) for row in self.assignments.get(name, [])]
        if index not in used:
            return Decimal(0)
        if domain == "binary":
            return Decimal(1)
        for cell in (self.amounts or {}).get(name, []):
            if tuple(cell["index"]) == index:
                return Decimal(str(cell["value"]))
        return None


def runs_named(locks: list[dict[str, Any]]) -> set[int]:
    """The earlier runs the locks read from."""
    return {int(lock["from_run"]) for lock in locks if "from_run" in lock}


def apply(compiled: Compiled, locks: list[dict[str, Any]], bases: dict[int, Base],
          sets: dict[str, list[dict[str, Any]]]) -> Compiled:
    """The model with every lock added as rows. Symmetry-ordering rows are given up: they may
    order interchangeable entities against the very plan a lock keeps."""
    if not locks:
        return compiled
    added: list[Constraint] = []
    for n, lock in enumerate(locks, start=1):
        rule = f"{PREFIX}{n}"
        for key, value in _cells(compiled, lock, bases, sets, rule):
            added.append(Constraint(rule, _label(compiled, key), Linear(coeffs={key: Decimal(1)}), "=",
                                    Linear(const=value)))
    return replace(compiled, constraints=[*compiled.constraints, *added], symmetry=[])


def _cells(compiled: Compiled, lock: dict[str, Any], bases: dict[int, Base],
           sets: dict[str, list[dict[str, Any]]], rule: str) -> list[tuple[VarKey, Decimal]]:
    if "index" in lock:
        key = (lock["var"], tuple(str(k) for k in lock["index"]))
        variable = _variable(compiled, key, rule)
        value = Decimal(str(lock["value"]))
        _within(variable, value, key, rule)
        return [(key, value)]

    base = bases.get(int(lock["from_run"]))
    if base is None:
        raise LockRefused("lock_run_invalid", f"{rule}: run {lock['from_run']} is not an answered run of this problem")
    if "where" in lock:
        names = [lock["var"]]
        if names[0] not in compiled.var_index_sets:
            raise LockRefused("lock_unknown", f"{rule}: this model has no decision {names[0]!r}")
        wanted = {s: {str(k) for k in keys} for s, keys in lock["where"].items()}
        for s in wanted:
            if s not in compiled.var_index_sets[names[0]]:
                raise LockRefused("lock_unknown", f"{rule}: {names[0]!r} is not indexed by {s!r}")
    else:
        wanted = {lock["set"]: _before(lock, sets.get(lock["set"]), rule)}
        names = lock.get("vars") or [n for n, index in compiled.var_index_sets.items()
                                     if lock["set"] in index and not n.startswith("__")]
        for name in names:
            if lock["set"] not in compiled.var_index_sets.get(name, []):
                raise LockRefused("lock_unknown", f"{rule}: {name!r} is not indexed by {lock['set']!r}")

    out = []
    for key, variable in compiled.variables.items():
        name, index = key
        if name not in names:
            continue
        positions = compiled.var_index_sets[name]
        if not all(index[p] in wanted[s] for p, s in enumerate(positions) if s in wanted):
            continue
        if key in compiled.intervals:
            raise LockRefused("lock_unsupported", f"{rule}: {name!r} is a task in time; a lock fixes amounts and choices")
        value = base.value(key, variable.domain)
        if value is None:
            raise LockRefused("lock_amounts_missing",
                              f"{rule}: run {lock['from_run']} used {name}{list(index)} and kept no amount for it")
        _within(variable, value, key, rule)
        out.append((key, value))
    return out


def _before(lock: dict[str, Any], rows: list[dict[str, Any]] | None, rule: str) -> set[str]:
    """The keys of the set's entities whose attribute is before the cut-off."""
    if rows is None:
        raise LockRefused("lock_unknown", f"{rule}: this model has no set {lock['set']!r}")
    cut, attr, keys = lock["before"], lock["attr"], set()
    for row in rows:
        value = row.get(attr)
        if value is None:
            raise LockRefused("lock_unknown", f"{rule}: {lock['set']} {row['id']!r} has no {attr!r}")
        numbers = all(isinstance(v, (int, float, Decimal)) and not isinstance(v, bool) for v in (value, cut))
        if not numbers and not (isinstance(value, str) and isinstance(cut, str)):
            raise LockRefused("lock_unknown", f"{rule}: {attr!r} {value!r} and the cut-off {cut!r} do not compare")
        if value < cut:
            keys.add(str(row["id"]))
    return keys


def _variable(compiled: Compiled, key: VarKey, rule: str):
    name, index = key
    positions = compiled.var_index_sets.get(name)
    if positions is None or name.startswith("__"):
        raise LockRefused("lock_unknown", f"{rule}: this model has no decision {name!r}")
    if len(index) != len(positions):
        raise LockRefused("lock_index_arity", f"{rule}: {name!r} is indexed by {len(positions)}, not {len(index)}")
    if key in compiled.intervals:
        raise LockRefused("lock_unsupported", f"{rule}: {name!r} is a task in time; a lock fixes amounts and choices")
    if key not in compiled.variables:
        raise LockRefused("lock_unknown", f"{rule}: {name}{list(index)} is not a decision of this model")
    return compiled.variables[key]


def _within(variable, value: Decimal, key: VarKey, rule: str) -> None:
    if not variable.lower <= value <= variable.upper:
        raise LockRefused("lock_out_of_bounds",
                          f"{rule}: {key[0]}{list(key[1])} = {value} is outside {variable.lower}..{variable.upper}")
    if variable.domain in ("binary", "integer") and value != value.to_integral_value():
        raise LockRefused("lock_out_of_bounds", f"{rule}: {key[0]}{list(key[1])} is whole, not {value}")


def _label(compiled: Compiled, key: VarKey) -> dict[str, str]:
    """The cell by its sets' names, as a rule instance is named; by position where a set repeats."""
    name, index = key
    positions = compiled.var_index_sets.get(name, [])
    if len(set(positions)) == len(positions) == len(index):
        return {"var": name, **{s: str(k) for s, k in zip(positions, index)}}
    return {"var": name, **{f"{s}#{p + 1}": str(k) for p, (s, k) in enumerate(zip(positions, index))}}
