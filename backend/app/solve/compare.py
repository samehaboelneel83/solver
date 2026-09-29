"""Two runs, side by side.

The roadmap's Phase 4 calls this the thing that turns a calculator into
something a planner can argue with, and the argument has a shape: *this* rule
was relaxed, so *these* shifts moved, and the cost changed by *this much*.
One run alone cannot say any of that.

**What is compared, and what is refused.** Two runs of the same problem, so
their variables and rules are the same vocabulary. Runs of different problems
are refused rather than diffed into nonsense -- `assign` in one domain has
nothing to do with `assign` in another, and a diff that lined them up would
invent a relationship.

**Comparability is reported, not assumed.** Two runs differ by whatever
differs: the patch, the model version, the frozen data, the solver, the seed.
Only when everything but the patch is equal can a difference in the answer be
attributed to the patch, which is the question people actually ask. So the
comparison lists what differs (`differs_by`) and states plainly whether the
patch is the only difference. A diff that silently compared runs over
different data would attribute a change to a rule when it came from an
employee being added, and that is a wrong answer dressed as an insight.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session


class NotComparable(Exception):
    """The two runs cannot be put side by side."""


@dataclass
class VariableDiff:
    """What moved, in the domain's own words."""

    #: Index tuples in the right run's answer but not the left's.
    added: list[list[str]] = field(default_factory=list)
    #: In the left's but not the right's.
    removed: list[list[str]] = field(default_factory=list)
    #: In both. Kept as a count: a planner reads what changed, not what did not.
    unchanged: int = 0


@dataclass
class RuleDiff:
    constraint_id: str
    left_satisfied: bool
    right_satisfied: bool
    left_violation: int
    right_violation: int
    left_penalty: int
    right_penalty: int


@dataclass
class Comparison:
    left: dict[str, Any]
    right: dict[str, Any]
    #: right - left. None when either run has no objective to compare.
    objective_delta: int | None
    #: Per variable name. Only variables that moved appear.
    moved: dict[str, VariableDiff]
    #: Rules whose outcome differs. A rule that held in both is not news.
    rules: list[RuleDiff]
    #: Everything that is not equal between the two runs, e.g. ["patch"].
    differs_by: list[str]
    #: True only when `differs_by` is exactly the patch, so the change in the
    #: answer can honestly be attributed to it.
    patch_is_the_only_difference: bool
    note: str
    #: When the two answers claim different things (proven best against best nearby, say), what that means
    #: for reading the difference in their values (Epic UX, U-5). None when they claim the same.
    claims: str | None = None


# Qualified: `run` is joined to `scenario`, and both have an `id`.
_FIELDS = (
    "run.id, run.scenario_id, run.dataset_id, run.status, run.solver,"
    " run.solver_version, run.seed, run.objective, run.wall_time_s,"
    " run.optimality, run.gap, run.params->>'classified_as' AS classified_as"
)


def compare(db: Session, left_id: int, right_id: int) -> Comparison:
    if left_id == right_id:
        raise NotComparable("a run compared with itself has no differences to show")

    left = _run(db, left_id)
    right = _run(db, right_id)
    if left["problem_id"] != right["problem_id"]:
        raise NotComparable(
            f"run {left_id} solves problem {left['problem_id']} and run {right_id} solves "
            f"problem {right['problem_id']}; their variables are not the same vocabulary"
        )

    differs = _differences(left, right)
    return Comparison(
        left=_public(left),
        right=_public(right),
        objective_delta=(
            right["objective"] - left["objective"]
            if left["objective"] is not None and right["objective"] is not None
            else None
        ),
        moved=_moved(_assignments(db, left_id), _assignments(db, right_id)),
        rules=_rules(db, left_id, right_id),
        differs_by=differs,
        patch_is_the_only_difference=differs == ["patch"],
        note=_note(differs),
        claims=_claims(left, right),
    )


def _run(db: Session, run_id: int) -> dict[str, Any]:
    row = db.execute(
        text(
            f"SELECT {_FIELDS}, s.name AS scenario_name, s.patch, s.problem_id,"
            "        s.model_version_id"
            "   FROM run JOIN scenario s ON s.id = run.scenario_id"
            "  WHERE run.id = :r"
        ),
        {"r": run_id},
    ).mappings().first()
    if row is None:
        raise NotComparable(f"there is no run {run_id}")
    return dict(row)


def _public(row: dict[str, Any]) -> dict[str, Any]:
    keep = (
        "id", "scenario_id", "scenario_name", "status", "solver", "solver_version",
        "objective", "wall_time_s", "dataset_id", "patch",
        # What each answer may claim, side by side (Epic UX, U-5).
        "optimality", "gap", "classified_as",
    )
    return {key: row[key] for key in keep}


def _differences(left: dict[str, Any], right: dict[str, Any]) -> list[str]:
    """What is not equal. Ordered most-consequential first, because the first
    entry is the one that explains the answer."""
    checks = (
        ("model version", "model_version_id"),
        ("data", "dataset_id"),
        ("patch", "patch"),
        ("solver", "solver"),
        ("seed", "seed"),
    )
    return [name for name, column in checks if (left[column] or None) != (right[column] or None)]


_CLAIM = {
    "global": "proven the best possible",
    "local": "the best nearby, not proven the best",
    "approximate": "optimal to a small tolerance",
    "none": "an answer, with no claim to be the best",
}


def _claims(left: dict[str, Any], right: dict[str, Any]) -> str | None:
    """Why two goal values may not be comparable at face value."""
    a, b = left.get("optimality") or "none", right.get("optimality") or "none"
    if a == b:
        return None
    return (f"run {left['id']}'s answer is {_CLAIM.get(a, a)}; run {right['id']}'s is {_CLAIM.get(b, b)}. "
            "A difference in their goal values may be the solvers', not the scenarios'.")


def _note(differs: list[str]) -> str:
    if not differs:
        return (
            "these runs asked the same question of the same data with the same solver, "
            "so any difference in the answer is the solver's freedom to choose between "
            "equally good answers"
        )
    if differs == ["patch"]:
        return "the patch is the only difference, so the change in the answer is down to it"
    if len(differs) == 1:
        # One difference can be named as the cause (operator trial F28).
        return f"these runs differ only by {differs[0]}, so the change in the answer is down to it"
    return (
        "these runs differ by " + ", ".join(differs) + ", so a change in the answer "
        "cannot be attributed to any one of them"
    )


def _assignments(db: Session, run_id: int) -> dict[str, set[tuple[str, ...]]]:
    row = db.execute(
        text("SELECT assignments FROM solution WHERE run_id = :r"), {"r": run_id}
    ).scalar()
    if not row:
        return {}
    return {name: {tuple(entry) for entry in tuples} for name, tuples in row.items()}


def _moved(
    left: dict[str, set[tuple[str, ...]]], right: dict[str, set[tuple[str, ...]]]
) -> dict[str, VariableDiff]:
    moved: dict[str, VariableDiff] = {}
    for name in sorted(set(left) | set(right)):
        before, after = left.get(name, set()), right.get(name, set())
        if before == after:
            continue
        moved[name] = VariableDiff(
            added=[list(t) for t in sorted(after - before)],
            removed=[list(t) for t in sorted(before - after)],
            unchanged=len(before & after),
        )
    return moved


def _rules(db: Session, left_id: int, right_id: int) -> list[RuleDiff]:
    rows = db.execute(
        text(
            "SELECT constraint_id, run_id, satisfied, total_violation, penalty_paid"
            "  FROM constraint_result WHERE run_id IN (:l, :r)"
        ),
        {"l": left_id, "r": right_id},
    ).mappings().all()

    both: dict[str, dict[int, Any]] = {}
    for row in rows:
        both.setdefault(row["constraint_id"], {})[row["run_id"]] = row

    out = []
    for constraint_id, sides in sorted(both.items()):
        left, right = sides.get(left_id), sides.get(right_id)
        if left is None or right is None:
            # A rule only one run has: the patch disabled it, or the versions
            # differ. `differs_by` already says which, and inventing a
            # satisfied/unsatisfied verdict for the missing side would be a
            # claim about a rule that was never checked.
            continue
        if (
            left["satisfied"] == right["satisfied"]
            and left["total_violation"] == right["total_violation"]
            and left["penalty_paid"] == right["penalty_paid"]
        ):
            continue
        out.append(
            RuleDiff(
                constraint_id=constraint_id,
                left_satisfied=left["satisfied"],
                right_satisfied=right["satisfied"],
                left_violation=left["total_violation"],
                right_violation=right["total_violation"],
                left_penalty=left["penalty_paid"],
                right_penalty=right["penalty_paid"],
            )
        )
    return out
