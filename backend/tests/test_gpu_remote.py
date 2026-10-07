from decimal import Decimal as D
import pytest
from app.solve.compile import Compiled, Variable, Linear, Constraint
from app.solve.gpu_remote import encode, decode, solve


def model():
    key = ("x", ())
    return Compiled({key: Variable(key, "integer", D(0), D(10))},
                    [Constraint("limit", {}, Linear({key: D(1)}), "<=", Linear(const=D(4)))],
                    Linear({key: D(2)}, D(3)), "maximize", {})


def test_linear_transport_and_objective_offset():
    m = model()
    keys, payload = encode(m)
    assert payload["rows"][0]["rhs"] == 4
    assert payload["offset"] == 3
    answer = decode(m, keys, {"status": "optimal", "values": [4]}, .2)
    assert answer.objective == 11
    assert answer.best_bound == 11


@pytest.mark.parametrize("values", [[], [4.5], [5], [float("nan")], [-1]])
def test_invalid_gpu_answers_rejected(values):
    m = model()
    with pytest.raises(ValueError):
        decode(m, list(m.variables), {"status": "optimal", "values": values}, 1)


def test_disabled_service_never_sends_model():
    with pytest.raises(ValueError, match="Enable"):
        solve(model(), time_limit=1, workers=1)


def test_unsupported_model_not_silently_relaxed():
    m = model()
    key = next(iter(m.variables))
    m.objective_quadratic = {(key, key): D(1)}
    with pytest.raises(ValueError, match="linear"):
        encode(m)


def test_network_failure_uses_remaining_cpu_budget(monkeypatch):
    from app.solve import gpu_remote, highs
    from app.solve.result import Solution
    monkeypatch.setattr(gpu_remote, "build_opener", lambda *a: (_ for _ in ()).throw(OSError("unavailable")))
    seen = {}
    def cpu(compiled, **kwargs):
        seen.update(kwargs)
        return Solution("optimal", True, 11, {("x", ()): 4}, .01, "HiGHS")
    monkeypatch.setattr(highs, "solve", cpu)
    answer = solve(model(), time_limit=10, workers=2, solver_params={"enabled": True, "endpoint": "http://gpu:8090"})
    assert 0 < seen["time_limit"] <= 10
    assert answer.execution["device"] == "cpu"
    assert answer.execution["fallback_from"] == "cuopt-remote"
