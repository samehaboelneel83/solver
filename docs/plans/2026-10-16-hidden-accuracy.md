# Hidden-test accuracy (mission of 16 October 2026)

Baseline: tag `reliable-2026-10-15` (5576c40), image `solver-backend:reliable` (eeed56). Hidden set on it (15 Oct,
run `r3`): **4 right of 16, built 10, wrong without a warning 3, timeouts 8.**
Experiments live on branch `exp/hidden-accuracy` (from `release/reliable`); the tag and its results are not touched.

**How the hidden set is read.** Only through `python -m bench.phase1.blind` (per-case outcome) and the backend's
content-free log lines (seconds, token counts, finish reason, tool-call names and sizes, the refusal *templates*
with names masked). No hidden problem text, plan or expected answer was opened for this work. Where a cause needs
the formulation itself, it is reconstructed on the practice cases that show the same failure class, and the text
says so.

## 1. Baseline reproduction (Phase A)

| Run | Image | Right | Built | Wrong, no warning | Timeouts |
|---|---|---|---|---|---|
| 14 Oct (reliable-2026-10-14, text calls) | c37772 | 4 | 6 | 2 | 10 |
| 15 Oct `r3` (reliable-2026-10-15, native calls) | eeed56 | 4 | 10 | 3 | 8 |
| 16 Oct `rel15b` (same image, same settings, rerun) | eeed56 | 6 | 10 | 3 | 6 |

Settings in the live container: native tool calls (`LLM_TOOL_MODE=auto`), thinking off, `LLM_MAX_TOKENS=16384`,
`LLM_PLAN_MAX_TOKENS=32768`, temperature 0.2, 30 minutes a case, one case at a time.

**Determinism.** The model samples at temperature 0.2 with no seed, so a rerun is not the same run. The rerun of
the same image on the same settings read **6** right where the 15 Oct run read 4: h02, h07 and h14 went from
timeout to right, h12 from right to wrong (23 violations), h01 from wrong to timeout. Only h03, h06 and h15 were
right both times. **The baseline is therefore 4 to 6 of 16 (mean 5)**, and a change must beat that by more than
two cases in one run, or be measured in repeated runs, before it is called an improvement.

**Scoring fixes of 15 Oct (p02, p07).** Kept and covered by `backend/tests/test_bench_checkers.py` (4 tests, pass):
a decision keyed by a joined pair ("W01-C001"), keys in another order, a joined key outside the sets (not taken),
and the generators' output not mistaken for their on/off. The hidden checkers are not changed by this work.

## 2. The 16 hidden cases (Phase B)

From the blind result of `r3` and the log (`python -m bench.phase1.latency`, plus a count of refusals by template).
"Plans" are whole plans the model sent; "string plans" are reads of a plan sent as a JSON *string* (native calls)
rather than an object; "no-model refusals" are send-backs that said the plan had no `ir`; "runaways" are replies
that ran to the 16,384-token limit with no tool call. The category of a hidden case is not read.

| Case | Outcome | Ended at | Min | Built | Solved | Right | Plans | String plans | No-model refusals | Runaways | Root cause (evidence) | Intervention | Regression test |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| h01 | wrong, no warning (1 violation) | solved | 12.0 | yes | yes | no | 7 | 0 | 0 | 0 | a rule of the problem missing or weaker in the model (built first try, no refusal points to it) | modeling checks (Phase D) | - |
| h02 | timeout | refusal loop | 30.0 | yes | no | no | 67 | 20 | 9 | 0 | 66 send-backs in 30 min; broken plan strings answered "has no ir" and resent | E1 | `test_spec_json.py` |
| h03 | right | solved | 14.2 | yes | yes | yes | 16 | 0 | 0 | 0 | - | - | - |
| h04 | wrong, no warning (2 violations) | solved | 6.7 | yes | yes | no | 9 | 0 | 0 | 0 | modeling (as h01) | Phase D | - |
| h05 | timeout | never built | 30.1 | no | no | no | 33 | 10 | 4 | 1 | slow convergence (33 send-backs, 14 "does not build") plus broken strings | E1, E2 | `test_spec_json.py`, `test_reply_cap.py` |
| h06 | right | solved | 3.0 | yes | yes | yes | 5 | 0 | 0 | 0 | - | - | - |
| h07 | timeout | never built | 30.0 | no | no | no | 28 | 15 | 6 | 0 | broken strings; slow replies (median 33 s) | E1 | `test_spec_json.py` |
| h08 | wrong, no warning (5 violations) | solved | 8.2 | yes | yes | no | 9 | 0 | 0 | 0 | modeling (as h01) | Phase D | - |
| h09 | timeout | built, not solved in time | 30.0 | yes | no | no | 14 | 23 | 8 | 1 | broken strings; slowest replies (median 41 s) | E1, E2 | as h05 |
| h10 | timeout | never built | 30.1 | no | no | no | 3 | 0 | 0 | 4 | four runaways, about 900 s of 1,384 s model time | E2 | `test_reply_cap.py` |
| h11 | timeout | never built | 30.0 | no | no | no | 18 | 0 | 1 | 4 | four runaways (about 900 s) and 18 send-backs | E2 | `test_reply_cap.py` |
| h12 | right | solved | 22.6 | yes | yes | yes | 23 | 0 | 0 | 0 | - | - | - |
| h13 | timeout | never built | 30.1 | no | no | no | 7 | 0 | 0 | 4 | four runaways (about 900 s) | E2 | `test_reply_cap.py` |
| h14 | timeout | never built | 30.0 | no | no | no | 21 | 0 | 0 | 1 | slow convergence: 21 send-backs, 13 "does not build" | none yet | - |
| h15 | right | solved | 16.0 | yes | yes | yes | 11 | 23 | 10 | 0 | right despite 10 no-model refusals | E1 (time) | - |
| h16 | wrong, warned (3 warnings) | solved | 13.2 | yes | yes | no | 14 | 0 | 0 | 0 | modeling; the card warned | Phase D | - |

String plans can exceed whole plans because the same string is counted on each read of the history.

**Silent wrong answers (h01, h04, h08).** All three built at once, had no refusal of note, and finished early (7 to
12 minutes). The violations are of the problem's own rules. Their formulations were not opened. The same class on
the practice set (R3, 15 Oct): p05 and p10 optimized a different goal, p07 left the battery capacity out, p02 let
pairs that were not approved through. Each is a rule of the text missing or weaker in the model; none is a solver
fault.

## 3. Where the time goes (Phase C)

`r3`, all 16 cases: 482 replies, **model time 15,419 s of 20,312 s wall (76%)**, reply median 21 s, p90 55 s; 285
whole plans; 267 send-backs; 15 replies cut at the length limit. The server writes about 80 tokens a second and
reads about 5,800.

- **Runaway replies.** Over the whole 15 Oct log (practice and hidden), 27 replies ran to the 16,384-token limit with
  no call, 210 to 240 s each, prose of 54,000 to 77,000 characters. 15 fall in the hidden run, 12 of them in h10,
  h11 and h13. After a single runaway the next reply (the same step again) usually succeeded; chains of two to four
  happened in five places. Of 1,337 replies that finished, 7 wrote more than 8,192 tokens (p99 6,256), each long
  prose before a plan; the plans themselves fit in 8,192.
- **Refusal loops.** h02 spent its 30 minutes on 67 plans and 66 send-backs.
- **Elsewhere the cost is many ordinary replies**, not long ones: median reply 21 s.

## 4. The "plan has no ir" defect (Phase E)

The log of `r3` shows the shape of every plan argument (`assistant.spec_shape`, keys and type, never content). With
native tool calls the model sometimes sends `spec` as a JSON string of 4,000 to 10,000 characters that does not
parse ("Expecting ',' delimiter" 15, "Expecting property name" 7, "Extra data" 2). The platform could not read it,
found no `ir`, and answered "the spec has no ir"; the model, told its plan had no model, resent the same string
(once the same 5,163 characters four times). 38 such refusals in the hidden run, in h02, h05, h07, h09, h11 and h15.

The slips, as seen on practice runs: a closer of the wrong kind (`]` for `}`), a closer doubled, a closer dropped,
a rule closed early.

**E1 (commit 9ee0083 on `exp/hidden-accuracy`).** The JSON mender also tries swapping a closer's kind; a string that
still does not parse is refused with the JSON error, its position and the text around it, never "has no ir".
On the gold practice models with the evidence's slips put in (`python -m bench.phase1.mend_rate`):

| | Restored exactly | Different but valid JSON | Not mended |
|---|---|---|---|
| Before E1 | 74 of 114 (wrong kind 21 of 38) | 32 | 8 |
| After E1 | 91 of 114 (wrong kind 38 of 38) | 23, every one refused by the model contract | 0 |

No slip is mended into a different model that the contract accepts. Tests: `backend/tests/test_spec_json.py`
(13 pass): every slip restored or refused; the refusal names the JSON fault; the fold of earlier calls never
raises; valid object, valid string, copied placeholder and plan without `ir` behave as before; the Assistant's own
plan path. A legitimate plan with no model (a dict without `ir`) is still refused as having no model.

## 5. Interventions

| Id | Hypothesis | Category | Commit | Tests |
|---|---|---|---|---|
| E1 | Hidden cases lose time in a loop where broken plan strings are refused as "has no ir"; naming the JSON fault and mending wrong-kind closers ends the loop | IR defect, timeouts | 9ee0083 | `test_spec_json.py`, 13 pass |
| E2 | Runaway replies cost about 220 s each and cluster in three timeouts; capping every reply at 8,192 tokens halves that cost and touches 7 of 1,337 finished replies | timeouts | see section 6 | `test_reply_cap.py`, 5 pass |

E2 first considered skipping the immediate retry after a runaway (thinking is already off, so the "retry without
thinking" is the same request). The log refuted it: after a single runaway the retry usually succeeded, so
skipping it would only replace one reply with another. It was not done.

## 6. Results

### exp1 (E1 + E2 + D1; image dbd155, commit 1efa04d), hidden run, first ten cases

Right: h03, h06, h07 (3 of 10; the baseline runs had 3 and 4 of the same ten). The JSON-fault refusal of E1 was
sent 12 times. **All 27 replies cut at the new 8,192 limit had no call and were loops**, by their logged shape:
11 to 121 distinct lines of 164 to 334, the last 200 characters seen 11 to 46 times. Each cost about 107 s
(before: about 220 s), but there were more of them: 10 in h09, 7 in h10, 6 in h05, all three timeouts.

**E3 (commit 8e38bef)**, from that evidence: replies are streamed, and one whose last 200 characters have already
been written four times (from 4,000 characters on) is stopped there and handled as a reply cut at the limit.
Tests: `backend/tests/test_reply_loops.py` (a loop is stopped before 8,000 characters; an 800-row reply that
does not repeat is kept whole; no gold model written out as pretty-printed JSON trips it at any length; a
streamed tool call is joined from its pieces; with the setting off nothing is streamed). Checked live against the
model server: a streamed tool call and a streamed text reply read back whole.

### Hidden results so far (`python -m bench.phase1.blind`)

| Run | Image | Right | Built | Wrong, no warning | Timeouts (30 min) | Ended early, not built |
|---|---|---|---|---|---|---|
| r3 (baseline, 15 Oct) | eeed56 | 4 | 10 | 3 | 8 | 0 |
| rel15b (baseline rerun) | eeed56 | 6 | 10 | 3 | 6 | 0 |
| exp1 (E1+E2+D1) | dbd155 | 5 | 10 | 3 | 6 | 0 |
| exp2 (+E3) | 9f2d19 | 5 | 9 | 3 | 2 | 5 |
| exp2b (exp2 again) | 9f2d19 | 6 | 13 | 5 | 2 | 3 |

exp2 over two runs: mean 5.5 right (baseline 5), built 11 (baseline 10), timeouts 2 (baseline 7), wrong without a
warning 4 (baseline 3). In exp2b h01 was solved to optimality but the driver found no "alternatives" button, so
the checker could not read the plan; it counts as not right (a harness gap, not read further: the case is hidden).
More plans now get built in time, and more of the extra ones are wrong: the remaining limit is the model's
formulation, not time.

Practice (one case at a time, 30 min): exp2 read 5 right of 10, built 9, 2 wrong without a warning (R3 runs of the
baseline: 5, 8, 4). Neither experiment is outside the baseline's spread.

**What exp2 showed.** E3 works as built: 52 replies were stopped as loops, after a median of 30 s (before: 107 s at
the 8,192 cap, 220 s at 16,384). Timeouts fell from 6-8 to 2. But five cases now ended early without a plan
(h05, h09, h10, h14, h15): their turns ended on the platform's own stops, and the test driver stops after three
"continue"s. By the turn log: 9 of 16 cases ended at least one turn on "the same refusal three times" or "my
replies kept running too long". Two causes, both from the evidence:

- **h15** (right in both baseline runs) ended four turns on "the same refusal three times", and every one was the
  E1 JSON-fault refusal: three *different* slips, the digits masked, read as one refusal. Before E1 the broken
  string was answered "has no ir", which the stop never counted, and the model got there in the end.
- After a reply stopped as a loop, **the same request again looped 25 times of 52**; the faster stop meant the
  rambling stop came within minutes.

**E4 (commit d295f35).** A JSON-fault refusal counts as "the same" only when the same string comes back (the same
fault at the same character). The replies right after a runaway are sampled at temperature 0.7
(`LLM_LOOP_TEMPERATURE`; 0 keeps the usual 0.2); every reply's log line now carries its temperature. Tests:
`backend/tests/test_e4_stops.py` (4 pass: different slips do not end the turn; the same broken string three times
still does; the replies after a runaway are at 0.7 and the next ordinary one back at 0.2; 0 keeps 0.2). The
assistant's test files, 255, pass.

exp3 = exp2 + E4 (image 8e91ce): queued after exp2's repeat, on the hidden set twice and the practice set once.
