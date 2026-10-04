# FastNER Qualification Policy

Machine-readable source: `policy/qualification-policy.json` (version **0.1.0**, status `alpha-0`).
This document explains it; if they disagree, the JSON wins and this file is a bug.

## NO SINGLE UNIVERSAL SCORE

There is no composite, weighted, or "overall" FastNER score. The policy validator rejects
weights and dimensions named like aggregates (`overall_score`, `composite`, ...).
Candidates are compared as **vectors** and decisions are taken on the **Pareto frontier**
(`fnbench/pareto.py`).

Why: F1 can rise while the model becomes too big for WASM; a tiny model can win on size
while failing Korean. Any weighting hides that trade-off behind an arbitrary constant.

## Dimensions

| Group | Dimension | Direction | Source |
|---|---|---|---|
| quality | entity precision / recall / F1 | max | quality artifact, public snapshot, global |
| quality | ambiguous-name precision | max | slice `difficulty=ambiguous` |
| quality | unseen-name recall | max | slice `seen=false` |
| language | EN F1, KO F1 | max | slices `language=en`, `language=ko` |
| shape | single-token recall, multi-token F1 | max | slices `shape=single-token`, `shape=multi-token` |
| collision | worst collision-slice precision | max | min over slices `collision=*` |
| performance | warm latency p95, startup, peak memory | min | perf artifact |
| performance | batch throughput | max | perf artifact |
| size | model size, runtime binary size, WASM size | min | perf artifact |

Slice names follow the `ner-eval` slice engine (`key=value` derived from canonical case
metadata). This repo does not define metric semantics; it only reads the numbers.

## Rules

1. **Unavailable is never zero.** A missing or `unavailable` value makes a candidate
   *incomplete* on that dimension. Incomplete candidates are listed, not ranked, and cannot
   be dominated or dominate (`dominates()` returns false for missing values).
2. **Pareto, not rank.** The frontier is the set of candidates no other complete candidate
   dominates (>= on all dimensions, > on one). Choosing *within* the frontier is governed by
   the promotion rule (issue #6), not by a score.
3. **Performance numbers are environment-bound.** Perf artifacts carry an environment id;
   candidates are only compared when environments match.
4. **Slices are never averaged away.** EN and KO are separate dimensions so a global figure
   cannot hide a language regression.
5. **Thresholds are data, not code.** Numeric budgets are introduced only after baseline
   measurements exist (see `policy/` budgets once written) and are versioned with the policy.

## Versioning

Any change to dimensions, directions, sources, or the rules above bumps `policy_version`.
Every generated report and qualification record embeds the policy version it was produced
under.

## Known debt

- The `ner-eval` quality/perf artifact schemas are not frozen; `docs/ARTIFACT_CONTRACT.md`
  (added with #5) states what this repo assumes. Handoff: ner-eval should confirm or freeze.
