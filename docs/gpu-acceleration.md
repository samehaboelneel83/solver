# Queue resources and private GPU acceleration

## Application settings

Administration → Platform settings → GPU acceleration exposes:

| Key | Default | Meaning |
| --- | --- | --- |
| gpu.enabled | false | Allows explicitly selected GPU solves |
| gpu.endpoint | empty | Private bridge origin, for example http://gpu-server:8090 |
| gpu.cpu_fallback | true | Fall back to HiGHS on transport errors, busy service or invalid answers |
| gpu.memory_mb | 4096 | Required free GPU memory at admission, not a hard allocation cap |

GPU settings are operator-controlled, platform-only and frozen in each new run.
After configuring them, select `cuopt-remote` in `solve.solver` at the problem level.
Automatic solver selection continues to use existing solvers, even after adapter conformance.
Benchmark before enabling GPU by default for a domain. Clearing `solve.solver` restores automatic selection.
Already queued runs retain their GPU settings snapshot.

`solve.workers` remains an application setting: the requested CPU thread count.
At queue admission, requests are capped by `SOLVE_WORKER_CPUS` and `SOLVE_HOST_WORKERS`.
The default Compose deployment aligns both with its 8-CPU worker container.
The 12 GB worker leaves headroom above its 10 GB scheduler memory budget.
Planner jobs can borrow idle check capacity; check jobs retain their ceiling.
Runs record `params.requested_workers`, `params.workers`, `params.reservation`, and `params.queue_reason`.
This repairs previously queued 32-thread requests without resubmitting or duplicating runs.
Multiple worker replicas share the configured host budget; do not multiply host limits per replica.

## Dedicated offline GPU host

The application host's GT 730 is not a supported deployment target for this integration.
Use a compatible NVIDIA GPU host, with driver and container GPU support validated against the chosen cuOpt release.

1. On a connected staging machine, assemble and test a pinned Linux image containing the cuOpt Python package and Python.
2. Export with `docker save -o cuopt-image.tar IMAGE`, verify a SHA256 checksum after transfer, and import with `docker load -i cuopt-image.tar` on the isolated host.
3. Copy `deploy/gpu/service.py` and `deploy/gpu/compose.yml` to that host.
4. Configure `CUOPT_IMAGE` to the preloaded image, `GPU_DEVICE_ID`, `GPU_BIND_IP` to its private interface, and a strong `GPU_SERVICE_TOKEN`.
5. Configure the same `GPU_SERVICE_TOKEN` in the application deployment's environment file and recreate the worker. Credentials deliberately do not appear in readable application settings or run snapshots.
6. Run `docker compose -f deploy/gpu/compose.yml up -d --pull never` on the GPU host. The compose file uses `pull_policy: never` and installs nothing at startup.
7. Restrict port 8090 to the platform host on the private network. Use a TLS reverse proxy when transport encryption is required; set gpu.endpoint to its HTTPS origin.
8. Enter the endpoint and enable switch through Application Settings, then choose a small representative problem for a test.

The supplied bridge uses the documented cuOpt `Problem`, `LinearExpression`, and `SolverSettings` API:
https://github.com/NVIDIA/cuopt/blob/main/skills/cuopt-numerical-optimization-api/references/python_api.md

## Capability and resource boundaries

Initial adapter: unconditional linear LP/IP/MILP models, including compiled soft penalties.
Quadratic, scheduling, piecewise and conditional expressions are rejected rather than omitted.
The bridge admits one request per exposed physical GPU. Busy requests return 503 immediately;
they do not wait behind another solve. With fallback enabled, the client reserves part of its time
budget for CPU solving. A dropped client does not release the GPU slot until the solve returns.
GPU timeout is bounded by the requested solver limit and GPU_MAX_SECONDS (default 1800 seconds).
Solver time limits are cooperative; a nonresponsive native solver may require service restart.
Do not run multiple bridge containers against the same GPU or share it with the LLM without separate allocation.

GPU memory is checked before admission. Before/after device memory samples are recorded;
they are not peak memory or a per-process allocation measurement. CUDA allocation limits are not enforced.
The client independently checks finite assignments, bounds, integrality and all compiled linear rows.
The objective is recalculated locally. Unrecognized solver statuses never become successful answers.
Positive requested MIP gaps are reported as feasible, not proven optimal. Bounds are left unknown
unless optimality is reported; the implementation does not invent a gap for feasible GPU results.

## Evidence and benchmarking

The run already records queue/start/finish timestamps, objective, wall time, best bound and gap.
`params.execution` additionally records GPU service time, admission queue time (zero: immediate admission/refusal),
memory samples and feasibility checking, or the actual CPU fallback and failure category.
Results from multi-stage/decomposed solves may aggregate solver results; use direct scalar linear solves
for initial GPU benchmarking and inspect the actual solver version rather than assuming GPU execution.

Compare CPU and GPU on identical frozen datasets, constraints, objective, time limit and target gap.
Use `reuse=false` so a cached answer does not masquerade as a fast solve. Record repeated timings,
feasibility, objective, gap, transfer overhead, GPU memory and fallback occurrence. Include the bed-layout
model and small/medium/large cases. No hardware benchmark has yet been performed for this deployment;
GPU execution must remain opt-in until the target server passes these tests.

## Rollback

Clear solve.solver overrides selecting cuopt-remote, then disable gpu.enabled for new runs.
Stop the dedicated GPU service after its active work finishes. Existing CPU solver paths remain installed.
