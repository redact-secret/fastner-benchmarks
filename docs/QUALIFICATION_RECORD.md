# First Candidate Qualification and Beta-Entry Decision

Criteria: `policy/beta-entry.json` (0.1.0). Generator: `fnbench/qualify.py`.
Output (generated): `reports/qualification/alpha1-qualification.{json,md}`.

## Outcomes
- **A. ENTER BETA**: every entry criterion met. Beta planning suggestions are generated from
  measured failing gates, ranked by relative shortfall, each citing profile, gate, value and
  threshold. Nothing else is suggested.
- **B. REMAIN IN ALPHA**: at least one criterion unmet. The record lists prioritized *alpha
  blockers* with an owning repo. No Beta 1 work is generated, because no measured deficit exists.

## Entry criteria
Architecture selected by the promotion rule; recorded as a fastner ADR; candidate pin
resolved; pinned public snapshot, regression and adversarial corpora measured; every budget
gate measured; each profile language has a reference that is measured or explicitly
unavailable with a reason; gate thresholds ratified against a real baseline.

Failing quality/budget gates do **not** block Beta (they are the Beta backlog). Missing
evidence does, because viability is then unproven.

## Record identity (ARCHITECTURE §11)
Runtime version/commit, model digest, evidence snapshot identity, product corpus content
digests and case counts, evaluator and metric-protocol versions, peer pins, performance
environment, policy and criteria versions.

## Current result
**REMAIN IN ALPHA.** All nine criteria are unmet: no `fastner` runtime/model, no `ner-eval`
artifacts, no released `ner-evidence` snapshot, and references unresolved. See the generated record.
