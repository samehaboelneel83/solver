"""Explicit remote linear GPU adapter. No model data leaves the configured LAN service."""
import json
import math
import os
import time
from urllib.request import Request, build_opener, HTTPRedirectHandler

from app.solve.result import Solution


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def encode(compiled):
    if (compiled.objective_quadratic or compiled.pwl or compiled.functions or compiled.intervals
            or any(c.quadratic or c.when is not None or c.schedule is not None for c in compiled.constraints)):
        raise ValueError("GPU bridge supports unconditional linear models only")
    keys = list(compiled.variables)
    positions = {k: i for i, k in enumerate(keys)}
    def linear(expr):
        return [[positions[k], float(v)] for k, v in expr.coeffs.items()]
    rows = []
    for c in compiled.constraints:
        expr = c.left.copy().add(c.right, -1)
        rows.append({"coeffs": linear(expr), "relation": c.relation, "rhs": -float(expr.const)})
    return keys, {"variables": [{"lb": float(v.lower), "ub": float(v.upper), "integer": v.is_integral}
                                for v in compiled.variables.values()],
                  "rows": rows, "objective": linear(compiled.objective),
                  "offset": float(compiled.objective.const), "sense": compiled.sense}


def decode(compiled, keys, body, elapsed):
    status = body["status"]
    if status not in ("optimal", "feasible", "infeasible", "unbounded", "unknown"):
        raise ValueError("Unrecognized GPU status")
    values = body.get("values") or []
    assignments = {}
    objective = None
    if status in ("optimal", "feasible"):
        if len(values) != len(keys):
            raise ValueError("GPU result has missing variables")
        for key, value in zip(keys, values):
            value = float(value)
            var = compiled.variables[key]
            if not math.isfinite(value) or value < float(var.lower) - 1e-6 or value > float(var.upper) + 1e-6:
                raise ValueError("GPU result violates variable bounds")
            if var.is_integral:
                if abs(value - round(value)) > 1e-6:
                    raise ValueError("GPU result violates integrality")
                value = round(value)
            assignments[key] = value
        # Validate all rows, including the compiled soft-constraint auxiliaries.
        for c in compiled.constraints:
            delta = float(c.left.evaluated_at(assignments) - c.right.evaluated_at(assignments))
            tolerance = 1e-6 * max(1, abs(float(c.left.evaluated_at(assignments))), abs(float(c.right.evaluated_at(assignments))))
            if ((c.relation == "<=" and delta > tolerance) or (c.relation == ">=" and delta < -tolerance)
                    or (c.relation == "==" and abs(delta) > tolerance)):
                raise ValueError("GPU result violates a compiled constraint")
        objective = float(compiled.objective.evaluated_at(assignments))
    return Solution(status=status, optimal=status == "optimal", objective=objective,
                    assignments=assignments, wall_seconds=elapsed, solver="cuOpt remote",
                    best_bound=objective if status == "optimal" else None,
                    execution={"device": "gpu", **body.get("metrics", {}), "feasibility_checked": bool(assignments)})


def solve(compiled, *, time_limit, workers, seed=None, gap_rel=0, should_stop=None,
          solver_params=None, **kwargs):
    config = solver_params or compiled.gpu_options or {}
    if not config.get("enabled") or not config.get("endpoint"):
        raise ValueError("Enable gpu.enabled and configure gpu.endpoint in Platform Settings first")
    keys, model = encode(compiled)
    started = time.monotonic()
    if should_stop and should_stop():
        return Solution("unknown", False, None, {}, 0, "cuOpt remote")
    try:
        # Budget only half to GPU when fallback is enabled, leaving real CPU time.
        gpu_seconds = time_limit * (0.5 if config.get("cpu_fallback", True) else 0.9)
        payload = {"model": model, "time_limit": gpu_seconds, "gap_rel": gap_rel,
                   "memory_mb": config.get("memory_mb", 4096)}
        request = Request(str(config["endpoint"]).rstrip("/") + "/solve",
                          data=json.dumps(payload, allow_nan=False).encode(),
                          headers={"Content-Type": "application/json",
                                   "Authorization": "Bearer " + os.environ.get("GPU_SERVICE_TOKEN", "")})
        with build_opener(NoRedirect).open(request, timeout=max(0.1, gpu_seconds + min(2, time_limit * 0.05))) as response:
            body = json.loads(response.read(64 * 1024 * 1024))
        return decode(compiled, keys, body, time.monotonic() - started)
    except Exception as exc:
        elapsed = time.monotonic() - started
        remaining = time_limit - elapsed
        if not config.get("cpu_fallback", True) or remaining <= 0 or (should_stop and should_stop()):
            raise RuntimeError(f"GPU solve did not complete ({type(exc).__name__}); no CPU fallback") from exc
        from app.solve import highs
        answer = highs.solve(compiled, time_limit=remaining, workers=workers, seed=seed,
                             gap_rel=gap_rel, should_stop=should_stop)
        answer.wall_seconds += elapsed
        answer.execution = {"device": "cpu", "fallback_from": "cuopt-remote",
                            "fallback_reason": type(exc).__name__, "gpu_request_seconds": elapsed}
        return answer
