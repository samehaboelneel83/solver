# Issues report and the plan to do better — 11 October 2026

Source: `docs/plans/2026-10-10-neutrality-results.md` (every measurement), the tuning runs (readable), and the
hidden set through its blind aggregate only.

## Where it stands

| Measurement | Tuning right (of 10) | Hidden right (of 16) | Wrong answers without a warning |
|---|---|---|---|
| Before step 2 | 5 | 6 | tuning 2, hidden 6 |
| Step 2 (neutral instructions) | 6 | 4 | tuning 1, hidden 3 |
| Step 3 (idioms) — withdrawn | 3 | stopped (0 of 2) | tuning 6 |
| Step 4 (data loading; 9 of 10 done) | 3 of 9 | queued | tuning 3 (1 warned) |

Goal of the plan: ≥ 90% right first time on the hidden set, no wrong answer without a warning, over three runs.
We are at 25–40%, and almost every wrong answer reaches the person unwarned.

## Issues

### 1. The measurement is too noisy to judge a step (the most urgent)

- One run per case. The same case swings from right to not built between runs with no relevant change: p07 was
  right under step 2 and not built under step 4; p08 right under step 3, not built under step 4.
- Scores of near-identical platforms range 3–6 of 10. A step changing ±2 cases cannot be told from chance.
- Many cases end at the 20-minute limit (hidden: 4 to 9 of 16). Part of it is the shared local LLM being slow,
  part is the Assistant going round in circles; the runs do not yet say which.
- Harness bugs found and fixed today: a what-if run scored instead of the plan (p07, p08); two hidden checkers
  and two tuning checkers that could not read the platform's real export (h11, h14, p03, p10).

### 2. Wrong answers reach the person without a warning (the most important for users)

Of all wrong answers measured today, one carried a warning. The plan's exit for step 5 is zero. Classes seen
(tuning, readable; the hidden ones are known only as counts of broken rules):

| Class | Cases | Caught by |
|---|---|---|
| A list of ALLOWED pairs loaded with default "allowed" — the list restricts nothing | p02, p04 (step 3, step 4) | step 5 check `as_default` (not deployed) |
| Pair data given one way round, read in one order | p06 | step 5 check `one_way` (not deployed) |
| Rules left out (69 violations) | p07 | none yet |
| A plan that does nothing (ships nothing, all demand unmet) | p10 | none yet |
| A number in the request the model never uses | possible in several | step 5 check `unused_numbers` (not deployed) |
| Corridor 1.2 m wide all the way to an entrance not enforced | p03, every run | none: platform gap |

### 3. Models not built in time

- p05 (ambulance) has never been built in any run.
- Hidden: 4 (base) to 9 (step 2) of 16 not built in 20 minutes.
- The cause per case (slow LLM, refusals repeated, send-backs) is in the platform's logs but not summarised.

### 4. Instructions are fragile

- Step 3 added ~2,000 characters and replaced written formulas with pointers: tuning fell from 6 to 3. The local
  model is sensitive to the instructions' length and wording; additions must sit beside what works, not replace it.

### 5. Platform gaps still open

- The layout rule does not hold a corridor of the full width all the way to an entrance (p03).
- The answer map does not carry placed items (the checker had to rebuild them from the decisions).
- Alternatives for unbounded integer decisions.

## The plan to do better

Ordered by what unblocks the rest. Each item: what, and how we know it worked.

### A. Make the measurement trustworthy (first, 1 day)

1. **Three runs per tuning case** for every step (≈ 3 hours a set), reporting right as mean and range per case.
   A step counts only if it moves the mean by more than the range.
2. **Split "not built" by cause** from the platform's own logs: LLM time per call, refusals by kind, send-backs.
   A small report per run folder (no hidden content: kinds and counts only).
3. **LLM headroom:** run the benchmark when nothing else uses the LLM, and record its latency per case, so a slow
   hour does not read as a worse platform.
4. Hidden set: three runs only at the end of a phase, never per step.

*Worked when:* the same platform measured twice gives tuning means within one case.

### B. No wrong answer without a warning (step 5, 2–3 days)

1. **Deploy the three checks already written** (`unused_numbers`, `as_default`, `one_way`) — image ready.
2. **Turn the clearest one into a repair, not only a warning:** a parameter loaded from a file with a constant
   `"value": 1` (a list) and default 1 gets default 0, with a note on the card. Neutral: true for any list.
3. **Add two general checks of the trial answer:** "the plan does nothing" (every decision zero, every demand
   unmet or the goal 0) and "a rule never binds and could be dropped without changing the answer" for rules
   the request states (rules left out show as requested limits never reached).
4. **Build twice and compare** (the plan's step 5): the model built a second time from the same request; two
   different goals on the trial → a warning. Costs one more LLM call per plan; try on tuning first.

*Worked when:* on three tuning runs, every wrong answer carries a CHECK THIS line.

### C. Build more often in time (2 days)

1. From A.2, the top causes of time lost; fix the top two (expected: repeated refusals of the same kind, and
   send-backs that do not say exactly what to change).
2. p05 traced end to end: why it never builds.

*Worked when:* "not built" falls to ≤ 1 of 10 on tuning over three runs.

### D. Step 3b, measured properly (after B)

Optional shortcuts beside the formulas (committed, fe687b8). Three tuning runs; kept only if the mean does not
drop.

### E. Platform gaps (in parallel, 2–3 days)

1. Corridor width all the way to an entrance in the placement rule.
2. Placed items on the answer map.

### F. Then the hidden set, three runs

Judge against the plan's bar: within a few points of tuning, ≥ 90% right, no unwarned wrong answer.

## Immediate next steps

1. Finish step 4 (tuning case 10 and the hidden set are running).
2. Deploy step 5 (the three checks) and measure with three tuning runs (A.1).
3. Write the cause-of-time report (A.2) from the step 4 and step 5 runs.
