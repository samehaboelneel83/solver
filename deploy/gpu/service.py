"""One GPU, one admitted solve; run one process/container per physical GPU.

No external services, dependencies downloaded, or disk model files at runtime.
"""
import hmac
import json
import os
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

SLOT = threading.Lock()


def memory():
    raw = subprocess.check_output([
        "nvidia-smi", "--query-gpu=memory.free,memory.used", "--format=csv,noheader,nounits",
    ], timeout=3, text=True).strip().splitlines()
    if len(raw) != 1:
        raise RuntimeError("Expose exactly one GPU to each bridge container")
    return tuple(int(x.strip()) for x in raw[0].split(","))


def optimize(payload):
    from cuopt.linear_programming.problem import Problem, LinearExpression, INTEGER, CONTINUOUS, MINIMIZE, MAXIMIZE
    from cuopt.linear_programming.solver_settings import SolverSettings
    model = payload["model"]
    p = Problem("oaas")
    variables = [p.addVariable(lb=v["lb"], ub=v["ub"], vtype=INTEGER if v["integer"] else CONTINUOUS, name=f"v{i}")
                 for i, v in enumerate(model["variables"])]
    def expr(terms, constant=0):
        return LinearExpression([variables[i] for i, _ in terms], [float(c) for _, c in terms], constant=constant)
    for i, row in enumerate(model["rows"]):
        left, right = expr(row["coeffs"]), row["rhs"]
        relation = row["relation"]
        if relation not in ("<=", ">=", "=="):
            raise ValueError("Unsupported relation")
        p.addConstraint(left <= right if relation == "<=" else left >= right if relation == ">=" else left == right, name=f"r{i}")
    p.setObjective(expr(model["objective"], model["offset"]), sense=MAXIMIZE if model["sense"] == "maximize" else MINIMIZE)
    settings = SolverSettings()
    settings.set_parameter("time_limit", max(0.1, min(float(payload["time_limit"]), float(os.environ.get("GPU_MAX_SECONDS", "1800")))))
    settings.set_parameter("mip_relative_gap", float(payload.get("gap_rel", 0)))
    p.solve(settings)
    raw = p.Status.name
    status = {"Optimal": "optimal", "PrimalFeasible": "feasible", "FeasibleFound": "feasible",
              "PrimalInfeasible": "infeasible", "Infeasible": "infeasible", "Unbounded": "unbounded"}.get(raw, "unknown")
    # A positive MIP gap can terminate before a proven optimum. Do not invent a bound.
    if status == "optimal" and float(payload.get("gap_rel", 0)) > 0:
        status = "feasible"
    return {"status": status, "values": [float(v.getValue()) for v in variables] if status in ("optimal", "feasible") else [],
            "metrics": {"termination": raw}}


class Handler(BaseHTTPRequestHandler):
    def reply(self, status, body):
        data = json.dumps(body, allow_nan=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def authorized(self):
        token = os.environ.get("GPU_SERVICE_TOKEN", "")
        return bool(token) and hmac.compare_digest(self.headers.get("Authorization", ""), "Bearer " + token)

    def do_POST(self):
        if not self.authorized():
            return self.reply(401, {"error": "unauthorized"})
        if self.path != "/solve":
            return self.reply(404, {"error": "not found"})
        length = int(self.headers.get("Content-Length", "0"))
        if not 0 < length <= 64 * 1024 * 1024:
            return self.reply(413, {"error": "model payload limit is 64 MB"})
        if not SLOT.acquire(blocking=False):
            return self.reply(503, {"error": "GPU busy; retry later or use CPU fallback"})
        try:
            self.connection.settimeout(30)
            payload = json.loads(self.rfile.read(length))
            free, used = memory()
            if free < max(64, int(payload.get("memory_mb", 4096))):
                return self.reply(503, {"error": "Insufficient free GPU memory"})
            began = time.monotonic()
            answer = optimize(payload)
            _, after = memory()
            answer["metrics"].update(gpu_memory_used_before_mb=used, gpu_memory_used_after_mb=after,
                                     service_seconds=time.monotonic() - began, gpu_queue_seconds=0,
                                     gpu_slots=1)
            self.reply(200, answer)
        except Exception as exc:
            self.reply(500, {"error": type(exc).__name__})
        finally:
            SLOT.release()


if __name__ == "__main__":
    if not os.environ.get("GPU_SERVICE_TOKEN"):
        raise RuntimeError("GPU_SERVICE_TOKEN is required")
    ThreadingHTTPServer(("0.0.0.0", 8090), Handler).serve_forever()
