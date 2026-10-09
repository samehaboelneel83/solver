"""A metaheuristic lane: a genetic algorithm, particle swarm, CMA-ES, simulated annealing, tabu search, differential
evolution and ant colony optimisation (queue R14; the last four 9 October 2026).

The exact solvers prove what they return; on some models they return
nothing in the time (a large time-indexed schedule, a nonconvex goal with a
wide bound). These three search instead: a population of whole answers,
bred, flown or sampled towards better ones, each judged on the compiled
model itself -- its goal, and how far it breaks each rule.

- **CMA-ES** (covariance matrix adaptation): the modern standard for a
  continuous search without derivatives. It samples around a mean, and
  learns from the best samples which directions pay, restarting with a
  larger population when it settles (IPOP).
- **Particle swarm**: each particle pulled towards its own best and the
  swarm's; continuous decisions.
- **Genetic algorithm**: tournaments, uniform crossover and per-gene
  mutation within bounds; whole-number, yes-or-no and continuous genes.
- **Simulated annealing**: one answer and batches of its neighbours, Metropolis
  acceptance on the goal plus an adaptive breach penalty, cooling and reheats.
- **Tabu search**: the best non-tabu one-decision move each step, aspiration,
  restarts from the best after stagnation; at home on yes/no decisions.
- **Differential evolution** (JADE): current-to-pbest/1 with an archive and
  self-adapting F and CR.
- **Ant colony** (ACO_R / ACO_MV): an archive of the best answers as pheromone,
  Gaussian kernels for continuous decisions, archive values for whole numbers.

Rules are held by Deb's order: any answer that keeps every rule beats any
that does not, two that keep them are compared on the goal, and two that
break them on how far. Nothing here proves anything: the answer is
`feasible` with no bound, never `optimal`, and the backends register as
`local` so the rules never choose them -- they run when asked for by name,
or after an exact solver ended with nothing (setting `solve.metaheuristic`).
The answer returned is checked on every compiled row first; none kept, no
answer.

Refused: a conditional rule, a scheduling rule, a piecewise curve, and a
decision with no finite bound (a search needs a box to search in). A
function of a decision (`fn`) is computed from its argument, not searched.
"""

from __future__ import annotations

import math
import time
from typing import Any, Callable

import numpy as np

from app.solve.compile import Compiled, Unsupported, VarKey
from app.solve.lp import NotContinuous
from app.solve.progress import report
from app.solve.result import Solution

#: How far a rule may be broken and still count as kept, relative to its size.
TOLERANCE = 1e-6
#: The most population x nonzeros evaluated at once (memory, not speed).
CHUNK = 4_000_000
_FUNCTIONS = {"exp": np.exp, "log": np.log, "sqrt": np.sqrt, "abs": np.abs, "sin": np.sin, "cos": np.cos}


class Model:
    """The compiled model as arrays: decisions in a box, the goal and every row, evaluated a population at a time."""

    def __init__(self, compiled: Compiled, *, continuous_only: bool):
        if compiled.pwl:
            raise Unsupported("a metaheuristic here holds no piecewise curve")
        if compiled.intervals or any(c.schedule is not None for c in compiled.constraints):
            raise Unsupported("a metaheuristic here holds no scheduling rule")
        if any(c.when is not None for c in compiled.constraints):
            raise Unsupported("a metaheuristic here holds no conditional rule")
        derived = {f.y for f in compiled.functions}
        self.keys = [k for k in compiled.variables if k not in derived]
        self.all_keys = self.keys + [f.y for f in compiled.functions]
        position = {k: i for i, k in enumerate(self.all_keys)}
        variables = [compiled.variables[k] for k in self.keys]
        self.lower = np.array([float(v.lower) for v in variables])
        self.upper = np.array([float(v.upper) for v in variables])
        # A bound the model did not declare (the compiler's default ceiling) is no box to search.
        unbounded = next((k for k, v in zip(self.keys, variables)
                          if getattr(v, "default_upper", False) or not (abs(float(v.lower)) < 1e15
                                                                         and abs(float(v.upper)) < 1e15)), None)
        if unbounded is not None:
            raise Unsupported(f"a metaheuristic searches a box, and {unbounded[0]!r} has no finite bound")
        self.integral = np.array([v.is_integral for v in variables], dtype=bool)
        if continuous_only and self.integral.any():
            first = self.keys[int(np.argmax(self.integral))]
            raise NotContinuous(f"this search is for continuous decisions, and {first[0]!r} takes whole numbers")
        self.sign = 1.0 if compiled.sense == "minimize" else -1.0
        self.functions = [(position[f.y], f.name, _dense(f.argument.coeffs, position), float(f.argument.const))
                          for f in compiled.functions]
        self.goal = _dense(compiled.objective.coeffs, position)
        self.goal_const = float(compiled.objective.const)
        self.goal_pairs = _pairs(compiled.objective_quadratic, position)
        # Every row as `lhs relation rhs`, lhs the variable part of left - right.
        rows, cols, vals, rhs, relation, scale, quad = [], [], [], [], [], [], []
        for i, c in enumerate(compiled.constraints):
            coeffs: dict[VarKey, float] = {}
            for k, v in c.left.coeffs.items():
                coeffs[k] = coeffs.get(k, 0.0) + float(v)
            for k, v in c.right.coeffs.items():
                coeffs[k] = coeffs.get(k, 0.0) - float(v)
            for k, v in coeffs.items():
                if v:
                    rows.append(i)
                    cols.append(position[k])
                    vals.append(v)
            bound = float(c.right.const) - float(c.left.const)
            rhs.append(bound)
            relation.append({"<=": 0, ">=": 1}.get(c.relation, 2))
            scale.append(max(1.0, abs(bound)))
            for (a, b), v in (c.quadratic or {}).items():
                quad.append((i, position[a], position[b], float(v)))
        order = np.argsort(np.array(rows, dtype=np.int64), kind="stable")
        self.rows = np.array(rows, dtype=np.int64)[order]
        self.cols = np.array(cols, dtype=np.int64)[order]
        self.vals = np.array(vals)[order]
        self.m = len(compiled.constraints)
        present, self.starts = np.unique(self.rows, return_index=True)
        self.present = present
        self.rhs = np.array(rhs)
        self.relation = np.array(relation, dtype=np.int8)
        self.scale = np.array(scale)
        self.quad = (np.array([q[0] for q in quad], dtype=np.int64), np.array([q[1] for q in quad], dtype=np.int64),
                     np.array([q[2] for q in quad], dtype=np.int64), np.array([q[3] for q in quad]))
        self.n = len(self.keys)
        self.evaluations = 0

    def full(self, X: np.ndarray) -> np.ndarray:
        """Decisions, then each function's value from its argument (in order: one may read another)."""
        F = np.concatenate([X, np.zeros((X.shape[0], len(self.functions)))], axis=1)
        with np.errstate(all="ignore"):
            for y, name, coeffs, const in self.functions:
                F[:, y] = _FUNCTIONS[name](F @ coeffs + const)
        return F

    def evaluate(self, X: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """(goal to minimise, total breach relative to each rule's size), one per row of X."""
        X = np.where(self.integral, np.rint(X), X)
        F = self.full(X)
        self.evaluations += X.shape[0]
        goal = self.sign * (F @ self.goal + self.goal_const + _quadratic(F, self.goal_pairs))
        lhs = np.zeros((X.shape[0], self.m))
        step = max(1, CHUNK // max(1, len(self.vals)))
        for s in range(0, X.shape[0], step):
            part = F[s:s + step]
            if len(self.vals):
                lhs[s:s + step, self.present] = np.add.reduceat(part[:, self.cols] * self.vals, self.starts, axis=1)
        r, a, b, v = self.quad
        if len(v):
            np.add.at(lhs.T, r, (F[:, a] * F[:, b] * v).T)
        gap = lhs - self.rhs
        breach = np.where(self.relation == 0, np.maximum(gap, 0), np.where(self.relation == 1, np.maximum(-gap, 0),
                                                                             np.abs(gap)))
        breach = (breach / self.scale).sum(axis=1)
        bad = ~np.isfinite(goal) | ~np.isfinite(breach)
        goal[bad], breach[bad] = np.inf, np.inf
        return goal, breach

    def rank(self, goal: np.ndarray, breach: np.ndarray) -> np.ndarray:
        """Deb's order, best first."""
        kept = breach <= TOLERANCE
        return np.lexsort((np.where(kept, goal, 0.0), np.where(kept, 0.0, breach)))

    def box(self, U: np.ndarray) -> np.ndarray:
        """From [0, 1] per decision to its range."""
        return self.lower + np.clip(U, 0.0, 1.0) * (self.upper - self.lower)

    def unit(self, X: np.ndarray) -> np.ndarray:
        span = np.where(self.upper > self.lower, self.upper - self.lower, 1.0)
        return np.clip((X - self.lower) / span, 0.0, 1.0)

    def starting(self, hint: dict | None) -> np.ndarray | None:
        if not hint:
            return None
        return np.array([float(hint.get(k, (lo + hi) / 2)) for k, lo, hi in zip(self.keys, self.lower, self.upper)])

    def answer(self, x: np.ndarray) -> dict[VarKey, float | int]:
        x = np.where(self.integral, np.rint(x), x)
        F = self.full(x[None, :])[0]
        out: dict[VarKey, float | int] = {}
        for i, k in enumerate(self.all_keys):
            out[k] = int(F[i]) if i < self.n and self.integral[i] else float(F[i])
        return out


def _dense(coeffs: dict, position: dict) -> np.ndarray:
    out = np.zeros(len(position))
    for k, v in coeffs.items():
        out[position[k]] += float(v)
    return out


def _pairs(pairs: dict, position: dict):
    if not pairs:
        return None
    return (np.array([position[a] for a, _ in pairs]), np.array([position[b] for _, b in pairs]),
            np.array([float(v) for v in pairs.values()]))


def _quadratic(F: np.ndarray, pairs) -> np.ndarray | float:
    if pairs is None:
        return 0.0
    a, b, v = pairs
    return (F[:, a] * F[:, b] * v).sum(axis=1)


class _Best:
    """The best answer so far, by Deb's order, and what to tell the run when it improves."""

    def __init__(self, model: Model, on_progress, began: float):
        self.model, self.on_progress, self.began = model, on_progress, began
        self.x, self.goal, self.breach, self.generations = None, math.inf, math.inf, 0

    def offer(self, X: np.ndarray, goal: np.ndarray, breach: np.ndarray) -> None:
        i = int(self.model.rank(goal, breach)[0])
        kept, was_kept = breach[i] <= TOLERANCE, self.breach <= TOLERANCE
        if (kept and (not was_kept or goal[i] < self.goal)) or (not kept and not was_kept and breach[i] < self.breach):
            self.x, self.goal, self.breach = X[i].copy(), float(goal[i]), float(breach[i])
            if kept:
                report(self.on_progress, "incumbent", time.monotonic() - self.began, self.model.sign * self.goal, None)


def _cma_es(model: Model, best: _Best, rng, deadline: float, stop: Callable[[], bool], x0) -> None:
    """(mu/mu_w, lambda)-CMA-ES in the unit box, full covariance up to 200 decisions and diagonal past it,
    restarted with twice the population whenever it settles (IPOP)."""
    n = model.n
    lam = 4 + int(3 * math.log(max(n, 1)))
    first = True
    while time.monotonic() < deadline and not stop():
        mean = model.unit(x0) if (first and x0 is not None) else rng.random(n)
        first = False
        mu = lam // 2
        w = np.log(mu + 0.5) - np.log(np.arange(1, mu + 1))
        w /= w.sum()
        mueff = 1.0 / (w ** 2).sum()
        cc, cs = (4 + mueff / n) / (n + 4 + 2 * mueff / n), (mueff + 2) / (n + mueff + 5)
        c1 = 2 / ((n + 1.3) ** 2 + mueff)
        cmu = min(1 - c1, 2 * (mueff - 2 + 1 / mueff) / ((n + 2) ** 2 + mueff))
        damps = 1 + 2 * max(0.0, math.sqrt((mueff - 1) / (n + 1)) - 1) + cs
        chi = math.sqrt(n) * (1 - 1 / (4 * n) + 1 / (21 * n * n))
        full = n <= 200
        sigma, pc, ps = 0.3, np.zeros(n), np.zeros(n)
        C = np.eye(n) if full else None
        d = np.ones(n)
        B, D = np.eye(n) if full else None, np.ones(n)
        since, settled = 0, False
        # The decomposition of C only every so often (Hansen's lazy update): at
        # 200 decisions one costs more than the generation's whole search.
        every, fresh = max(1, int(lam / ((c1 + cmu) * n * 10))), 0
        invsqrt = np.eye(n) if full else None
        while time.monotonic() < deadline and not stop() and not settled:
            Z = rng.standard_normal((lam, n))
            Y = (Z * D) @ B.T if full else Z * np.sqrt(d)
            U = mean + sigma * Y
            goal, breach = model.evaluate(model.box(U))
            best.offer(model.box(U), goal, breach)
            best.generations += 1
            order = model.rank(goal, breach)[:mu]
            yw = w @ Y[order]
            mean = mean + sigma * yw
            if full:
                ps = (1 - cs) * ps + math.sqrt(cs * (2 - cs) * mueff) * (invsqrt @ yw)
            else:
                ps = (1 - cs) * ps + math.sqrt(cs * (2 - cs) * mueff) * (yw / np.sqrt(d))
            hsig = np.linalg.norm(ps) / math.sqrt(1 - (1 - cs) ** (2 * (best.generations + 1))) / chi < 1.4 + 2 / (n + 1)
            pc = (1 - cc) * pc + hsig * math.sqrt(cc * (2 - cc) * mueff) * yw
            if full:
                C = ((1 - c1 - cmu) * C + c1 * (np.outer(pc, pc) + (1 - hsig) * cc * (2 - cc) * C)
                     + cmu * (Y[order].T * w) @ Y[order])
                fresh += 1
                if fresh >= every:
                    fresh = 0
                    C = np.triu(C) + np.triu(C, 1).T
                    D2, B = np.linalg.eigh(C)
                    D = np.sqrt(np.maximum(D2, 1e-20))
                    invsqrt = (B / D) @ B.T
            else:
                d = (1 - c1 - cmu) * d + c1 * pc ** 2 + cmu * (w @ Y[order] ** 2)
            sigma *= math.exp((cs / damps) * (np.linalg.norm(ps) / chi - 1))
            since += 1
            spread = sigma * (D.max() if full else math.sqrt(d.max()))
            settled = spread < 1e-9 or sigma > 1e3 or since > 100 + 50 * (n + 3) ** 2 / math.sqrt(lam)
        lam *= 2


def _swarm(model: Model, best: _Best, rng, deadline: float, stop: Callable[[], bool], x0) -> None:
    """Particle swarm in the unit box: inertia 0.72, pulls 1.49 each (Clerc's constriction)."""
    n, size = model.n, 40
    P = rng.random((size, n))
    if x0 is not None:
        P[0] = model.unit(x0)
    V = (rng.random((size, n)) - 0.5) * 0.2
    goal, breach = model.evaluate(model.box(P))
    own, own_goal, own_breach = P.copy(), goal.copy(), breach.copy()
    best.offer(model.box(P), goal, breach)
    while time.monotonic() < deadline and not stop():
        lead = own[int(model.rank(own_goal, own_breach)[0])]
        V = 0.72 * V + 1.49 * rng.random((size, n)) * (own - P) + 1.49 * rng.random((size, n)) * (lead - P)
        V = np.clip(V, -0.25, 0.25)
        P = np.clip(P + V, 0.0, 1.0)
        goal, breach = model.evaluate(model.box(P))
        best.offer(model.box(P), goal, breach)
        best.generations += 1
        for i in range(size):
            pair_goal, pair_breach = np.array([goal[i], own_goal[i]]), np.array([breach[i], own_breach[i]])
            if model.rank(pair_goal, pair_breach)[0] == 0:
                own[i], own_goal[i], own_breach[i] = P[i], goal[i], breach[i]


def _genetic(model: Model, best: _Best, rng, deadline: float, stop: Callable[[], bool], x0) -> None:
    """Tournaments of two, uniform crossover, per-gene mutation in the box; the best two carried over.
    Seeded with the start (if any), every decision at its lower bound, at its upper, and at random."""
    n, size = model.n, 60
    span = model.upper - model.lower
    P = model.lower + rng.random((size, n)) * span
    P[1], P[2] = model.lower, model.upper
    if x0 is not None:
        P[0] = x0
    P = np.where(model.integral, np.rint(P), P)
    goal, breach = model.evaluate(P)
    best.offer(P, goal, breach)
    rate = max(1.0, 0.01 * n) / n
    while time.monotonic() < deadline and not stop():
        order = model.rank(goal, breach)
        place = np.empty(size, dtype=np.int64)
        place[order] = np.arange(size)
        a, b = rng.integers(0, size, (2, size - 2))
        mothers = np.where(place[a] < place[b], a, b)
        a, b = rng.integers(0, size, (2, size - 2))
        fathers = np.where(place[a] < place[b], a, b)
        children = np.where(rng.random((size - 2, n)) < 0.5, P[mothers], P[fathers])
        flip = rng.random((size - 2, n)) < rate
        jump = np.where(rng.random((size - 2, n)) < 0.2, model.lower + rng.random((size - 2, n)) * span,
                        children + rng.standard_normal((size - 2, n)) * np.maximum(span * 0.1, model.integral))
        children = np.clip(np.where(flip, jump, children), model.lower, model.upper)
        children = np.where(model.integral, np.rint(children), children)
        child_goal, child_breach = model.evaluate(children)
        best.offer(children, child_goal, child_breach)
        best.generations += 1
        keep = order[:2]
        P = np.concatenate([P[keep], children])
        goal = np.concatenate([goal[keep], child_goal])
        breach = np.concatenate([breach[keep], child_breach])


def _penalised(model: Model, goal: np.ndarray, breach: np.ndarray, weight: float) -> np.ndarray:
    """One number per answer for a single-answer search: the goal plus `weight` per unit of breach."""
    return np.where(np.isfinite(goal), goal, 1e300) + weight * breach


def _neighbours(model: Model, x: np.ndarray, count: int, rng, scale: float, moves: int = 1) -> np.ndarray:
    """`count` answers near `x`: `moves` decisions each changed -- a yes/no flipped, a whole number stepped or
    redrawn, a continuous one moved by a Gaussian step of `scale` times its range."""
    span = model.upper - model.lower
    X = np.repeat(x[None, :], count, axis=0)
    for _ in range(moves):
        which = rng.integers(0, model.n, count)
        rows = np.arange(count)
        lo, hi, cur = model.lower[which], model.upper[which], X[rows, which]
        whole = model.integral[which]
        binary = whole & (lo == 0) & (hi == 1)
        step = np.where(rng.random(count) < 0.5, -1.0, 1.0) * np.maximum(1.0, np.rint(np.abs(
            rng.standard_normal(count)) * scale * (hi - lo)))
        redraw = lo + rng.random(count) * (hi - lo)
        moved = np.where(binary, 1.0 - cur,
                         np.where(whole, np.where(rng.random(count) < 0.2, np.rint(redraw), cur + step),
                                  cur + rng.standard_normal(count) * scale * np.maximum(span[which], 1e-12)))
        X[rows, which] = np.clip(moved, lo, hi)
    return np.where(model.integral, np.rint(X), X)


def _annealing(model: Model, best: _Best, rng, deadline: float, stop: Callable[[], bool], x0) -> None:
    """Simulated annealing (Kirkpatrick et al.) on the goal plus a breach penalty whose weight grows while the
    current answer breaks rules: batches of neighbours, Metropolis acceptance, geometric cooling, and a reheat
    from the best answer when nothing has been accepted for a while."""
    x = x0.copy() if x0 is not None else model.lower + rng.random(model.n) * (model.upper - model.lower)
    x = np.where(model.integral, np.rint(np.clip(x, model.lower, model.upper)), np.clip(x, model.lower, model.upper))
    goal, breach = model.evaluate(x[None, :])
    best.offer(x[None, :], goal, breach)
    weight = max(1.0, abs(float(goal[0])) if np.isfinite(goal[0]) else 1.0)
    current = float(_penalised(model, goal, breach, weight)[0])
    temperature = max(1e-6, 0.1 * abs(current) if np.isfinite(current) else 1.0)
    first, idle, scale = temperature, 0, 0.1
    while time.monotonic() < deadline and not stop():
        X = _neighbours(model, x, 32, rng, scale, moves=1 + int(rng.random() < 0.3))
        goal, breach = model.evaluate(X)
        best.offer(X, goal, breach)
        best.generations += 1
        cost = _penalised(model, goal, breach, weight)
        accepted = False
        for i in np.argsort(cost):
            delta = cost[i] - current
            if delta <= 0 or rng.random() < math.exp(-delta / max(temperature, 1e-12)):
                x, current, accepted = X[i].copy(), float(cost[i]), True
                if breach[i] > TOLERANCE:
                    weight *= 1.05  # a breaking answer accepted: rules weigh more from now on
                break
        idle = 0 if accepted else idle + 1
        temperature *= 0.995
        scale = max(0.01, scale * 0.999)
        if idle > 200 or temperature < first * 1e-6:
            # Reheat from the best answer found.
            if best.x is not None:
                x = best.x.copy()
                g, b = model.evaluate(x[None, :])
                current = float(_penalised(model, g, b, weight)[0])
            temperature, idle, scale = first * 0.5, 0, 0.1


def _tabu(model: Model, best: _Best, rng, deadline: float, stop: Callable[[], bool], x0) -> None:
    """Tabu search (Glover): each step the best of a sample of one-decision moves that is not tabu -- a decision
    changed is tabu for a tenure -- unless it beats the best answer found (aspiration); answers compared by
    Deb's order. Restarted from the best, perturbed, after long stagnation."""
    n = model.n
    x = x0.copy() if x0 is not None else model.lower + rng.random(n) * (model.upper - model.lower)
    x = np.where(model.integral, np.rint(np.clip(x, model.lower, model.upper)), np.clip(x, model.lower, model.upper))
    goal, breach = model.evaluate(x[None, :])
    best.offer(x[None, :], goal, breach)
    tabu_until = np.zeros(n, dtype=np.int64)
    tenure = max(5, int(math.sqrt(n)))
    step, stagnant = 0, 0
    sample = min(64, max(8, n))
    while time.monotonic() < deadline and not stop():
        step += 1
        which = rng.choice(n, size=sample, replace=n < sample)
        X = np.repeat(x[None, :], sample, axis=0)
        for r, j in enumerate(which):
            X[r] = _neighbours_one(model, x, j, rng)
        goal, breach = model.evaluate(X)
        best_before = (best.goal, best.breach)
        best.offer(X, goal, breach)
        best.generations += 1
        order = model.rank(goal, breach)
        chosen = None
        for i in order:
            j = which[i]
            aspires = (breach[i] <= TOLERANCE and (best_before[1] > TOLERANCE or goal[i] < best_before[0]))
            if tabu_until[j] <= step or aspires:
                chosen = i
                break
        if chosen is None:
            chosen = order[0]
        x = X[chosen].copy()
        tabu_until[which[chosen]] = step + tenure + int(rng.integers(0, tenure + 1))
        stagnant = 0 if (best.goal, best.breach) != best_before else stagnant + 1
        if stagnant > 50 * tenure and best.x is not None:
            x = _neighbours(model, best.x, 1, rng, 0.2, moves=max(2, n // 20))[0]
            stagnant = 0


def _neighbours_one(model: Model, x: np.ndarray, j: int, rng) -> np.ndarray:
    y = x.copy()
    lo, hi = model.lower[j], model.upper[j]
    if model.integral[j]:
        if lo == 0 and hi == 1:
            y[j] = 1.0 - y[j]
        else:
            y[j] = np.clip(y[j] + (1 if rng.random() < 0.5 else -1) * max(1.0, np.rint(abs(rng.standard_normal())
                                                                                      * 0.1 * (hi - lo))), lo, hi)
    else:
        y[j] = np.clip(y[j] + rng.standard_normal() * 0.1 * max(hi - lo, 1e-12), lo, hi)
    return y


def _differential(model: Model, best: _Best, rng, deadline: float, stop: Callable[[], bool], x0) -> None:
    """Differential evolution, JADE's current-to-pbest/1 with an archive and self-adapting F and CR (Zhang and
    Sanderson), in the unit box; whole numbers rounded when evaluated. Selection by Deb's order."""
    n = model.n
    size = max(20, min(100, 10 * n))
    P = rng.random((size, n))
    if x0 is not None:
        P[0] = model.unit(x0)
    goal, breach = model.evaluate(model.box(P))
    best.offer(model.box(P), goal, breach)
    mu_f, mu_cr, archive = 0.5, 0.5, []
    while time.monotonic() < deadline and not stop():
        order = model.rank(goal, breach)
        top = order[: max(2, size // 10)]
        F = np.clip(mu_f + 0.1 * rng.standard_cauchy(size), 0.05, 1.0)
        CR = np.clip(rng.normal(mu_cr, 0.1, size), 0.0, 1.0)
        pbest = P[rng.choice(top, size)]
        r1 = rng.integers(0, size, size)
        pool = np.concatenate([P, np.array(archive)]) if archive else P
        r2 = rng.integers(0, len(pool), size)
        V = P + F[:, None] * (pbest - P) + F[:, None] * (P[r1] - pool[r2])
        cross = rng.random((size, n)) < CR[:, None]
        cross[np.arange(size), rng.integers(0, n, size)] = True
        U = np.clip(np.where(cross, V, P), 0.0, 1.0)
        ug, ub = model.evaluate(model.box(U))
        best.offer(model.box(U), ug, ub)
        best.generations += 1
        good_f, good_cr = [], []
        for i in range(size):
            if model.rank(np.array([ug[i], goal[i]]), np.array([ub[i], breach[i]]))[0] == 0:
                archive.append(P[i].copy())
                P[i], goal[i], breach[i] = U[i], ug[i], ub[i]
                good_f.append(F[i])
                good_cr.append(CR[i])
        if len(archive) > size:
            archive = [archive[k] for k in rng.choice(len(archive), size, replace=False)]
        if good_f:
            f = np.array(good_f)
            mu_f = 0.9 * mu_f + 0.1 * float((f ** 2).sum() / f.sum())
            mu_cr = 0.9 * mu_cr + 0.1 * float(np.mean(good_cr))


def _ants(model: Model, best: _Best, rng, deadline: float, stop: Callable[[], bool], x0) -> None:
    """Ant colony optimisation for mixed decisions (ACO_R / ACO_MV, Socha and Dorigo; Liao et al.): an archive of
    the best answers is the pheromone; each ant draws every continuous decision from a Gaussian kernel around a
    member chosen by rank weight, and every whole-number one from the archive's values, weighted the same way."""
    n, k, ants, q, xi = model.n, 30, 30, 0.1, 0.85
    A = rng.random((k, n))
    if x0 is not None:
        A[0] = model.unit(x0)
    goal, breach = model.evaluate(model.box(A))
    best.offer(model.box(A), goal, breach)
    weights = np.exp(-((np.arange(k)) ** 2) / (2 * (q * k) ** 2))
    weights /= weights.sum()
    whole = model.integral
    while time.monotonic() < deadline and not stop():
        order = model.rank(goal, breach)
        A, goal, breach = A[order], goal[order], breach[order]
        guide = rng.choice(k, size=ants, p=weights)
        spread = xi * np.abs(A[None, :, :] - A[guide][:, None, :]).sum(axis=1) / (k - 1)
        S = A[guide] + rng.standard_normal((ants, n)) * spread
        # Whole numbers: a value taken from the archive, member drawn by weight, per decision.
        pick = rng.choice(k, size=(ants, n), p=weights)
        S = np.where(whole, A[pick, np.arange(n)[None, :]], S)
        # Evaporation for whole numbers: now and then a value from anywhere in the range, so the archive's
        # values do not close the search on themselves.
        fresh = whole & (rng.random((ants, n)) < max(0.02, 1.0 / max(1, n)))
        S = np.where(fresh, rng.random((ants, n)), S)
        S = np.clip(S, 0.0, 1.0)
        sg, sb = model.evaluate(model.box(S))
        best.offer(model.box(S), sg, sb)
        best.generations += 1
        A = np.concatenate([A, S])
        goal, breach = np.concatenate([goal, sg]), np.concatenate([breach, sb])
        keep = model.rank(goal, breach)[:k]
        A, goal, breach = A[keep], goal[keep], breach[keep]


METHODS = {"cma-es": (_cma_es, True), "pso": (_swarm, True), "ga": (_genetic, False),
           "sa": (_annealing, False), "tabu": (_tabu, False), "de": (_differential, False), "aco": (_ants, False)}


def _blas_threads(count: int) -> None:
    """numpy's bundled OpenBLAS starts a spinning thread per core (20 here), which ran a 60 s search past the
    sandbox's CPU allowance (queue R14's bench). The sandbox's forkserver has numpy loaded already, so the
    environment variable is too late: the library is told directly."""
    import ctypes
    import glob
    import os

    libs = os.path.join(os.path.dirname(os.path.dirname(np.__file__)), "numpy.libs")
    for path in glob.glob(os.path.join(libs, "libscipy_openblas*.so")):
        try:
            library = ctypes.CDLL(path)
            for name in ("scipy_openblas_set_num_threads64_", "openblas_set_num_threads64_", "openblas_set_num_threads"):
                setter = getattr(library, name, None)
                if setter is not None:
                    setter(int(count))
                    return
        except OSError:  # pragma: no cover -- another build of numpy: its own default stands
            return


def solve(compiled: Compiled, *, method: str, time_limit: float = 10.0, workers: int = 1, should_stop=None,
          seed: int | None = None, gap_rel: float = 0.0, on_progress=None, hint: dict | None = None,
          solver_params: dict | None = None) -> Solution:
    search, continuous_only = METHODS[method]
    began = time.monotonic()
    # The searches are single-threaded, and a small matrix gains nothing from more.
    _blas_threads(1)
    model = Model(compiled, continuous_only=continuous_only)
    rng = np.random.default_rng(seed)
    best = _Best(model, on_progress, began)
    stop = should_stop or (lambda: False)
    if model.n:
        search(model, best, rng, began + max(0.1, float(time_limit)), stop, model.starting(hint))
    wall = round(time.monotonic() - began, 3)
    if best.x is None or best.breach > TOLERANCE:
        return Solution("unknown", False, None, {}, wall, method)
    assignments = model.answer(best.x)
    if not holds(compiled, assignments):
        return Solution("unknown", False, None, {}, wall, method)
    objective = objective_at(compiled, assignments)
    return Solution("feasible", False, objective, assignments, wall, method)


def objective_at(compiled: Compiled, values: dict) -> float | int:
    value = float(compiled.objective.evaluated_at(values)) + sum(
        float(c) * float(values.get(a, 0)) * float(values.get(b, 0)) for (a, b), c in compiled.objective_quadratic.items())
    return int(value) if value == int(value) and all(v.is_integral for v in compiled.variables.values()) else value


def holds(compiled: Compiled, values: dict[VarKey, Any]) -> bool:
    """Every compiled row, its quadratic part, each function and each bound, at `values`: the answer's own check."""
    for key, var in compiled.variables.items():
        x = float(values.get(key, 0))
        if x < float(var.lower) - TOLERANCE * max(1.0, abs(float(var.lower))) or \
                x > float(var.upper) + TOLERANCE * max(1.0, abs(float(var.upper))):
            return False
        if var.is_integral and abs(x - round(x)) > 1e-9:
            return False
    for c in compiled.constraints:
        gap = float(c.left.evaluated_at(values)) - float(c.right.evaluated_at(values)) + sum(
            float(v) * float(values.get(a, 0)) * float(values.get(b, 0)) for (a, b), v in (c.quadratic or {}).items())
        slack = TOLERANCE * max(1.0, abs(float(c.right.const) - float(c.left.const)))
        if not {"<=": gap <= slack, ">=": gap >= -slack}.get(c.relation, abs(gap) <= slack):
            return False
    return all(abs(float(values.get(f.y, 0)) - f.value_at(values)) <= 1e-7 * max(1.0, abs(f.value_at(values)))
               for f in compiled.functions)


# --- NSGA-II: a trade-off front by search (9 October 2026) ---------------------------------------------------


def _fronts(F: np.ndarray, breach: np.ndarray) -> list[np.ndarray]:
    """Non-dominated sorting with Deb's constraint domination: an answer that keeps every rule dominates one that
    does not; two that do not, by breach; two that do, by Pareto dominance on the goals (all minimised)."""
    n = len(F)
    kept = breach <= TOLERANCE
    dominated_by = [[] for _ in range(n)]
    count = np.zeros(n, dtype=np.int64)
    for i in range(n):
        for j in range(i + 1, n):
            if kept[i] and kept[j]:
                a = np.all(F[i] <= F[j]) and np.any(F[i] < F[j])
                b = np.all(F[j] <= F[i]) and np.any(F[j] < F[i])
            elif kept[i] != kept[j]:
                a, b = bool(kept[i]), bool(kept[j])
            else:
                a, b = breach[i] < breach[j], breach[j] < breach[i]
            if a:
                dominated_by[i].append(j)
                count[j] += 1
            elif b:
                dominated_by[j].append(i)
                count[i] += 1
    fronts, current = [], np.nonzero(count == 0)[0]
    while len(current):
        fronts.append(current)
        following = []
        for i in current:
            for j in dominated_by[i]:
                count[j] -= 1
                if count[j] == 0:
                    following.append(j)
        current = np.array(following, dtype=np.int64)
    return fronts


def _crowding(F: np.ndarray) -> np.ndarray:
    n, m = F.shape
    distance = np.zeros(n)
    if n <= 2:
        return np.full(n, np.inf)
    for k in range(m):
        order = np.argsort(F[:, k])
        spread = F[order[-1], k] - F[order[0], k]
        distance[order[0]] = distance[order[-1]] = np.inf
        if spread > 0:
            distance[order[1:-1]] += (F[order[2:], k] - F[order[:-2], k]) / spread
    return distance


def nsga2(compiled: Compiled, *, time_limit: float, seed: int | None = None, size: int = 80,
          should_stop: Callable[[], bool] | None = None) -> list[tuple[dict, list[float]]]:
    """The front between the goal's terms by NSGA-II (Deb et al. 2002): SBX crossover and polynomial mutation in
    the unit box, whole numbers rounded, Deb's constraint domination, crowding distance. Returns each answer of
    the final front that keeps every rule, with its terms' values (as the terms read, not minimised)."""
    from app.solve.compile import directed_terms

    began = time.monotonic()
    _blas_threads(1)
    model = Model(compiled, continuous_only=False)
    rng = np.random.default_rng(seed)
    stop = should_stop or (lambda: False)
    position = {k: i for i, k in enumerate(model.all_keys)}
    sense = 1.0 if compiled.sense == "minimize" else -1.0
    terms = directed_terms(compiled)
    quads = list(getattr(compiled, "objective_term_quadratics", []) or [])
    weights = compiled.objective_term_weights
    vectors = [(_dense(t.coeffs, position), float(t.const),
                _pairs(quads[i], position) if i < len(quads) and quads[i] else None,
                -1.0 if (len(weights) == len(terms) and weights[i] < 0) else 1.0) for i, t in enumerate(terms)]

    def goals(X: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        _, breach = model.evaluate(X)
        Xr = model.full(np.where(model.integral, np.rint(X), X))
        F = np.stack([sense * (Xr @ v + c + (turn * _quadratic(Xr, p) if p is not None else 0.0))
                      for v, c, p, turn in vectors], axis=1)
        F[~np.isfinite(F).all(axis=1)] = np.inf
        return F, breach

    n = model.n
    P = rng.random((size, n))
    F, breach = goals(model.box(P))
    eta_c, eta_m = 15.0, 20.0
    while time.monotonic() - began < time_limit and not stop() and n:
        # Parents by binary tournament on (front rank, crowding).
        rank = np.empty(size, dtype=np.int64)
        crowd = np.empty(size)
        for r, front in enumerate(_fronts(F, breach)):
            rank[front] = r
            crowd[front] = _crowding(F[front])
        a, b = rng.integers(0, size, (2, size))
        better = (rank[a] < rank[b]) | ((rank[a] == rank[b]) & (crowd[a] > crowd[b]))
        parents = P[np.where(better, a, b)]
        # SBX crossover between consecutive parents.
        u = rng.random((size // 2, n))
        beta = np.where(u <= 0.5, (2 * u) ** (1 / (eta_c + 1)), (1 / (2 * (1 - u))) ** (1 / (eta_c + 1)))
        x1, x2 = parents[0::2][: size // 2], parents[1::2][: size // 2]
        swap = rng.random((size // 2, n)) < 0.5
        c1 = 0.5 * ((1 + beta) * x1 + (1 - beta) * x2)
        c2 = 0.5 * ((1 - beta) * x1 + (1 + beta) * x2)
        children = np.concatenate([np.where(swap, c1, x1), np.where(swap, c2, x2)])
        # Polynomial mutation.
        mutate = rng.random(children.shape) < 1.0 / max(1, n)
        u = rng.random(children.shape)
        delta = np.where(u < 0.5, (2 * u) ** (1 / (eta_m + 1)) - 1, 1 - (2 * (1 - u)) ** (1 / (eta_m + 1)))
        children = np.clip(np.where(mutate, children + delta, children), 0.0, 1.0)
        CF, cb = goals(model.box(children))
        # Environmental selection: the best `size` by front, then crowding.
        allP, allF, allb = np.concatenate([P, children]), np.concatenate([F, CF]), np.concatenate([breach, cb])
        chosen: list[int] = []
        for front in _fronts(allF, allb):
            if len(chosen) + len(front) <= size:
                chosen.extend(front.tolist())
            else:
                order = front[np.argsort(-_crowding(allF[front]))]
                chosen.extend(order[: size - len(chosen)].tolist())
                break
        P, F, breach = allP[chosen], allF[chosen], allb[chosen]
    out = []
    first = _fronts(F, breach)[0] if n else np.array([], dtype=np.int64)
    seen = set()
    for i in first:
        if breach[i] > TOLERANCE:
            continue
        values = model.answer(model.box(P[i:i + 1])[0])
        if not holds(compiled, values):
            continue
        key = tuple(np.round(F[i], 9))
        if key in seen:
            continue
        seen.add(key)
        # As the terms read (not turned, not minimised): what the exact front reports too.
        out.append((values, [float(turn * sense * f) for f, (_v, _c, _p, turn) in zip(F[i], vectors)]))
    return out
