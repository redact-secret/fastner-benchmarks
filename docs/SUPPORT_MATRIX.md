# Support Matrix and Provisional Gates

Gates: `policy/support-gates.json` (gate set 0.2.0, adds a collision-precision gate). Generator: `fnbench/support.py`.
Output (generated, never edited): `reports/support/support-matrix.{json,md}`.

## Status vocabulary
| Status | Meaning |
|---|---|
| `unsupported` | No selected architecture, or nothing measured for the profile. Means "no evidence", not "bad". |
| `experimental` | A candidate is measured for the profile, but a gate fails/is unmeasured, the architecture is not promoted via ADR, or the gate set is unratified. |
| `provisional` | Architecture promoted (fastner ADR recorded), pins resolved, **every** gate passes, gate set ratified against a real baseline. |
| `stable` | Not reachable at Alpha; the generator never emits it. Needs `stable_enabled`, a measured holdout, ≥2 consecutive passing requalifications, CI-enforced budgets. |

Support is derived from `promotion decision + measured artifacts + gates`. Intent to ship
changes nothing. Nothing can be hand-set.

## Gates (PERSON/en and PERSON/ko)
Per profile: language F1 on the public snapshot; ambiguous-name precision; unseen-name recall;
language-slice F1 on the regression corpus; language-slice precision on the adversarial corpus;
and shared budgets: latency p95, throughput, startup, peak memory, model size, runtime binary
size, WASM size. A gate with no measurement is `unmeasured`, never pass and never fail-as-zero.

## Thresholds are ratified as Beta targets (gate set 0.3.0)
The numbers were first proposals. They are now **adopted unchanged as the targets Beta must reach**
(`thresholds_status: ratified-as-beta-targets`; baseline runs, ratifier and limits are recorded in
`policy/support-gates.json`). They were not fitted to the baseline: CRF fails most quality gates, which
is the Beta backlog. Without a `ratification` record the generator still caps support at `experimental`.
Re-ratify, with revised numbers if needed, when a protected holdout exists and before any move toward stable.
Gates on the tiny product corpora show their slice size (`n=`, flagged low-n under 50 cases).

## Current output (CRF)
PERSON/en and PERSON/ko are **experimental**: promoted architecture, ratified gates, every gate measured,
but several fail (EN/KO F1, ambiguous-name precision, collision precision, adversarial precision, startup). See `reports/support/support-matrix.md`.
Failing proposed gates are information about the gap, not a verdict on the proposals themselves.
