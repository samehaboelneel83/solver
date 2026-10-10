# Depending on the platform alone — plan, and the phase 1 evaluation

**10 October 2026.** The goal: a person approves a *plan*, never has to audit a *model*. Today they must,
because a wrong model can build, solve and be "proven optimal" with nothing flagging it
([session handover](2026-10-10-session-handover.md), section 5).

## 1. The plan

| Phase | What | Exit |
|---|---|---|
| 1. Measure | 10 problems from different domains, three sizes each, run through the browser and scored on one checklist (section 2); then nightly pass rates | A stable, trusted score per problem and capability |
| 2. Make common mistakes impossible to write | Tested building blocks the Assistant fills instead of writing by hand: a period balance with an opening amount, "only if set up", a percentage limit, "at most N" | Production and blending reach the pass rate of warehouse and roster problems |
| 3. Catch what gets through | Build the model twice independently and compare answers; account for every number in the message on the plan card; keep the existing checks | No wrong answer reaches a user without a warning |
| 4. Fast and robust | A time cap per problem; when a plan has no answer, show the conflicting rows with numbers | Median under 5 minutes, worst case under 15 |

**Bar for switching off model review:** for two weeks of nightly runs, ≥ 90% right first time, zero
unwarned wrong answers, every failure a clear message. Until then a person approves each model.

**Owner's decision:** a stronger language model would help most, and conflicts with keeping customer
data on the platform. Phases 2–3 proceed on the local model first.

## 2. Phase 1: the evaluation

Ten problems, in the order the owner set: #2 supply chain, #4 factory, #6 exam timetabling,
#1 hospital, #8 cybersecurity, #7 smart grid, #9 cloud allocation, #5 ambulances, #3 camp layout,
#10 disaster response. Each in three sizes:

| Size | Data | Reference |
|---|---|---|
| S | typed in the message (the proven path) | exact optimum from an independent model (SciPy / OR-Tools) |
| M | attached CSV files | exact if it solves in minutes, else a known feasible plan and a bound |
| L | attached CSV files, long format | a constructed known-feasible plan and a bound |

Everything is generated from a seed in `backend/bench/phase1/<nn>_<name>/`: the data files, the
message, the expected result, and a **checker** that validates every hard constraint of an exported
solution against the data files alone — the independent verification, not trusting the solver or
the Assistant's words.

### The score, one row per problem and size

| Column | How it is measured |
|---|---|
| Built / first time / corrections | From the browser trace: no "continue", no stop |
| Model inspection | The plan card's read-back and the model page show the rules; editable in the Model editor |
| Feasibility | The checker on the exported CSV: violations = 0 |
| Optimality | Goal vs reference (exact, or between the known plan and the bound); status and gap recorded |
| Independent verification | The platform's own verdict (Q02) and our checker agree |
| Alternatives | The run page's alternative plans: how many distinct, and their goals |
| Sensitivity | Ranges (linear models only, by design) or what-if runs |
| Performance | Build, solve and verify time from the run's phases; model size |
| Explainability | Binding rules and the goal's breakdown shown |
| Report coverage | How many of the problem's "Expected output" bullets the final answer contains |

**Freezing rule:** a defect found during the evaluation is recorded against the run that found it.
If it is fixed, the re-run is a second row; the first row stands.

The owner's "important tests" are built into the data: #5 ships a travel-time matrix (does the model
read it, or compute straight lines?); #8 defines overlapping protection per asset (does the model add
percentages?); #6's checker reads enrolments for two exams at once; #3 uses a drawing and the
`connected` rule; #9 and #10 record build time, solve time and memory as size grows.

Results: `docs/plans/2026-10-10-phase1-results.md`, one table per problem as it is done.
