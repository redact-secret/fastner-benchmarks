# Product corpora (FastNER-owned)

Separate from canonical `ner-evidence`. Never imported into it, never edited to fit model output.

| Path | Population | Purpose |
|---|---|---|
| `regression/regression.src.jsonl` → `.jsonl` | `fastner-regression` | realistic cases a release must keep passing |
| `adversarial/adversarial.src.jsonl` → `.jsonl` | `fastner-adversarial` | hostile/edge input: mixed script, Unicode, invisibles, casing, structured text |
| `regression/runtime-contracts.json` | companion (no denominator) | model-format and runtime requirements for fastner CI |
| `performance/workloads.src.json` → `workloads.json` | companion (no denominator) | reproducible workloads: spec + seed + content digest |
| `candidate/fastner-b-linear-crf/candidate.src.jsonl` → `.jsonl` | `candidate-specific` | 46 variants of failure classes CRF showed in ner-eval runs; never feeds shared gates; unmeasured until a ner-eval run uses it |

## Authoring
Edit only `*.src.jsonl` / `workloads.src.json`. Mark PERSON spans with `[[surface]]`; the builder
derives UTF-8 byte offsets. Then run `python -m fnbench corpus` and `python -m fnbench workloads`.
`make validate` fails if generated files are stale.

Each case needs: `category`, `origin`, `rationale`, and the seven slice keys
(`language, script, entity, difficulty, shape, collision, seen`) using ner-eval slice naming.
`seen=false` also needs `seen_basis`. `contested` marks expectations that must be aligned with
ner-evidence conventions once published.

## Origin and honesty
`origin` is `seed-taxonomy` (authored from known failure classes), `bakeoff-failure`, or
`production-bug`. Regression and adversarial cases are `seed-taxonomy` (authored before any model ran).
The `candidate-specific` cases are `bakeoff-failure`: each cites the ner-eval run and the failing parent
case it varies (verified against the ingested failure lists by a test), with new synthetic names and
words. They probe the failure class; they are not the failing cases. Non-seed origins require `lineage` (run id / bug ref).
When real failures exist, add the case, run neutral evaluation, then change support state
(CONVENTIONS.md "Regression handling"). Never edit expectations to match model output.

## Safe publication
Names are invented or generic; no real contact data. The validator rejects emails, URLs,
long digit runs and phone-like strings. Reports carry ids, counts and digests only, never case text.
