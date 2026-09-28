# Guided problem forms — 28 September 2026

Open a problem, choose **Build model → Guided Form**, and use **Create with guided forms**.

## End-user workflow

1. **Decision variable:** give it a short identifier, choose yes/no, whole-number, or decimal values, select its dimensions, and enter optional bounds. Selecting dimensions also declares the required sets. Leave dimensions empty for one overall decision.
2. **Rule:** choose a decision and whether the limit applies overall or separately by selected dimensions. Other dimensions are summed. Choose at most, exactly, or at least; enter the limit; choose Required or Preference. Preferences require a positive integer penalty.
3. **Objective:** choose a decision total to minimize or maximize and a positive integer weight. Adding terms preserves the existing objective direction and combination mode.
4. Review the plain-language summary and exact representation. Create each item, edit it in the existing forms below if needed, then publish a new version.

The guided commands apply to the latest shared draft and preserve other model content. Names, bounds, references, scopes, penalties, and objective weights are checked before creation. The existing model validation and publication checks still apply.

## Current scope

These are guided creation forms for common numeric decisions, constant or parameter limits, and decision-total or parameter-weighted objectives. Advanced expressions, scheduling, routing, and other existing model constructs remain available through the detailed forms. The new panel does not claim to translate unrestricted natural language or provide a complete template library.

## Parameter forms follow-up

- Choose declared numeric parameters as rule limits (for example, daily capacity or demand).
- Optionally multiply each decision by a parameter before aggregation, supporting expressions such as `sum(cost[feed] * quantity[feed])` in rules or objectives.
- Each parameter dimension has a visible mapping to a decision dimension. A unique match is preselected; repeated/ambiguous set dimensions require an explicit choice.
- Limit parameters may reference only dimensions retained by the rule's `forall`; multiplier parameters are evaluated before the remaining dimensions are summed.
- Missing parameters, entity-valued parameters, wrong dimension order, stale mappings, and out-of-scope references are rejected before creation.
- Units are not inferred or converted automatically. Users must verify compatible units in domain data.
- Follow-up validation: 69 tests passed, including parameter semantics and form interaction; build and lint passed.
- Browser verified adding `feed_quantity[feed]`, declared `cost[feed]`, and `total_feed_cost = sum(cost[feed] * feed_quantity[feed])` to problem 191. The existing scalar variable, required rule, and first objective term remained intact. These follow-up changes are an unpublished local draft; version 276 remains unchanged. No solve was submitted.

## Verification

- 64 tests passed: guided command semantics, form interactions, and existing ModelEditor behavior.
- Generated model tested against the actual IR shape validator.
- TypeScript/production build and lint passed. The existing bundle-size advisory remains.
- Frontend deployed locally using compiled assets and an installed nginx image; image build networking disabled.
- Authenticated browser test created **Guided forms verification**, problem **191** in domain **5**.
- Forms created integer `staff_count` bounded 0–20, required `staff_count >= 3`, and objective `minimize staff_count`.
- Draft survived reload; publication succeeded as **version 1**, model version ID **276**.
- No solve was submitted. Existing planning problems were not edited.

Example: http://localhost:3010/domains/5/problems/191/model?problem=191&version=276
