# fastner-benchmarks

Product qualification and comparative benchmarking for FastNER.

> **Status:** Private architecture phase. Qualification policy 0.2.0. **CRF (architecture B) promoted**; product
> readiness **ENTER BETA** with support `experimental` (real `ner-eval` runs on the public snapshot and both
> product corpora). See `reports/qualification/`.

**Beta 1 qualification:** see `docs/BETA1_QUALIFICATION.md` and `reports/beta1/` (the Alpha 1 records under `reports/qualification`, `reports/support` are historical).

## Quick start

```bash
make validate                  # tests + checks that every generated output is current
python -m fnbench ingest       # real ner-eval run -> normalized aggregate-only artifacts
python -m fnbench report       # bakeoff report from policy + artifacts
python -m fnbench promotion    # promotion decision + ADR handoff for fastner
python -m fnbench support      # support matrix
python -m fnbench qualify      # qualification record + Beta-entry decision
python -m fnbench corpus       # rebuild product corpora from *.src.jsonl
python -m fnbench beta1-ingest # ner-eval Beta 1 plan -> artifacts/beta1
python -m fnbench beta1        # Beta 1 qualification (stages, support matrix, record)
```

Docs: `docs/QUALIFICATION_POLICY.md`, `POPULATIONS.md`, `BAKEOFF_CONFIG.md`, `ARTIFACT_CONTRACT.md`,
`PROMOTION_RULE.md`, `SUPPORT_MATRIX.md`, `QUALIFICATION_RECORD.md`, `corpora/README.md`.
Generated outputs live in `reports/` and are never hand-edited.

This repository is where FastNER-specific interpretation lives.

It consumes measurements from `ner-eval` and answers product questions such as whether a model is ready to ship, whether a candidate improves quality without unacceptable size/latency cost, which language/entity profiles are supported, what regressions block a release, and how FastNER compares with selected reference NER systems under the same protocol.

## Ecosystem boundary

```text
ner-evidence
    = canonical/shared NER evidence

ner-eval
    = model-neutral measurement

fastner-benchmarks
    = FastNER qualification + product policy + comparisons

fastner
    = runtime product
```

## What this repository owns

- FastNER qualification policy;
- candidate-vs-release comparisons;
- model promotion gates;
- product regression corpus;
- adversarial product corpus;
- protected/holdout integration where permitted;
- FastNER support matrix;
- release qualification reports;
- competitor comparison presentation;
- performance/size budgets for FastNER releases.

## What it does not own

- canonical public NER evidence;
- generic metric semantics;
- generic model adapter protocol;
- FastNER inference implementation;
- raw training corpus.

## Qualification populations

A FastNER release should not depend on one denominator.

Possible populations:

```text
public/shared ner-evidence snapshot
FastNER regression corpus
FastNER adversarial corpus
candidate-specific cases
protected/holdout corpus
```

Each population keeps its own identity and provenance. The benchmark layer decides how results contribute to qualification.

## Product objective

FastNER is not trying to maximize F1 at any cost.

Qualification should consider precision/recall/F1, ambiguous-name precision, unseen-name recall, latency, throughput, startup, memory, model size, runtime binary size, and WASM size where relevant.

A candidate can fail qualification by becoming too large or too slow even if F1 improves.

## Architecture bakeoff

The initial milestone should compare statistical, CRF/linear, compact neural, and tiny Transformer reference models. The selected architecture must be justified by measured tradeoffs.

## Competitive comparisons

Comparisons should use identical evidence where possible, pin exact model versions/artifacts, identify unavailable models honestly, separate accuracy from performance, and avoid one universal "best NER" score.

## Support status

A future support matrix may distinguish states such as `experimental`, `provisional`, `stable`, and `unsupported`. Exact vocabulary is not frozen.

Support status belongs here, not in `ner-evidence` or `ner-eval`.

## Public-release gate

Before public release:

- qualification policy documented;
- comparison methodology reproducible;
- peer model versions pinned;
- release reports identify exact FastNER/model artifacts;
- product-owned corpora have safe publication rules.
