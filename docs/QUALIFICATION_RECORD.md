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

## Current result (CRF)
Architecture: `fastner-b-linear-crf` **promoted** (ADR-0002 accepted and on fastner main).
Product readiness: **A. ENTER BETA**. All nine entry criteria are met: the architecture is promoted, the
public snapshot and both product corpora are measured for CRF, every budget gate is measured, EN and KO
references are measured, and the gate thresholds are ratified as Beta targets.

Entering Beta is not a quality claim. Support stays `experimental`; the generated measured-deficit
backlog is the Beta plan: startup (re-measure in-process), collision and ambiguous-name false
positives, Korean particle and adversarial false positives, EN/KO F1, and the tokenization failures
seen on the product corpora. Evidence caveats (public snapshot is not a holdout, tiny seed corpora)
are carried into the generated record.
