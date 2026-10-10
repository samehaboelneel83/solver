"""A model as a QUBO -- quadratic unconstrained binary optimisation -- for annealers, quantum or not (10 October 2026).

A QUBO is `minimise y' Q y + offset` over yes/no values `y`, nothing else: the form D-Wave's annealers, digital
annealers (Fujitsu), simulated-bifurcation machines (Toshiba) and the QUBO solvers in dimod / qbsolv take. Any
model of yes/no and bounded whole-number decisions, linear rules and a linear or quadratic goal becomes one, the
same way for every model:

1. **Decisions as bits.** A yes/no decision is one bit; a whole number in [l, u] is `l + sum(c_k y_k)` with the
   coefficients 1, 2, 4, ... and the last cut so they add up to exactly `u - l` (every value reachable, none past
   it). A continuous decision has no exact bits and is refused by name.
2. **The goal** in those bits, turned to a minimum.
3. **Each rule as a square.** Scaled to whole numbers (a rule with more than `MAX_DECIMALS` places is refused),
   `a.x = b` adds `P (a.x - b)^2`; `a.x <= b` adds `P (a.x + s - b)^2` with a slack `s` in [0, b - least a.x] as
   bits; `>=` is turned round; a rule no answer can break is left out.
4. **The weight `P`** is 1 more than the most the goal can move over all the bits (the sum of its coefficients'
   sizes): a broken whole-number rule costs at least `P`, so a QUBO's least value is the model's optimum whenever
   the model has an answer, and an answer that breaks a rule is never the least. A smaller weight may be given;
   it can make an annealer's landscape gentler, with no such promise.

What is refused, by name: continuous decisions, conditional / scheduling / quadratic rules, piecewise or
function terms, goals in order (`lex`), and a QUBO of more than `MAX_TERMS` entries.

`to_qubo` returns the matrix and how to read an answer back (`decode`); `export` writes it as JSON in dimod's
binary-quadratic-model layout or as a qbsolv `.qubo` file; `anneal` (backend `qubo-anneal`) solves it here by
simulated annealing over many replicas at once, and every answer is checked on the model's own rows.
"""
from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

import numpy as np

from app.solve.compile import Compiled, Linear, VarKey
from app.solve.result import Solution

MAX_DECIMALS = 6
MAX_TERMS = 4_000_000
#: The most bits `anneal` holds as a dense matrix.
MAX_ANNEAL_BITS = 4000


class NotQubo(ValueError):
    """The model cannot be written as a QUBO; the message says why."""


@dataclass
class Qubo:
    #: Bit names, in order: `name[index]#k` for bit k of a decision, `slack:rule[n]#k` for a rule's slack.
    bits: list[str]
    #: (i, j) with i <= j -> weight; (i, i) is bit i's own (linear) weight.
    terms: dict[tuple[int, int], float]
    offset: float
    #: The weight each rule's square carries.
    penalty: float
    #: decision -> (lower, [(bit, coefficient), ...]).
    encoding: dict[VarKey, tuple[int, list[tuple[int, int]]]]
    sense: str
    #: The QUBO's value is the goal times this, plus the rules' squares (1 for a minimum, -1 for a maximum).
    turn: int
    rules: int = 0
    dropped: list[str] = field(default_factory=list)
    #: The least nonzero change one bit makes to the goal: how fine an annealer's last temperature must be.
    goal_step: float = 1.0

    def decode(self, sample) -> dict[VarKey, int]:
        """The decisions from a 0/1 value per bit (a sequence, or a mapping by bit name or index)."""
        if isinstance(sample, dict):
            by_name = {name: i for i, name in enumerate(self.bits)}
            values = [0] * len(self.bits)
            for k, v in sample.items():
                values[by_name[k] if isinstance(k, str) else int(k)] = int(round(float(v)))
        else:
            values = [int(round(float(v))) for v in sample]
        return {key: low + sum(c * values[b] for b, c in bits) for key, (low, bits) in self.encoding.items()}

    def energy(self, sample) -> float:
        y = np.asarray(sample, dtype=float)
        return self.offset + sum(w * y[i] * y[j] for (i, j), w in self.terms.items())

    def summary(self) -> dict[str, Any]:
        return {"bits": len(self.bits), "terms": len(self.terms), "penalty": self.penalty, "rules": self.rules,
                "decision_bits": sum(len(b) for _, b in self.encoding.values()), "dropped_rules": self.dropped[:20]}


def _whole(value: Decimal, what: str) -> int:
    if value != value.to_integral_value():
        raise NotQubo(f"{what} is not a whole number after scaling")
    return int(value)


def _bits_for(span: int) -> list[int]:
    """Coefficients 1, 2, 4, ... adding up to exactly `span` (the last one cut)."""
    out, total, step = [], 0, 1
    while total < span:
        c = min(step, span - total)
        out.append(c)
        total += c
        step *= 2
    return out


def _scale(coeffs: dict[VarKey, Decimal], rhs: Decimal, what: str) -> tuple[dict[VarKey, Decimal], Decimal]:
    """The row times the least power of ten that makes every number whole."""
    for places in range(MAX_DECIMALS + 1):
        factor = Decimal(10) ** places
        if all((c * factor) == (c * factor).to_integral_value() for c in coeffs.values()):
            return {k: c * factor for k, c in coeffs.items()}, rhs * factor
    raise NotQubo(f"{what} has a number with more than {MAX_DECIMALS} decimal places")


def to_qubo(compiled: Compiled, *, penalty: float | None = None) -> Qubo:
    if compiled.objective_mode == "lex":
        raise NotQubo("a QUBO has one goal; this model's goals are in order -- weight them into one to export it")
    if compiled.pwl or compiled.functions or compiled.intervals:
        raise NotQubo("a QUBO holds sums and products of decisions; this model has piecewise or function terms "
                      "or time intervals")
    bits: list[str] = []
    encoding: dict[VarKey, tuple[int, list[tuple[int, int]]]] = {}
    for key, var in compiled.variables.items():
        if not var.is_integral:
            raise NotQubo(f"{_name(key)} is continuous, and a QUBO holds only yes/no and bounded whole-number "
                          "decisions")
        if var.default_upper:
            raise NotQubo(f"{_name(key)} has no finite bound, and a QUBO needs one to write it as bits")
        low, high = int(math.ceil(float(var.lower))), int(math.floor(float(var.upper)))
        if high < low:
            raise NotQubo(f"{_name(key)} has no whole value within its bounds")
        if high - low > 2 ** 20:
            raise NotQubo(f"{_name(key)} ranges over {high - low:,} values; give it a tighter upper bound")
        start = len(bits)
        coefs = _bits_for(high - low)
        bits += [f"{_name(key)}#{k}" for k in range(len(coefs))]
        encoding[key] = (low, [(start + k, c) for k, c in enumerate(coefs)])

    terms: dict[tuple[int, int], float] = {}
    offset = 0.0

    def add(i: int, j: int, w: float) -> None:
        if w == 0:
            return
        pair = (i, j) if i <= j else (j, i)
        terms[pair] = terms.get(pair, 0.0) + w
        if len(terms) > MAX_TERMS:
            raise NotQubo(f"the QUBO would hold more than {MAX_TERMS:,} entries")

    def expand(linear: dict[VarKey, Decimal], const: Decimal) -> tuple[list[tuple[int, float]], float]:
        """A linear expression over decisions as (bit, weight) pairs and a constant."""
        out: list[tuple[int, float]] = []
        c = float(const)
        for key, coeff in linear.items():
            if key not in encoding:
                raise NotQubo(f"{_name(key)} is not a decision of the model")
            low, enc = encoding[key]
            c += float(coeff) * low
            out += [(b, float(coeff) * k) for b, k in enc]
        return out, c

    # The goal, as a minimum.
    turn = 1 if compiled.sense == "minimize" else -1
    goal, goal_const = expand(compiled.objective.coeffs, compiled.objective.const)
    offset += turn * goal_const
    for b, w in goal:
        add(b, b, turn * w)
    for (x, y), coeff in compiled.objective_quadratic.items():
        (lx, ex), (ly, ey) = encoding[x], encoding[y]
        c = float(coeff) * turn
        # (lx + sum a_i u_i)(ly + sum b_j v_j)
        offset += c * lx * ly
        for b, k in ex:
            add(b, b, c * ly * k)
        for b, k in ey:
            add(b, b, c * lx * k)
        for bi, ki in ex:
            for bj, kj in ey:
                if bi == bj:
                    add(bi, bi, c * ki * kj)  # y*y = y
                else:
                    add(bi, bj, c * ki * kj)
    reach = sum(abs(w) for w in terms.values()) or 1.0
    goal_step = min((abs(w) for w in terms.values() if w), default=1.0)
    weight = float(penalty) if penalty is not None else float(math.floor(reach) + 1)

    # The rules, each as a square.
    rules, dropped = 0, []
    for c in compiled.constraints:
        what = f"rule {c.id!r}"
        if c.quadratic or c.when is not None or getattr(c, "schedule", None) is not None:
            raise NotQubo(f"{what} is conditional, scheduling or quadratic, which a QUBO's squares cannot hold")
        coeffs: dict[VarKey, Decimal] = dict(c.left.coeffs)
        for key, coeff in c.right.coeffs.items():
            coeffs[key] = coeffs.get(key, Decimal(0)) - coeff
        coeffs = {k: v for k, v in coeffs.items() if v != 0}
        rhs = c.right.const - c.left.const
        relation = c.relation
        if relation in (">", ">="):
            coeffs, rhs = {k: -v for k, v in coeffs.items()}, -rhs
            relation = "<" if relation == ">" else "<="
        coeffs, rhs = _scale(coeffs, rhs, what)
        if relation == "<":
            rhs = Decimal(math.ceil(rhs)) - 1
        elif relation == "<=":
            rhs = Decimal(math.floor(rhs))
        row, const = expand(coeffs, Decimal(0))
        least = const + sum(min(w, 0.0) for _, w in row)
        most = const + sum(max(w, 0.0) for _, w in row)
        b = float(rhs)
        if relation in ("=", "=="):
            if b != round(b):
                raise NotQubo(f"{what} asks whole numbers to equal {b}")
            square = row
            k0 = const - b
        else:
            if most <= b:
                dropped.append(c.id)  # no answer breaks it
                continue
            span = int(round(b - least))
            if span < 0:
                # No answer keeps it: the square stays, so every answer pays for it.
                span = 0
            start = len(bits)
            coefs = _bits_for(span)
            bits += [f"slack:{c.id}[{rules}]#{k}" for k in range(len(coefs))]
            square = row + [(start + k, float(v)) for k, v in enumerate(coefs)]
            k0 = const - b
        # P (sum w_i y_i + k0)^2 = P (sum w_i^2 y_i + 2 sum_{i<j} w_i w_j y_i y_j + 2 k0 sum w_i y_i + k0^2)
        merged: dict[int, float] = {}
        for bit, w in square:
            merged[bit] = merged.get(bit, 0.0) + w
        items = [(bit, w) for bit, w in merged.items() if w != 0]
        offset += weight * k0 * k0
        for n, (bi, wi) in enumerate(items):
            add(bi, bi, weight * (wi * wi + 2 * k0 * wi))
            for bj, wj in items[n + 1:]:
                add(bi, bj, 2 * weight * wi * wj)
        rules += 1
    return Qubo(bits, terms, offset, weight, encoding, compiled.sense, turn, rules, dropped, goal_step)


def _name(key: VarKey) -> str:
    name, index = key
    return f"{name}[{','.join(map(str, index))}]" if index else name


def export(q: Qubo, fmt: str = "json") -> str:
    """`json`: dimod's BinaryQuadraticModel layout (`dimod.BinaryQuadraticModel(linear, quadratic, offset,
    "BINARY")` reads it), with each decision's bits; `qubo`: qbsolv's text format, bits by number."""
    if fmt == "json":
        linear = {q.bits[i]: w for (i, j), w in q.terms.items() if i == j}
        quadratic = [[q.bits[i], q.bits[j], w] for (i, j), w in q.terms.items() if i != j]
        return json.dumps({
            "vartype": "BINARY", "offset": q.offset, "linear": linear, "quadratic": quadratic,
            "variables": q.bits, "penalty": q.penalty, "sense": q.sense,
            "goal": "the QUBO's least value is the goal" + ("" if q.turn == 1 else " times -1") + " when no rule breaks",
            "decisions": {_name(k): {"lower": low, "bits": [[q.bits[b], c] for b, c in enc]}
                          for k, (low, enc) in q.encoding.items()},
        }, indent=1)
    if fmt == "qubo":
        diagonal = [(i, w) for (i, j), w in q.terms.items() if i == j]
        couplers = [(i, j, w) for (i, j), w in q.terms.items() if i != j]
        lines = [f"c QUBO of a model: {len(q.bits)} bits, rule weight {q.penalty:g}, offset {q.offset:g}",
                 f"c bits in order: {' '.join(q.bits[:200])}{' ...' if len(q.bits) > 200 else ''}",
                 f"p qubo 0 {len(q.bits)} {len(diagonal)} {len(couplers)}"]
        lines += [f"{i} {i} {w:.12g}" for i, w in sorted(diagonal)]
        lines += [f"{i} {j} {w:.12g}" for i, j, w in sorted(couplers)]
        return "\n".join(lines) + "\n"
    raise ValueError(f"unknown QUBO format {fmt!r}")


def anneal(compiled: Compiled, *, time_limit: float = 10.0, seed: int | None = None, replicas: int = 32,
           should_stop=None, on_progress=None, penalty: float | None = None) -> Solution:
    """Simulated annealing on the QUBO: `replicas` chains at once, one bit at a time in random order, the
    temperature falling geometrically from the largest single-flip change to a small fraction of the least,
    restarted from the best while time is left; then the best answer that keeps every rule is polished by one-
    and two-bit moves on the decisions (`_polish`). It is returned `feasible` (an annealer proves nothing)."""
    from app.solve.evolve import holds, objective_at

    began = time.monotonic()
    q = to_qubo(compiled, penalty=penalty)
    n = len(q.bits)
    if n > MAX_ANNEAL_BITS:
        raise NotQubo(f"the QUBO has {n:,} bits; qubo-anneal holds at most {MAX_ANNEAL_BITS:,} (export it for "
                      "a larger annealer)")
    stop = should_stop or (lambda: False)
    rng = np.random.default_rng(seed)
    if n == 0:
        values = q.decode([])
        ok = holds(compiled, values)
        # An annealer proves nothing, so never "infeasible": no answer is "unknown".
        return Solution("feasible" if ok else "unknown", False, objective_at(compiled, values) if ok else None,
                        values if ok else {}, round(time.monotonic() - began, 3), "qubo-anneal")
    W = np.zeros((n, n))
    for (i, j), w in q.terms.items():
        if i == j:
            W[i, i] += w
        else:
            W[i, j] += w
            W[j, i] += w
    diag = np.diag(W).copy()
    off = W - np.diag(diag)
    size = abs(diag) + abs(off).sum(axis=1)
    # From hot enough to cross a broken rule's square to cold enough to tell the goal's smallest step.
    hot = float(size.max()) or 1.0
    cold = max(1e-9, 0.1 * q.goal_step)
    R = max(1, replicas)
    Y = rng.integers(0, 2, (R, n)).astype(float)
    best_y, best_e = None, math.inf
    best_ok_y, best_ok_obj = None, None
    sense = 1 if compiled.sense == "minimize" else -1
    deadline = began + max(0.2, float(time_limit))
    sweeps = 200
    while time.monotonic() < deadline and not stop():
        H = Y @ off  # field from the other bits
        for t in range(sweeps):
            T = hot * (cold / hot) ** (t / max(1, sweeps - 1))
            for i in rng.permutation(n):
                # Flipping bit i changes the energy by (1 - 2 y_i)(diag_i + H_i).
                delta = (1 - 2 * Y[:, i]) * (diag[i] + H[:, i])
                accept = (delta <= 0) | (rng.random(R) < np.exp(-np.clip(delta, 0, None) / T))
                if accept.any():
                    change = np.where(accept, 1 - 2 * Y[:, i], 0.0)
                    Y[:, i] += change
                    H += np.outer(change, off[i])
            if time.monotonic() > deadline or stop():
                break
        # Each coupler sits on both sides of `off`, so y' off y counts it twice.
        E = np.einsum("ri,ri->r", Y @ off, Y) / 2 + Y @ diag
        for r in np.argsort(E):
            values = q.decode(Y[r])
            if holds(compiled, values):
                obj = objective_at(compiled, values)
                if best_ok_obj is None or sense * obj < sense * best_ok_obj:
                    best_ok_y, best_ok_obj = Y[r].copy(), obj
                    if on_progress is not None:
                        try:
                            on_progress(obj, None, time.monotonic() - began)
                        except Exception:  # noqa: BLE001 -- progress is a courtesy
                            pass
                break
        r0 = int(np.argmin(E))
        if E[r0] < best_e:
            best_e, best_y = float(E[r0]), Y[r0].copy()
        # Restart: half the chains from the best, half fresh.
        Y = rng.integers(0, 2, (R, n)).astype(float)
        Y[: R // 2] = best_y
        sweeps = min(2000, sweeps * 2)
    if best_ok_y is not None:
        best_ok_y, best_ok_obj = _polish(compiled, q, best_ok_y, best_ok_obj, sense,
                                         deadline + 0.2 * max(0.2, float(time_limit)), stop)
    wall = round(time.monotonic() - began, 3)
    if best_ok_y is None:
        return Solution("unknown", False, None, {}, wall, "qubo-anneal")
    values = q.decode(best_ok_y)
    return Solution("feasible", False, best_ok_obj, values, wall, "qubo-anneal")


#: The most decision bits the polish tries pairs of (all single flips are always tried).
POLISH_PAIRS_BITS = 600


def _polish(compiled: Compiled, q: Qubo, y: np.ndarray, objective, sense: int, until: float, stop):
    """The annealer's best answer, improved by the best one- or two-bit move on the decisions that keeps every
    rule of the model, until none improves -- the moves a penalty's barrier keeps single flips from making.
    Slack bits are left out: each candidate is checked on the model's own rows (`evolve.Model`, a batch at a
    time), not on the squares."""
    from app.solve.evolve import TOLERANCE, Model, holds, objective_at

    try:
        model = Model(compiled, continuous_only=False)
    except Exception:  # noqa: BLE001 -- a model the batch check cannot hold keeps the annealer's answer
        return y, objective
    if len(model.all_keys) != len(model.keys):
        return y, objective
    position = {k: i for i, k in enumerate(model.keys)}
    owner = np.array([position[key] for key, (_, bits) in q.encoding.items() for _ in bits])
    bit = np.array([b for _, bits in q.encoding.values() for b, _ in bits])
    weight = np.array([c for _, bits in q.encoding.values() for _, c in bits], dtype=float)
    if not len(bit):
        return y, objective
    y = y.copy()

    def values_of(vector: np.ndarray) -> np.ndarray:
        decoded = q.decode(vector)
        return np.array([float(decoded[k]) for k in model.keys])

    x = values_of(y)
    goal_now = model.evaluate(x[None, :])[0][0]
    while time.monotonic() < until and not stop():
        step = weight * (1 - 2 * y[bit])  # each decision bit's flip, as a change to its decision
        n = len(bit)
        moves = [np.array([i]) for i in range(n)]
        if n <= POLISH_PAIRS_BITS:
            up, down = np.flatnonzero(step > 0), np.flatnonzero(step < 0)
            moves += [np.array([i, j]) for i in up for j in down]
        best_gain, best_move = 1e-9, None
        for chunk in range(0, len(moves), 4000):
            batch = moves[chunk:chunk + 4000]
            X = np.repeat(x[None, :], len(batch), axis=0)
            for r, move in enumerate(batch):
                np.add.at(X[r], owner[move], step[move])
            goal, breach = model.evaluate(X)
            gain = np.where(breach <= TOLERANCE, goal_now - goal, -np.inf)
            r = int(np.argmax(gain))
            if gain[r] > best_gain:
                best_gain, best_move = float(gain[r]), batch[r]
            if time.monotonic() > until:
                break
        if best_move is None:
            break
        trial = y.copy()
        trial[bit[best_move]] = 1 - trial[bit[best_move]]
        values = q.decode(trial)
        if not holds(compiled, values):
            break
        y, x, goal_now = trial, values_of(trial), goal_now - best_gain
        objective = objective_at(compiled, values)
    return y, objective
