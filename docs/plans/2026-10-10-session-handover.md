# Session handover — 10 October 2026

For whoever picks this up next. It covers one working day: what was found, what was changed, what
is proven, and what is still open. The older, platform-wide record is [`handover.md`](../../handover.md)
(as of 26 September); this file does not repeat it.

## 1. State in one paragraph

- **Repository:** `D:\solver`, branch `main`, pushed. GitHub `origin/main` is at `5e12092` and equals
  the local branch. There is no `master` any more.
- **Live stack:** backend, workers and frontend run the code of `16e794c` (the merge `5e12092` changed
  no file). No migration was added today; the head is still `0121`.
- **Full check:** `scripts/check.sh` passed all 8 steps on `3835f84` (3,473 frontend tests, 5,544
  backend tests). It has **not** been run in full on the commits after that; their own test files pass
  (289 Assistant-related backend tests, the assistant panel's frontend tests).
- **In flight when this was written:** an evaluation of the Assistant, detached inside the backend
  container (section 6 says how to read it).

## 2. The question the day was about

"When can we depend on the platform alone?" The answer reached:

| Part | Dependable alone? | Why |
|---|---|---|
| Solving a given model: the answer, the proof, the independent check, the cost breakdown | **Yes** | No language model is involved; the full check is green. |
| Models built in the Model editor, from templates or forms | **Yes** | No language model is involved. |
| A problem described in words to the Assistant (local model `qwen3.5`) | **Not yet** | It builds a wrong model in a share of runs; see section 5. |

Working rule until the Assistant passes a fixed case set repeatedly: let it draft, read the plan
card's "As built" read-back and its TRIAL and CHECK THIS lines before approving, and sanity-check any
result that matters against a number already known.

## 3. What was changed

Every item is committed; the commit is the one that did it.

### 3.1 Work found uncommitted from an earlier web session

| What | Commit |
|---|---|
| Assistant repairs from the first Nile Juice trace: the spec read wherever the model put it, brackets mended, pasted CSV rows read as given numbers, a goal's parts by decision | `7be4c0e` |
| The model as a QUBO: export route, `qubo-anneal` backend, downloads on the run page | `23a691b` |
| Rules learnt from past plans: `learned-rules` route, "Rules your past plans kept" in the Model editor | `e83c685` |

The web session had pushed the same work as seven commits of its own; the merge `5e12092` joins the
two histories. The early work therefore appears twice in the log. The tree is unaffected.

### 3.2 The Assistant: fewer refusals, and none shown as errors

| What | Commit |
|---|---|
| `ir` written beside `spec` is taken as part of it (the cause of the first trace's "came back 3 times") | `c236606` |
| Values for a parameter only the IR declares get the seed's declaration; `"default": 0` on a sum is dropped; self-corrected steps stay folded as "corrected automatically" instead of red boxes | `18dcb6a` |
| A product or sum of one part is that part; a stray backslash (`$\ge$`) is read as a backslash; the stop's "Technical detail" is a closed fold, not raw tags | `fffecc1` |
| Export links (PDF, CSV, spreadsheet) in the Assistant's written answer download the file with the user's sign-in | `ae90c71` |
| The goal breakdown on the run page keeps units and two decimals for large values | `4017885` |

### 3.3 Guards against a wrong model

| Guard | What it does | Commit |
|---|---|---|
| Trial with no answer | A plan whose trial solve is infeasible or unbounded is not shown: it goes back to the Assistant, at most twice, with the rules that cannot hold together | `174185a`, `2183705` |
| Conflict by record | A proven-smallest conflict of at most six rows names its records ("c_balance at BR1L, W01") | `2183705` |
| Shape check: a decision that can never help | Raising it never improves the goal and only tightens its rules, so a term is on the wrong side | `16e794c` |
| Shape check: data given and never read | A number field or parameter with values that nothing in the model names | `16e794c` |

The two shape checks (`backend/app/solve/lint.py`) read only the model's structure, so they apply to
any problem. A flagged plan goes back to the Assistant once; unchanged, it is shown with "CHECK THIS"
lines. On the 19 models the Assistant built today they flagged the two wrong ones and none of the 17
others. The never-read check stays quiet for an order (1, 2, 3), a coordinate, numbers that reach the
model as constants or through a parameter it reads, and models with a placement or route rule; the
third of these means it can miss a truly ignored field.

**Not caught by anything:** a wrong model in which every decision can help and all data is read (a
rule too loose, a wrong coefficient).

### 3.4 Tests, the full check and the nightly

| What | Commit |
|---|---|
| Numbers written with Latin digits in the 11 files that used the machine's locale (four tests failed on this Arabic-locale machine; users with an Arabic browser now see 12, not ١٢) | `856f01d` |
| Test setup clears the machine's `SOLVE_*` limits from `.env`; the stochastic test holds the code's own minimum; the suite self-check judges only its own case; the egress script no longer passes `-o /dev/null` to a native curl | `3835f84` |
| Nightly: checks `main` (it still named `master`), clears its stale worktree folder, and writes a clear failure when no worktree can be made | `998a72e`, `bc682bd` |

The test image `solver-backend-test` was rebuilt today; it had been two weeks old and lacked NetworkX.

## 4. The Assistant check

`backend/bench/assistant.py` sends a described problem to the live Assistant as one message, approves
its plan as a person would (a plan whose trial says "NO answer exists" is sent back instead), answers
"continue" at most three times, and compares the solved goal with a known answer.

```
docker compose exec -T -w /app backend python -m bench.assistant --runs 3 --minutes 15
```

| Case (`bench/assistant_cases/`) | Kind | Known answer |
|---|---|---|
| `nile_juice` | multi-period production with changeovers | 116,235 |
| `delta_pharma` | which warehouses to open | 189,900 |
| `ward_roster` | nurse roster | 14,370 |
| `feed_mill` | blending under percentage limits | 3,937,795.79 |

Each known answer comes from an independent SciPy model written from the problem's words
(`.agent_tmp/<name>/reference.py`, not committed). Each run uses the local language model and leaves a
"bench …" workspace on the live platform.

## 5. Evidence so far

**In the browser** (headless Chrome driving the Assistant panel; scripts and screenshots in
`.agent_tmp/delta`, `.agent_tmp/roster`, `.agent_tmp/feed`):

| Problem | Result |
|---|---|
| Delta Pharma | Run 1 never built (12 minutes, three "continue"s); after `fffecc1`, built and solved in 2 minutes, 189,900 |
| Ward roster | Built and solved first time in 4 minutes, 14,370 |
| Feed mill | Built and solved first time in 7 minutes, 3,937,795.79; its first plan had no answer and was sent back before being shown |

**Through the check, before the shape checks existed** (7 runs; the run stopped at an hour):

| Problem | Runs | Right first time | Built wrong | Not built |
|---|---|---|---|---|
| Delta Pharma | 2 | 2 | 0 | 0 |
| Ward roster | 1 | 1 | 0 | 0 |
| Nile Juice | 2 | 1 | 1 | 0 |
| Feed mill | 2 | 0 | 0 | 2 |

The wrong Nile Juice model was built first time and "proven optimal" at 122,826 against a true
116,235: the opening stock was never read and overtime was written where it uses hours up. Nothing
warned at the time; both shape checks now flag that exact model. Across all of today's runs Nile Juice
was right in 3 of 6.

## 6. In flight and open

| Item | State | Next step |
|---|---|---|
| Evaluation after the shape checks (4 problems × 2 runs, 15-minute cap) | Running detached in the backend container when this was written; one run done (Delta Pharma, right, 2 minutes) | Read `/tmp/assistant-eval2.log` and `/tmp/assistant-eval2.md` in the backend container. A container restart loses them. |
| Whether the shape checks make the Assistant fix the model | Unproven: they were verified on stored wrong models, not yet seen in a live run | The evaluation above is the first evidence |
| Feed mill reliability | Passed once in the browser, failed both check runs (one took 42 minutes) | Read those conversations for what was sent back; repair what repeats |
| Nightly | Fixed, but no whole night has run on the fix | Read `backend/bench/nightly_results/LATEST` after 03:00 |
| Full check on today's later commits | Not run | `SOLVER_BACKEND_IMAGE=solver-backend-test bash scripts/check.sh` (about 40 minutes) |
| Tool calls written as plain text by the model | Seen in the first trace; nothing was changed for it | Needs a trace that keeps the raw text |
| Half-second start-up of every small HiGHS solve | Left alone; it slows anything that does many small solves | Measure before changing |
| Bench and trace workspaces on the live platform ("bench …", "Nile Juice bottling", "Delta Pharma distribution", "Ward 4 roster", "Sinai feed mill") | Left in place | Delete when no longer wanted |

**The bar proposed for "the Assistant is dependable"** (not yet agreed): 10–15 real problems with
known answers, each run three times, at least 90% built first time with the right goal, and no wrong
answer reaching a person without a warning; the check run nightly.

**A decision that is the owner's:** a stronger language model would cut the Assistant's errors more
than any repair, but conflicts with the standing decision that tenant data stays on the platform.

## 7. Working notes

- **The test image goes stale.** Rebuild `solver-backend-test` (`docker build -t solver-backend-test
  backend`) whenever `backend/requirements.txt` changes.
- **Tests must not read the machine's settings.** `.env` sets the live workers' `SOLVE_*` limits;
  `tests/conftest.py` now clears them.
- **`check.sh` on Windows turns path conversion off** (`MSYS_NO_PATHCONV=1`), so a native program
  given `/dev/null` or `/app` as an argument takes it as a path on the drive.
- **A long job must not hang on the session.** A background command here is cut at one hour; run it
  detached in the container (`docker compose exec -d … > /tmp/x.log`) and read the log.
- **Web sessions and this checkout share one tree.** They hot-patch the live containers and may push
  their own commits of the same work: fetch before pushing, and check what is live
  (`docker compose exec backend python -c "import …"`) before assuming a deploy is owed.
- **GitHub is intermittently unreachable from this machine;** a fetch or push that fails to connect
  usually works on a retry.
- **Disk:** D: has about 4 GB free and C: about 17 GB. Run `docker image prune -f` after every build.
