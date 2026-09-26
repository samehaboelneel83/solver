"""Run the benchmark: every instance, every backend that takes it, every seed.

    python -m bench.run --family rota,facility --sizes S,M --seeds 3 \
        --technique gap_rel=0,0.01 --time-limit 30 --out results.json

One JSON row per (instance, backend, technique value, seed):

    {family, size, instance, backend, technique, value, seed, status,
     objective, bound, gap, compile_s, solve_s, sense, wrong, primal_integral}

**Techniques are solve settings.** `--technique name=v1,v2` runs every value
of one `solve_compiled` knob (`gap_rel`, `workers`) so the report can compare
them; the first value is the baseline. `backend.option=v1,v2` measures a
whitelisted solver option (`app.solve.params`) on that backend alone, its
default first. `cpsat_scaling=0,1` is a routing
setting instead: for each value it runs only the backend `choose` picks with
the setting so (migration 0039), as a run would, and labels the rows
`routed` with the backend in `solver` -- the comparison is of the two
decisions, on the same instances. A technique that is not a knob yet
cannot be benchmarked here, which is the point: it is not wired in either.

**`wrong` is disagreement, not a guess.** Two backends that both claim a
proven optimum on the same instance must agree on its value to 1e-6
relative, and on infeasibility. Any row that disagrees with the majority of
proven answers on its instance is marked wrong. The roadmap's rule -- zero
wrong answers before anything is enabled by default -- reads this column.

**`primal_integral`** is how long the run spent without a good answer
(`bench.primal`): the area under the primal gap of its best answer so far,
from the incumbents the backend streams as it solves plus the one it ended
with. A backend that streams nothing is charged until it finishes.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from bench.families import FAMILIES, SIZES, Instance, generate
from bench.primal import mark_primal_integral

# Imported lazily in `run`: `app.solve` loads the solvers, and a bad import
# should fail the run with a message rather than the argument parser.

PROVEN = ("optimal", "infeasible", "unbounded")
TOLERANCE = 1e-6


@dataclass
class Technique:
    name: str | None
    values: list[Any]


def parse_technique(text: str | None) -> Technique:
    if not text:
        return Technique(None, [None])
    name, _, values = text.partition("=")
    if "." in name:
        # A whitelisted solver option, `backend.option` (app.solve.params):
        # the first value is the solver's default, the baseline.
        from app.solve.params import WHITELIST, parse

        backend, option = name.split(".", 1)
        if option not in WHITELIST.get(backend, {}):
            raise SystemExit(f"{name!r} is not a whitelisted solver option; see app.solve.params")
        try:
            return Technique(name, [parse(backend, option, v) for v in values.split(",") if v])
        except ValueError as exc:
            raise SystemExit(str(exc)) from None
    if name not in ("gap_rel", "workers", "cpsat_scaling"):
        raise SystemExit(
            f"--technique takes gap_rel, workers, cpsat_scaling or backend.option, not {name!r}"
        )
    cast = float if name == "gap_rel" else int
    return Technique(name, [cast(v) for v in values.split(",") if v])


def instances(families: Iterable[str], sizes: Iterable[str], count: int) -> Iterable[Instance]:
    for family in families:
        for size in sizes:
            for n in range(count):
                yield generate(family, size, n)


def _generated(families: list[str], sizes: list[str], count: int):
    from app.solve import compile_model
    from app.solve.classify import classify
    from app.solve.convexity import refine

    for inst in instances(families, sizes, count):
        started = time.monotonic()
        compiled = compile_model(inst.ir, inst.data)
        compile_s = time.monotonic() - started
        found = refine(classify(inst.ir, inst.data), compiled)
        yield inst.family, inst.size, inst.name, compiled, found, compile_s, None


def _mps(directory: str):
    from bench.mps import MPS_BACKENDS, classify_compiled, read

    for path in sorted(Path(directory).glob("*.mps*")):
        started = time.monotonic()
        compiled = read(path)
        compile_s = time.monotonic() - started
        name = path.name.split(".mps")[0]
        yield "miplib", "-", name, compiled, classify_compiled(compiled), compile_s, MPS_BACKENDS


def run(
    families: list[str],
    sizes: list[str],
    *,
    count: int = 1,
    seeds: int = 1,
    technique: Technique | None = None,
    backends: list[str] | None = None,
    time_limit: float = 30.0,
    workers: int = 8,
    mps_dir: str | None = None,
) -> list[dict[str, Any]]:
    from app.solve.backends import REGISTRY, SEARCHES, NoBackend, choose, is_automatic
    from app.solve.service import gap_of, solve_compiled

    technique = technique or Technique(None, [None])
    source = _mps(mps_dir) if mps_dir else _generated(families, sizes, count)
    rows: list[dict[str, Any]] = []
    for family, size, name, compiled, found, compile_s, only in source:
        if technique.name == "cpsat_scaling":
            rows += _routed(
                family, size, name, compiled, found, compile_s, technique, seeds, time_limit, workers
            )
            continue
        option_of = technique.name.split(".", 1) if technique.name and "." in technique.name else None
        for backend in REGISTRY:
            if backends and backend.name not in backends:
                continue
            if not backends and not is_automatic(backend):
                continue  # an added solver is benched only when named
            if option_of is not None and backend.name != option_of[0]:
                # A solver option is measured on its own solver only.
                continue
            if only is not None and backend.name not in only:
                continue
            if not backend.is_available():
                continue
            if backend.name in SEARCHES and backend.name not in (backends or ()):
                # A search proves nothing, so it cannot "agree": measured only when named (bench.evolve).
                continue
            try:
                choose(found, backend.name)
            except NoBackend:
                continue
            for value in technique.values:
                knobs: dict[str, Any] = {"workers": workers}
                if option_of is not None:
                    knobs["solver_params"] = {option_of[1]: value}
                elif technique.name:
                    knobs[technique.name] = value
                for seed in range(1, seeds + 1):
                    incumbents: list[tuple[float, float]] = []

                    def heard(kind: str, payload: dict, found=incumbents) -> None:
                        if kind == "incumbent" and payload.get("objective") is not None:
                            found.append((payload["t"], payload["objective"]))

                    started = time.monotonic()
                    result, _ = solve_compiled(
                        backend, compiled, time_limit=time_limit, seed=seed, on_progress=heard, **knobs
                    )
                    solve_s = round(time.monotonic() - started, 4)
                    if result.objective is not None and result.status in ("optimal", "feasible"):
                        # The answer it ended with, at the moment it ended.
                        incumbents.append((solve_s, float(result.objective)))
                    rows.append(
                        {
                            "family": family,
                            "size": size,
                            "instance": name,
                            "class": found.model_class,
                            "backend": backend.name,
                            "technique": technique.name,
                            "value": value,
                            "seed": seed,
                            "status": result.status,
                            "objective": None if result.objective is None else float(result.objective),
                            "bound": result.best_bound,
                            "gap": gap_of(result.objective, result.best_bound),
                            "compile_s": round(compile_s, 4),
                            "solve_s": solve_s,
                            "time_limit": time_limit,
                            "sense": getattr(compiled, "sense", "minimize"),
                            "incumbents": incumbents,
                        }
                    )
    mark_wrong(rows)
    if mps_dir:
        from bench.mps import known_optima

        mark_against_known(rows, known_optima(mps_dir))
    mark_primal_integral(rows)
    return rows


def mark_against_known(rows: list[dict[str, Any]], known: dict[str, float | str]) -> None:
    """Also wrong: a proven answer that contradicts the published one, or an
    unproven one better than a published optimum.

    The backends agreeing with each other is not proof -- two can share a
    reading of the file that drops an objective constant. Each row records
    the published answer as `known`."""
    for row in rows:
        answer = known.get(row["instance"])
        row["known"] = answer
        if answer is None:
            continue
        if row["status"] == "feasible" and row["objective"] is not None and answer != "infeasible":
            # Unproven, but no answer can beat a proven optimum: one that
            # does means the model was read or solved wrong.
            beyond = TOLERANCE * max(1.0, abs(answer))
            better = (
                row["objective"] > answer + beyond
                if row.get("sense") == "maximize"
                else row["objective"] < answer - beyond
            )
            if better:
                row["wrong"] = True
            continue
        if row["status"] not in PROVEN:
            continue
        if answer == "infeasible":
            contradicts = row["status"] != "infeasible"
        elif row["status"] != "optimal" or row["objective"] is None:
            contradicts = True
        else:
            contradicts = abs(row["objective"] - answer) > TOLERANCE * max(1.0, abs(answer))
        if contradicts:
            row["wrong"] = True


def _routed(family, size, name, compiled, found, compile_s, technique, seeds, time_limit, workers):
    """One row per (value, seed): the backend a run would get, and its answer."""
    from app.solve.backends import NoBackend, choose
    from app.solve.scaling import admit

    rows = []
    for value in technique.values:
        considered = admit(found, compiled) if value else found
        try:
            backend, _ = choose(considered)
        except NoBackend:
            continue
        for seed in range(1, seeds + 1):
            rows.append(
                _solve_row(family, size, name, compiled, found, compile_s, backend,
                           "cpsat_scaling", value, seed, time_limit, {"workers": workers}, label="routed")
            )
    return rows


def _solve_row(family, size, name, compiled, found, compile_s, backend, technique, value, seed,
               time_limit, knobs, *, label=None):
    from app.solve.service import gap_of, solve_compiled

    incumbents: list[tuple[float, float]] = []

    def heard(kind: str, payload: dict) -> None:
        if kind == "incumbent" and payload.get("objective") is not None:
            incumbents.append((payload["t"], payload["objective"]))

    started = time.monotonic()
    result, _ = solve_compiled(
        backend, compiled, time_limit=time_limit, seed=seed, on_progress=heard, **knobs
    )
    solve_s = round(time.monotonic() - started, 4)
    if result.objective is not None and result.status in ("optimal", "feasible"):
        incumbents.append((solve_s, float(result.objective)))
    return {
        "family": family,
        "size": size,
        "instance": name,
        "class": found.model_class,
        "backend": label or backend.name,
        "solver": backend.name,
        "technique": technique,
        "value": value,
        "seed": seed,
        "status": result.status,
        "objective": None if result.objective is None else float(result.objective),
        "bound": result.best_bound,
        "gap": gap_of(result.objective, result.best_bound),
        "compile_s": round(compile_s, 4),
        "solve_s": solve_s,
        "time_limit": time_limit,
        "sense": getattr(compiled, "sense", "minimize"),
        "incumbents": incumbents,
    }


def mark_wrong(rows: list[dict[str, Any]]) -> None:
    """Set `wrong` on each row: does it contradict the proven answers on its
    instance? The reference is the most common proven outcome -- a status,
    and for `optimal` a value rounded to the tolerance."""
    by_instance: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_instance[row["instance"]].append(row)
    for group in by_instance.values():
        proven = [_outcome(row) for row in group if row["status"] in PROVEN]
        reference = Counter(proven).most_common(1)[0][0] if proven else None
        for row in group:
            row["wrong"] = bool(
                reference is not None
                and row["status"] in PROVEN
                and not _agrees(row, reference)
            )


def _outcome(row: dict[str, Any]) -> tuple[str, float | None]:
    value = row["objective"]
    if row["status"] != "optimal" or value is None:
        return row["status"], None
    scale = max(1.0, abs(value))
    return "optimal", round(value / scale / TOLERANCE) * TOLERANCE * scale


def _agrees(row: dict[str, Any], reference: tuple[str, float | None]) -> bool:
    status, value = reference
    if row["status"] != status:
        return False
    if value is None or row["objective"] is None:
        return value is None and row["objective"] is None
    return abs(row["objective"] - value) <= TOLERANCE * max(1.0, abs(value)) * 2


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m bench.run", description=__doc__.split("\n\n")[0])
    parser.add_argument("--family", default=",".join(FAMILIES), help="comma-separated families")
    parser.add_argument("--sizes", default="S,M", help=f"comma-separated, from {','.join(SIZES)}")
    parser.add_argument("--instances", type=int, default=1, help="instances per family and size")
    parser.add_argument("--seeds", type=int, default=1, help="solver seeds per instance")
    parser.add_argument("--technique", help="name=v1,v2 -- gap_rel or workers; the first is the baseline")
    parser.add_argument("--backends", help="comma-separated; default every backend that takes the model")
    parser.add_argument("--time-limit", type=float, default=30.0)
    parser.add_argument("--workers", type=int, default=8, help="threads (a run's default is 8), unless --technique varies them")
    parser.add_argument("--out", help="write the rows here as JSON; default stdout")
    parser.add_argument("--store", action="store_true", help="also insert the rows into bench_result")
    parser.add_argument("--mps", help="run the MPS files in this directory instead of the families")
    args = parser.parse_args(argv)

    rows = run(
        args.family.split(","),
        args.sizes.split(","),
        count=args.instances,
        seeds=args.seeds,
        technique=parse_technique(args.technique),
        backends=args.backends.split(",") if args.backends else None,
        time_limit=args.time_limit,
        workers=args.workers,
        mps_dir=args.mps,
    )
    text = json.dumps(rows, indent=1)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as handle:
            handle.write(text)
    else:
        sys.stdout.write(text + "\n")
    if args.store:
        store(rows)
    wrong = sum(row["wrong"] for row in rows)
    print(f"{len(rows)} rows, {wrong} wrong", file=sys.stderr)
    return 1 if wrong else 0


def store(rows: list[dict[str, Any]]) -> None:
    """Keep the history queryable (migration 0031)."""
    from sqlalchemy import text

    from app.core.db import SessionLocal

    db = SessionLocal()
    try:
        db.execute(
            text(
                "INSERT INTO bench_result (family, size, instance, model_class, backend, technique,"
                "  technique_value, seed, status, objective, bound, gap, compile_s, solve_s,"
                "  time_limit_s, wrong, primal_integral)"
                " VALUES (:family, :size, :instance, :class, :backend, :technique, :value, :seed,"
                "  :status, :objective, :bound, :gap, :compile_s, :solve_s, :time_limit, :wrong,"
                "  :primal_integral)"
            ),
            [
                {
                    **row,
                    "value": None if row["value"] is None else str(row["value"]),
                    "primal_integral": row.get("primal_integral"),
                }
                for row in rows
            ],
        )
        db.commit()
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
