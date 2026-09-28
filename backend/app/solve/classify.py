"""What kind of model is this, and what must a solver do to take it?

Phase 2 of the roadmap wants the platform to pick a technique and say why.
Classification is the half of that which has nothing to do with any solver, so
it lives here rather than inside a backend adapter.

**Two outputs, doing different jobs.** `model_class` is the name a person
recognises -- LP, IP, MILP -- and is what a run is labelled with. `needs` is
what the registry actually matches against, and is deliberately finer-grained
than the class: `fractional-data` is not visible in the class name at all, yet
it is the thing that decides whether CP-SAT may be offered an otherwise
perfectly integral model.

**Why the data is an input.** Until migration 0015 every number in the system
was an integer and classification was a pure function of the IR. It no longer
can be: a model whose variables are all binary is still out of CP-SAT's reach
if a parameter is 2.5. The IR alone cannot see that, because the IR declares
the *shape* of a model and the dataset supplies its *numbers*. So `data` is an
optional second input, and it can only ever add `fractional-data` -- it never
changes the class, which stays a property of the model itself.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from decimal import Decimal, InvalidOperation
from typing import Any


@dataclass
class Classification:
    model_class: str
    reasons: list[str]
    # What a backend must support to run it.
    needs: set[str]
    #: The same facts in a planner's words. The Model editor shows these
    #: rather than "IP" / "fractional-data"; `reasons` stays the record on
    #: the run, because that is what a modeller traces a backend choice to.
    planner: list[str] = field(default_factory=list)
    #: need -> why a backend that would otherwise fit may not take this
    #: model, when the need itself cannot say (`reformulate.admit`: which
    #: variable left a conditional rule without a big-M). `choose` quotes it.
    refusals: dict[str, str] = field(default_factory=dict)
    #: For a model that applies a catalogue function to a decision: whether
    #: the composition rules prove it convex (`app.solve.dcp`). None when
    #: the question was not asked.
    convex: bool | None = None


def classify(ir: dict[str, Any], data: dict[str, Any] | None = None) -> Classification:
    # An interval is not a number: its start and end variables are, and they
    # decide the class like any other.
    domains = {spec.get("domain", "binary") for spec in ir.get("variables", {}).values()} - {"interval"}
    reasons: list[str] = []
    needs = {"linear"}

    planner: list[str] = []
    refusals: dict[str, str] = {}

    if not domains:
        reasons.append("no variables, so nothing is decided")
        planner.append("nothing is decided yet")
        return Classification("trivial", reasons, needs, planner)

    integral = domains & {"binary", "integer"}
    continuous = domains & {"continuous"}

    if continuous and integral:
        model_class = "MILP"
        needs |= {"integral", "continuous"}
        reasons.append(
            f"some variables are integral ({', '.join(sorted(integral))}) and some are "
            "continuous, so the model is mixed"
        )
        planner.append("some decisions are yes or no, some are quantities")
    elif continuous:
        model_class = "LP"
        needs.add("continuous")
        reasons.append("every variable is continuous")
        planner.append("every decision is a quantity")
    elif domains == {"binary"}:
        model_class = "IP"
        needs.add("integral")
        reasons.append("every variable is binary")
        planner.append("every decision is yes or no")
    elif domains <= {"binary", "integer"}:
        model_class = "IP"
        needs.add("integral")
        reasons.append(f"variables are integral ({', '.join(sorted(domains))})")
        planner.append("every decision is a whole number")
    else:  # pragma: no cover -- the validator pins the vocabulary
        reasons.append(f"variable domains {sorted(domains)} are not ones this platform knows")
        return Classification("unsupported", reasons, needs, planner)

    quadratic_goal = _quadratic_objective(ir)
    quadratic_rules = _quadratic_rules(ir)
    mixed_or_whole = model_class != "LP"
    if quadratic_rules:
        # A rule that multiplies two decisions: a quadratically constrained
        # model, whatever the goal. Its class says whether any decision is
        # whole. Its feasible region may be nonconvex, which is why only a
        # solver that proves a global optimum regardless is offered one.
        model_class = "MIQCQP" if mixed_or_whole else "QCQP"
        needs.add("quadratic-constraints")
        verb = "multiplies" if len(quadratic_rules) == 1 else "multiply"
        names = ", ".join(quadratic_rules)
        reasons.append(
            f"{names} {verb} two variables together, so the model has quadratic rules"
        )
        planner.append("a rule multiplies decisions together")
    if quadratic_goal:
        if not quadratic_rules:
            model_class = "MIQP" if mixed_or_whole else "QP"
        needs.add("quadratic")
        reasons.append("the objective multiplies two variables together, so it is quadratic")
        planner.append("the goal multiplies decisions together")
    if not quadratic_rules:
        reasons.append("every rule is linear")
        planner.append("every rule is linear")

    functions = sorted(_functions(ir))
    if functions:
        # A catalogue function of a decision: nonlinear, whatever else the
        # model is, and held only by a solver that takes the function itself.
        model_class = "MINLP" if mixed_or_whole else "NLP"
        needs.add("functions")
        names = ", ".join(functions)
        reasons.append(
            f"the model applies {names} to decisions, so it is nonlinear beyond products"
        )
        planner.append(f"a rule or the goal applies {names} to decisions")
        # SCIP answers either way (it searches globally); this says whether
        # the model is one where the best answer nearby is the best overall.
        from app.solve.dcp import model_curvature

        verdict = model_curvature(ir, data)
        convex = verdict.convex
        relaxed = " (its continuous relaxation, as some decisions are whole)" if mixed_or_whole else ""
        if convex:
            reasons.append(f"the model is convex{relaxed}: {verdict.reason}")
            planner.append("the rules and the goal curve one way, so the best answer nearby is the best overall")
        else:
            reasons.append(f"the model is not proven convex{relaxed}: {verdict.reason}")
            planner.append(
                "the goal or a rule may have more than one peak or dip, so the solver searches the whole range"
            )
    else:
        convex = None

    if any(c.get("severity") == "soft" for c in ir.get("constraints", [])):
        needs.add("soft-constraints")
        reasons.append("at least one constraint is soft, so the backend must carry penalties")
        planner.append("at least one rule can bend, at a cost")

    if any(isinstance(c, dict) and "when" in c for c in ir.get("constraints", [])):
        needs.add("indicator")
        reasons.append(
            "a rule holds only while a yes-or-no decision is set (`when`), which a solver "
            "must switch on and off rather than approximate"
        )
        planner.append("some rules apply only when a decision says so")

    if _scheduling(ir):
        needs.add("scheduling")
        reasons.append(
            "the model has intervals or a scheduling rule (no_overlap, cumulative), which a "
            "constraint solver holds natively and nothing else here holds at all"
        )
        planner.append("some things are placed in time and must not clash")
        refusals["scheduling"] = (
            "a scheduling rule or an interval is solved by CP-SAT, the one solver here that "
            "holds them"
        )

    if any(isinstance(c, dict) and "connected" in c for c in ir.get("constraints", [])):
        needs.add("connected")
        reasons.append(
            "a rule keeps each group's units in one connected piece, which a solver holds as a "
            "flow over their adjacency"
        )
        planner.append("some groups must be one connected piece")

    if any(isinstance(c, dict) and "route" in c for c in ir.get("constraints", [])):
        needs.add("route")
        reasons.append(
            "a rule sends vehicles from a depot round every stop and back, which a solver holds as "
            "visits in and out of each stop and a load flow that rules out loops missing the depot"
        )
        planner.append("vehicles go round the stops from a depot")

    if _has_pwl(ir):
        needs.add("pwl")
        reasons.append(
            "a cost or amount follows a piecewise-linear curve, which a solver holds by choosing "
            "the segment x falls on"
        )
        planner.append("some amounts follow a curve with corners")

    predictors = sorted(_predictors(ir))
    if predictors:
        # A trained model over decisions (Epic ML): the compiler writes its
        # trees as rows with one yes-or-no choice per leaf (`app.solve.predict`),
        # so the model gains whole-number decisions whatever it had, and the
        # leaves' values are rarely whole.
        model_class = {"LP": "MILP", "QP": "MIQP", "QCQP": "MIQCQP", "NLP": "MINLP"}.get(model_class, model_class)
        needs |= {"integral", "fractional-data"}
        names = ", ".join(predictors)
        reasons.append(
            f"the model optimizes over the trained model{'s' if len(predictors) > 1 else ''} {names}, "
            "whose trees are written as rows with a yes-or-no choice per leaf"
        )
        planner.append(f"a goal or rule follows the prediction of {names}")

    fractional = _fractional(ir, data)
    if fractional:
        needs.add("fractional-data")
        reasons.append(
            f"{fractional} is not a whole number, so a solver that works in integers "
            "cannot take this model without changing it"
        )
        planner.append(
            f"{fractional} is not a whole number, so a yes-or-no solver cannot take this model"
        )

    return Classification(model_class, reasons, needs, planner, refusals=refusals, convex=convex)


def _scheduling(ir: dict[str, Any]) -> bool:
    return any(
        isinstance(spec, dict) and spec.get("domain") == "interval" for spec in ir.get("variables", {}).values()
    ) or any(
        isinstance(c, dict) and ("no_overlap" in c or "cumulative" in c) for c in ir.get("constraints", [])
    )


def _quadratic_objective(ir: dict[str, Any]) -> bool:
    """Whether any objective term multiplies two variables together."""
    return any(
        _degree(term.get("expression")) >= 2 for term in (ir.get("objective") or {}).get("terms", [])
    )


def _quadratic_rules(ir: dict[str, Any]) -> list[str]:
    """The ids of the rules that multiply two variables together."""
    return [
        str(spec.get("id"))
        for spec in ir.get("constraints", [])
        if isinstance(spec, dict)
        and max(_degree(spec.get("left")), _degree(spec.get("right"))) >= 2
    ]


def _degree(term: Any) -> int:
    if not isinstance(term, dict):
        return 0
    if "var" in term or "pwl" in term:
        return 1
    if "fn" in term:
        return 1 if _degree(term.get("of")) else 0
    if "predict" in term:
        return 1 if any(_degree(a) for a in term.get("of") or []) else 0
    if "sum" in term:
        return _degree(term["sum"])
    if isinstance(term.get("add"), list):
        return max((_degree(child) for child in term["add"]), default=0)
    if isinstance(term.get("mul"), list):
        return sum(_degree(child) for child in term["mul"])
    return 0


def with_convexity(found: Classification, convex: bool | None, reason: str) -> Classification:
    """The classification, told whether the compiled objective is convex.

    Convexity is a fact about the numbers, so it is known only after the
    model is compiled against its data -- which is why this is a second step
    rather than part of `classify`. A model not proven convex needs a backend
    that does not depend on convexity; `nonconvex` is how the registry asks.
    """
    if "quadratic" not in found.needs or convex is True:
        return found
    # `replace`, not a new Classification: what the earlier steps set
    # (refusals, a convexity verdict) survives this one.
    return replace(
        found,
        reasons=[*found.reasons, reason],
        needs=found.needs | {"nonconvex"},
        planner=[*found.planner, "the goal may have more than one low point, so the best one has to be searched for"],
    )


def _functions(node: Any) -> set[str]:
    """The catalogue functions the model applies to a decision -- one of data
    is only a number."""
    if isinstance(node, dict):
        found = set().union(*(_functions(v) for v in node.values())) if node else set()
        if isinstance(node.get("fn"), str) and _degree(node.get("of")):
            found.add(node["fn"])
        return found
    if isinstance(node, list):
        return set().union(*(_functions(v) for v in node)) if node else set()
    return set()


def _predictors(node: Any) -> set[str]:
    """The predictors the model applies to a decision -- one of data is only
    a number, a forecast (Epic ML)."""
    if isinstance(node, dict):
        found = set().union(*(_predictors(v) for v in node.values())) if node else set()
        if isinstance(node.get("predict"), str) and any(_degree(a) for a in node.get("of") or []):
            found.add(node["predict"])
        return found
    if isinstance(node, list):
        return set().union(*(_predictors(v) for v in node)) if node else set()
    return set()


def _has_pwl(node: Any) -> bool:
    if isinstance(node, dict):
        return "pwl" in node and "points" in node or any(_has_pwl(v) for v in node.values())
    if isinstance(node, list):
        return any(_has_pwl(v) for v in node)
    return False


def _fractional(ir: dict[str, Any], data: dict[str, Any] | None) -> str | None:
    """The first non-whole number in the model, named, or None.

    Named rather than counted, because the reason is recorded on the run and
    "demand is 2.5" tells someone which number made their model continuous
    where "it has fractional data" sends them looking through all of them.
    """
    for name, spec in ir.get("variables", {}).items():
        for key in ("lower", "upper"):
            if key in spec and not _whole(spec[key]):
                return f"{name}'s {key} bound ({spec[key]})"

    found = _fractional_in_terms(ir)
    if found is not None:
        return found

    if data is None:
        return None

    for name, rows in (data.get("parameters") or {}).items():
        for row in rows:
            if not _whole(row.get("value")):
                return f"the parameter {name} ({row.get('value')})"
    for name, value in (data.get("parameter_defaults") or {}).items():
        if not _whole(value):
            return f"the default of the parameter {name} ({value})"

    # An `attr` used as a number: only the ones the model actually reads
    # matter, so the set rows are searched by the attribute names the terms
    # name rather than wholesale.
    wanted = _attributes_used(ir)
    for set_name, rows in (data.get("sets") or {}).items():
        for row in rows:
            for attribute in wanted:
                if attribute in row and not _whole(row[attribute]):
                    return f"{set_name}.{attribute} ({row[attribute]})"
    # An edge's attributes (queue R19) are read the same way.
    for rel, edges in (data.get("relationships") or {}).items():
        for edge in edges:
            attrs = edge.get("attrs") or {}
            for attribute in wanted:
                if isinstance(attrs.get(attribute), (int, float)) and not _whole(attrs[attribute]):
                    return f"{rel}.{attribute} ({attrs[attribute]})"
    return None


def _fractional_in_terms(ir: dict[str, Any]) -> str | None:
    for spec in ir.get("constraints", []):
        for side in ("left", "right"):
            found = _walk_const(spec.get(side))
            if found is not None:
                return f"a constant in {spec.get('id', 'a constraint')} ({found})"
    for term in (ir.get("objective") or {}).get("terms", []):
        if not _whole(term.get("weight", 1)):
            return f"the weight of the objective term {term.get('id')} ({term.get('weight')})"
        found = _walk_const(term.get("expression"))
        if found is not None:
            return f"a constant in the objective term {term.get('id')} ({found})"
    return None


def _walk_const(term: Any) -> Any:
    if not isinstance(term, dict):
        return None
    if "const" in term and not _whole(term["const"]):
        return term["const"]
    for key in ("sum", "add", "mul"):
        body = term.get(key)
        if isinstance(body, dict):
            found = _walk_const(body)
            if found is not None:
                return found
        elif isinstance(body, list):
            for item in body:
                found = _walk_const(item)
                if found is not None:
                    return found
    return None


def _attributes_used(ir: dict[str, Any]) -> set[str]:
    found: set[str] = set()

    def walk(term: Any) -> None:
        if not isinstance(term, dict):
            return
        if "attr" in term and isinstance(term["attr"], dict):
            name = term["attr"].get("name")
            if isinstance(name, str):
                found.add(name)
        for key in ("sum", "add", "mul"):
            body = term.get(key)
            if isinstance(body, dict):
                walk(body)
            elif isinstance(body, list):
                for item in body:
                    walk(item)

    for spec in ir.get("constraints", []):
        walk(spec.get("left"))
        walk(spec.get("right"))
    for term in (ir.get("objective") or {}).get("terms", []):
        walk(term.get("expression"))
    return found


def _whole(value: Any) -> bool:
    """True for anything that is a whole number, and for anything that is not
    a number at all -- a string attribute is not this function's business, and
    calling it fractional would route a model away from CP-SAT for no reason.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal, str)):
        return True
    try:
        as_decimal = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return True
    return as_decimal == as_decimal.to_integral_value()
