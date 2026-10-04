# First Candidate Qualification and Beta-Entry Decision

Criteria: `policy/beta-entry.json` (0.1.0). Generator: `fnbench/qualify.py`.
Output (generated): `reports/qualification/alpha1-qualification.{json,md}`.

## Outcomes
- **A. ENTER BETA**: every entry criterion met. The measured-deficit backlog becomes the Beta plan.
  Deficits are generated from measured failing gates (ranked by relative shortfall, a screening
  heuristic), each citing profile, gate, value, threshold and any measurement caveat.
- **B. REMAIN IN ALPHA**: at least one criterion unmet. The record lists prioritized *alpha
  blockers* with an owning repo and next action. Any measured deficits are still listed as a
  candidate backlog but nothing is scheduled.

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

## Current result (CRF, `alpha1-full`)
Architecture: `fastner-b-linear-crf` recommended; ADR accepted, pending merge.
Product readiness: **REMAIN IN ALPHA**. Unmet criteria: ADR on fastner main, regression and
adversarial corpora measured, gate thresholds ratified. The measured-deficit backlog (collision and
ambiguity false positives, EN/KO F1, startup) is generated from failing gates and listed as a
*candidate* Beta backlog; it does not mean Beta was entered.
