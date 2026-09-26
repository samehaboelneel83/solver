# OAAS Phase 0 — baseline inventory

> Linked from [`OAAS_PLATFORM_PROPOSAL.md`](../../OAAS_PLATFORM_PROPOSAL.md).  
> Status as of 2026-09-26. Reconciles handover with the proposal before Phase 1.

## Capability inventory

| Area | Status | Notes |
|---|---|---|
| Problem IR + validation | **implemented** | `docs/contracts/problem-ir.md` |
| Solver adapters / choose / sandbox | **implemented** | Track D done |
| Planner locks / stay-close / why-not / ranges | **implemented** | R24–R28 |
| Cell-click lock + what-if form | **implemented** | `2bc5713` |
| Suite / gate / shadow / nightly | **implemented** | R29–R32 |
| Gate override + audit | **implemented** | `0081` |
| Shadow card UI | **implemented** | Model versions |
| Hide `checks:` scenarios | **implemented** | default list filter |
| SSO / SCIM / retention / Helm / tiers | **implemented** | Track C R35–R40 |
| Backups / queue metrics / audit | **implemented** | R39 / R33 / R34 |
| Offline install bundle (digest-pinned) | **implemented** | O01 + offline-bundle + digest compose + Dockerfile `OFFLINE=1` wheelhouse/npm-cache |
| Reachability UX | **implemented** | O02 banner + egress-check + hooked in `check.sh` (skips if stack down) |
| Chunked large results | **implemented** | 0082 + `GET …/amounts`; inline cap 200k |
| Approval lifecycle | **implemented** | 0082 + API + Runs `ApprovePlanPanel` UI |
| Scale reservations / capacity | **implemented** | S04 `app.solve.reserve` + S05 reference limits in `docs/contracts/scale-reliability.md` |
| URL-authoritative context (no silent fallback) | **implemented** | `useModelTarget` + ContextMismatch + `/domains/:domainId/...` routes + scoped nav |
| Unified run detail (Runs + Workspace) | **implemented** | N06 guided tab; `/workspace` → `/runs?tab=guided` |
| Coverage / bench gates | **implemented** | Q01 matrix + Q02 verify + Q03 `params.phases` + Q04 family policies / equal_budget + Q05 suites path |
| Navigation hierarchy (proposal §3) | **implemented** | Phase 1 N01–N07 + §3.5 scoped URLs |
| Learned selector promotion | **partial** | shadow only (by design) |

## Route inventory (current → proposed owner)

| Current path | Proposed owner | Migration |
|---|---|---|
| `/` | Home | alias `/home` |
| `/public/domain` | Domains | alias `/domains` |
| `/entities`, `/relationships`, `/parameters` | Domain → Data | keep until domain shell |
| `/entity-types`, `/relationship-types` | Domain → Data Structure | keep |
| `/graph` | Domain → Data → Map & graph | keep |
| `/public/problem`, `/model`, `/versions`, `/scenarios` | Problem | keep |
| `/runs`, `/workspace` | Problem → Runs & Results | N06: workspace → runs?tab=guided |
| `/public/template` | Template Library | alias `/templates` |
| `/solvers` | Operations → Solvers | regroup nav |
| `/settings`, `/api-keys`, `/iam/*` | Administration | regroup nav |

## Offline dependency notes (Phase 0)

- Dockerfiles support `OFFLINE=1` with `backend/wheelhouse/` and `frontend/npm-cache/`.
- Compose digests: `deploy/compose/docker-compose.digests.example.yml`.
- Egress: `scripts/egress-check.sh` (optional `EGRESS_BLOCKED=1`); hooked from `check.sh`.
- See proposal §6 and `docs/runbooks/offline-install.md`.

## Representative user tasks (agreed for Phase 1 acceptance)

1. Find a problem in a domain.
2. Open / change a scenario.
3. Open the latest result for that problem.
4. Bookmark a problem URL and reopen it in another session without silent substitution.

## Next

OAAS Phase 0–5 backlog items (N/W/O/Q01–Q05, S01–S05, chunks/approvals, scoped URLs,
offline Docker path, Archivo/teal theme) are in the working tree. Remaining work is
demand-led extensions (Phase 6) and further equal-budget re-runs when changing defaults.
