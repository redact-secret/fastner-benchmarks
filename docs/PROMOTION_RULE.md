# Architecture Promotion Rule (Alpha 0 → Alpha 1)

Source: `policy/promotion-rule.json` (rule 0.1.0), evaluator `fnbench/promotion.py`.
Output: `reports/promotion/<bakeoff>.decision.json` and `.adr-handoff.md` (generated).

## What it prevents

| Failure mode | Mechanism |
|---|---|
| choosing solely on F1 | size ceiling on model, binary and WASM (≤10× the smallest measured); Pareto frontier required |
| choosing solely on smallest model | quality floor (entity F1 within 0.10 of best), ambiguity floor |
| hiding a language regression in the global average | language floor: EN F1 and KO F1 each within 0.05 of the best candidate |
| ignoring huge binary/WASM cost | size ceiling covers `runtime_binary_size_bytes` and `wasm_size_bytes` |
| promoting on unmeasured data | all dimensions must be present; pins resolved; public snapshot measured |

Every guardrail is relative to the best/smallest *measured* candidate, so the rule needs no
invented absolute numbers. Initial gap/ratio values are **provisional defaults** and must be
re-derived from the first real baseline (changing them bumps `rule_version`).

## Procedure
1. Candidate needs a resolved pin and a complete vector on every policy dimension.
2. Candidate must be on the Pareto frontier.
3. Candidate must pass all four guardrails, or hold a waiver (`policy/promotion-waivers.json`)
   with a reason and ADR reference, per candidate and guardrail.
4. Outcomes:
   - `no-decision-insufficient-evidence`: nothing promotable can be judged yet.
   - `no-eligible-candidate`: improve candidates; do not relax guardrails to fit.
   - `recommend`: exactly one survivor, or several that are auto-resolvable by tolerance.
   - `needs-adr-decision`: survivors genuinely trade quality against size.
5. **Tie/tradeoff handling.** Survivors within 0.01 on every quality dimension are
   quality-equivalent → the one no larger on every size dimension. Survivors within 1.10× on
   every size dimension → the one no worse on every quality dimension. Anything else is a
   human tradeoff recorded in the ADR. The machine never picks by one dimension.

## ADR handoff
Promotion is **not effective** until a decision exists in `fastner` as an ADR. The generated
handoff lists decision, evidence, frontier, guardrail results, waivers, tradeoffs, known
deficits and requested actions. Once `fastner` records the ADR, add its reference to
`policy/promotion-adr-refs.json`; only then does `promotion_state` become `promoted`
(otherwise `recommended-awaiting-adr`).

## Current state
No measurements exist, so the decision is `no-decision-insufficient-evidence`; nothing is promoted.
