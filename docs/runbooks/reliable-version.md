# The reliable version

**As of 15 October 2026** the platform runs its reliable version: the best measured build that works with the
model server as it is now configured, pinned so it can be redeployed or rolled back to at any time.

| What | Where |
|---|---|
| Source | branch `release/reliable`, tag `reliable-2026-10-15` (5576c40) |
| Backend image | `solver-backend:reliable` (eeed56) |
| Frontend image | `solver-frontend:reliable` (9896a6) |
| Database | migration 0122 |
| Model server | qwen3.5 on 10.125.18.189, **with native tool calls** (`--enable-auto-tool-choice --tool-call-parser ...`, enabled by the owner on 15 Oct) |
| Previous reliable version | tag `reliable-2026-10-14`, image `solver-backend:reliable-2026-10-14` (c37772) |

**Why it changed on 15 Oct.** The owner turned on native tool calls on the model server. The 14 Oct version
then fell into a loop: the model copied the history's placeholder for earlier plan attempts as its next plan
("the spec has no ir", over and over). The 15 Oct version fixes that (earlier attempts keep no spec; a copied
placeholder counts as no plan) and adds the per-reply log. **Do not go back to the 14 Oct image while the model
server takes native tool calls**; it is only safe with native calls off.

Measured 15 Oct with native calls, one case at a time, 30 minutes a case: **5, 7, 4 right of 10 (mean 5.3)**, 5
wrong answers without a warning in 30; plans built in 9, 8, 6 cases. (The 14 Oct version, text calls: mean 4.7
at 20 minutes a case, 2 of 30 wrong without a warning; R1 at 30 minutes: 5 right, 2 wrong unwarned in 10.)

**Verified 15 Oct, 17:45:** every backend source file in the live container (384 files) is identical to
`reliable-2026-10-15`; health 200.

## Why this one

Measured on the ten tuning cases (`docs/plans/2026-10-10-neutrality-results.md`):

| Version | One case at a time | Three at a time | Plans built (three at a time) |
|---|---|---|---|
| **Reliable (step 7)** | 5, 4, 5 right (mean 4.7); 2 wrong answers without a warning in 30 | 4 right; 1 unwarned | 9 of 10 |
| Steps 8-11 (later main) | 4.3 mean (step 8) | 3 to 5 right | 5 to 8 of 10 |

Under the same conditions every version is within one case of the others; this one builds the most plans and
has the fewest moving parts. The hidden set read 4 of 16 right on it (13 Oct).

**Verified 14 Oct, 21:20:** every backend source file in the live container (384 files, line endings
normalised) is identical to `release/reliable`; the live frontend bundle carries the last frontend commit on the
branch (70004a0); health 200; migration 0122.

## Check what is running

```bash
docker inspect --format '{{.Image}}' solver-backend-1 | cut -c8-19   # eeed56a8b471 is the reliable version
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8010/api/health
docker compose exec -T backend alembic current                       # 0122 (head)
```

## Go back to it (from any other build)

```bash
docker tag solver-backend:reliable solver-backend:latest
docker tag solver-frontend:reliable solver-frontend:latest
docker compose up -d --no-build backend worker frontend
```

A 502 on `/api/health` in the first seconds after a restart is the startup window; recheck before diagnosing.
The database needs nothing: later builds add no migration past 0122.

## Rebuild it from source (if the images are lost)

```bash
git worktree add -f ../solver-release reliable-2026-10-15 --detach
cd ../solver-release
docker build -t solver-backend:reliable backend
docker build -t solver-frontend:reliable frontend
```

Then the commands of "Go back to it".

## What is not in it

Everything on main after 384549a: the canonical form (`app/agent/canon.py`), the constructs library, the
always-yes warning, refusals that name the fix, the build protocol (behind `LLM_BUILD_STAGES`), the per-reply log,
and the harness fixes. They are measured and kept on main; none of them raised the right answers on this model.
A newer build replaces this one only after three runs, measured the same way as this one, show it better.
