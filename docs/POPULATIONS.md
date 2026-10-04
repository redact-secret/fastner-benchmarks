# Qualification Populations

Source: `policy/populations.json`, validated by `fnbench/populations.py`.

A FastNER release never depends on one denominator. Five populations exist, each with its
own identity, provenance, artifact, and **role**:

| Population | Role | Owner | Status |
|---|---|---|---|
| `ner-evidence-public` | quality floor | ner-evidence | available: snapshot `person-en-ko-alpha.1-65b5a0970bfe` (545 cases), **not a holdout** |
| `fastner-regression` | regression gate | this repo | available (52 cases); measured for CRF (`run-fa7c74ef7884624a`) |
| `fastner-adversarial` | adversarial gate | this repo | available (37 cases); measured for CRF (`run-810f86b911170c68`) |
| `candidate-specific` | candidate diagnostic only | this repo | available (46 cases, origin `bakeoff-failure`); unmeasured |
| `protected-holdout` | holdout gate | external custodian | planned |

## Rules

- **No merged denominators.** `account_artifact` rejects any ner-eval artifact whose
  `corpus.id` is not exactly one registered population (`a+b` is rejected), and
  `combined_denominator()` always raises. Reports show one row/table per population.
- **Identity must match.** An artifact's `case_count` must equal the registered count and, when
  a snapshot digest is pinned, its corpus digest must match it.
- **Unpinned means unusable.** Artifacts against `pending-pin`/`planned` populations are
  rejected; they cannot qualify anything.
- **Roles are 1:1 with populations.** Role decides how a population contributes (floor, gate,
  diagnostic); it is not a weight.
- **Candidate-specific cases never feed shared gates.** They explain one candidate's failures.
- **Holdout** is `private-aggregates-only`: no text in this repo, custody recorded, and a
  no-training-leak attestation required before first use.
- **Provenance fields are mandatory**: source, license, synthetic, personal_data, custody.
  `null` is allowed only for populations that are not yet available.

## Public snapshot caveats (recorded in the registry, surfaced in every report)
- Not a holdout: FastNER candidates were not trained on it but were run against it three times across builds; FastNER numbers are likely optimistic relative to references never tuned against it.
- Project-authored synthetic text with no independent review; seen/unseen is a name-rarity proxy.
- `redistribution: internal-only`: this repo stores aggregates only.

## Debt
- Licenses for product corpora must be set before public release.
