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

## Thresholds are proposals
No baseline exists, so every number is a **proposal**
(`thresholds_status: proposed-unratified`, `ratification: null`). Until a commit fills
`ratification` (baseline run ids + who), the generator caps every profile at `experimental`.
Ratifying means re-deriving numbers from the first real baseline and bumping `gate_set_version`.

## Current output (CRF, `alpha1-full`)
PERSON/en and PERSON/ko are **experimental**: measured, but gates fail (EN/KO F1, ambiguous-name
precision, collision precision, startup), regression/adversarial gates are unmeasured, and thresholds are
unratified. See `reports/support/support-matrix.md`.
Failing proposed gates are information about the gap, not a verdict on the proposals themselves.
