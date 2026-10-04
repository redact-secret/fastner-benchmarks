# Qualification Populations

Source: `policy/populations.json`, validated by `fnbench/populations.py`.

A FastNER release never depends on one denominator. Five populations exist, each with its
own identity, provenance, artifact, and **role**:

| Population | Role | Owner | Status |
|---|---|---|---|
| `ner-evidence-public` | quality floor | ner-evidence | pending-pin (no immutable snapshot released yet) |
| `fastner-regression` | regression gate | this repo | created by #7 |
| `fastner-adversarial` | adversarial gate | this repo | created by #7 |
| `candidate-specific` | candidate diagnostic only | this repo | planned |
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

## Debt

- `ner-evidence-public` cannot be pinned until `ner-evidence` publishes a snapshot manifest.
  Tracked as a cross-repo handoff.
- Licenses for product corpora must be set before public release.
