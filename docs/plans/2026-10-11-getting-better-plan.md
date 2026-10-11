# Getting better — the plan from tonight's evidence

**11 October 2026, late.** Three tuning runs of the same image (step 5: the checks, repairs and send-backs of
the day) read 3, 5 and a weaker third, with 3 cases per run not built and 3 per run wrong without a warning.
Every loss tonight belongs to one of three classes, and each class has a lever. This plan orders the levers by
what they recover per day of work, with a target for each, and feeds the two plans it sits between
(`2026-10-11-issues-and-plan.md`, `2026-10-11-build-protocol-plan.md`).

**Where we are (the tuning set, 10 small cases, one image):** right 3–5 of 10; built 7–8; wrong without a
warning 3; not built 2–3, every one lost to time, not to a refusal.

**Where we want to be, in order:** not built ≤ 1 of 10 → wrong unwarned 0 → right ≥ 7 of 10 on the tuning mean
→ the hidden set within a few points of that, three runs. The neutrality plan's "done when" stays the bar.

---

## Lever 1 — Stop losing cases to time (this week; target: not built ≤ 1 of 10)

Every unbuilt case tonight was a reply past the 7-minute cap, or a send-back that made the model rewrite the
whole plan (two of those and the 20 minutes are gone). Three changes, all general, no new model knowledge:

| # | Change | Where | Verified by | Target |
|---|---|---|---|---|
| 1.1 | **Send back a patch, not a plan.** The platform keeps the last proposed spec as the draft; a send-back names the rules at fault and asks for those rules only (`patch_plan({rules: [...], goal?})`); the platform merges them onto the draft, canonicalises, re-checks, and the card follows. The old full `propose_plan` stays. | `app/agent/core.py` (`_check_plan`, a `patch_plan` tool), `app/agent/draft.py` (new) | corpus: a gold with one rule broken, sent back, patched by a scripted reply, reaches its reference; browser: p02 and p08 no longer time out on send-backs | a re-plan reply ≤ 3,000 characters |
| 1.2 | **A shorter reply cap, re-asked shorter.** 4 minutes (12,000 tokens at this model's rate -- more than any right plan tonight needed) instead of 7; the cut reply is asked again at half the room, as today. | `LLM_REPLY_SECONDS` default 240; `SLOW_REPLY` | the `causes` table: "slow" ends no case | one slow reply costs 4 minutes, not 7 |
| 1.3 | **Ask the pasted tables' questions of the platform, not the model.** The Assistant spends turns reading files it was just given; the load report already answers them. The first-message brief lists each table's columns and totals once, so the model loads, not reads. | `files.outline` already does this; check it is in the first message after `_attach_pasted` | the `causes` table: fewer turns before the first card | first card ≤ 4 minutes on cases with pasted data |

## Lever 2 — No wrong answer without a warning (this week; target: 0 on the tuning mean)

Tonight's three unwarned wrong answers per run are three known classes:

| Class seen | Case | Check | Status |
|---|---|---|---|
| a decision used on a pair the data gives no value for (a product on a machine with no time) | p04, every run | `used_without_data` on the trial | built, queued for the next image |
| a rule of the request left out | p07 | the request's sentences mapped to rules; an unclaimed rule sentence is a CHECK THIS | Phase 3.2 of the build-protocol plan; the mutation table shows it is the only large gap left (18 of 19 misses) |
| a penalty term that swamps the goal (a goal of −5,000,000 against a reference of 3,400,000) | p05 | **new:** when one goal term's contribution is ten times the others' combined, the card says which term decides the goal and which barely count | to build: `app/agent/result.py` / `breakdown.py` already split the goal by term; one line on the card |

Plus the two found in run 1 and already fixed in the working tree (the layout's cells-as-metres false warning;
the term written with `over` and no `sum`). **Exit:** three tuning runs of the next image with 0 wrong unwarned.

## Lever 3 — Judge every change in an hour, not an evening (this week)

Already in place from tonight: 8 gold models (8 of 8 at their references, no model, no database, one minute)
and the mutation table (52 caught, 27 harmless, 19 missed, 0 false alarms). To finish Phase 0:

| # | Change | Target |
|---|---|---|
| 3.1 | parallel browser runs, three cases at once (`run_parallel.sh`) | a 10-case set in ≤ 1 hour; three runs in an evening |
| 3.2 | golds for p05 and p08 once a right run exists (p05 builds now; p08's wrong model is caught, the right one is one send-back away) | 10 of 10 golds |
| 3.3 | hidden golds captured blind from right runs | the corpus covers the hidden set without anyone reading it |
| 3.4 | `gold check` + `mutate` in `scripts/nightly.sh`; a red night blocks a deploy | the corpus is the first gate |

**Rule from here:** no image reaches the browser measurement before `gold check` is 100 % and `mutate` shows no
new false alarm; no image reaches the hidden set before three tuning runs.

## Lever 4 — The structural fix: build in stages (weeks 2–3)

Lever 1 buys time inside today's one-shot design; the staged protocol removes the one-shot design. Phases 1–3
of `2026-10-11-build-protocol-plan.md`: one canonical form for every repair (fixed point on the golds), the
constructs library (the model selects and fills, never hand-writes the algebra), then `stage_data` →
`stage_decisions` → `add_rule` one sentence at a time → `stage_goal` → `propose_plan` with no spec. Each stage is
a small reply checked on arrival; the sentence-to-rule mapping closes the last mutation gap; the card shows the
request on the left and the model on the right.

**Target at the end of Phase 3:** tuning mean ≥ 7 of 10, 0 wrong unwarned, ≤ 1 not built, no case over 12
minutes of model time; then the hidden set, three runs, read blind.

## The order, and what each week ends with

| When | Do | Ends with |
|---|---|---|
| Tonight → tomorrow | finish step 5's three runs and its hidden run; record. Build 1.1, 1.2, the penalty check (2); assemble the next image with the six queued fixes | the next image, corpus-green |
| Day 2 | three tuning runs of the next image, in parallel (3.1) | not built ≤ 1, wrong unwarned 0 on the mean -- or the gap list of what remains |
| Day 3 | the hidden set on it, once; golds and mutations extended (3.2–3.4) | the hidden reading for the record; the corpus nightly |
| Week 2 | Phase 1 (canonical form) and Phase 2 (constructs) | `canonical(gold) == gold`; every hard rule of every gold a construct or a plain rule |
| Week 3 | Phase 3 (the protocol) | tuning ≥ 7, then the hidden set three runs |

## What does not change

Domain-neutral (the build check), general (shape, never a name), isolated (the model and the tiles inside;
nothing calls out), one image per measurement, nothing deployed during a hidden run, every change through the
corpus before the browser.

## Progress

- **11 Oct, 23:40 — 1.1 built.** `app/agent/draft.py`: a `propose_plan` with only what changes (rules by id,
  `{"id", "drop": true}` to remove, a goal, a decision) is completed from the last plan proposed, folded from
  the conversation's own calls (nothing held between turns; the browser's round trip carries it); every
  send-back now ends with how to patch instead of rewriting. 115 tests pass. Queued for the next image.
- **12 Oct, 00:00 — 1.2 built.** The reply cap's default is 240 s (was 420); a cut reply is asked again at
  half the room, as before. `LLM_REPLY_SECONDS` in `.env` still overrides. Queued for the next image.
- **12 Oct, 01:10 — lever 2's new check built.** A goal one term decides (its contribution ten times the
  others' combined) is a CHECK THIS on the card naming the term and its share, and a flag to the model; from the
  trial's own goal breakdown. 100 tests pass. Queued for the next image, which now holds: the no-data check,
  the `over`-without-`sum` repair, the cells-as-metres and attachment-count rules for unused numbers, the
  goal-sense check, the patch send-back (1.1), the 4-minute cap (1.2), and this.
