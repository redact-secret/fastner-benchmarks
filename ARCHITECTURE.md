# Architecture

## 1. Purpose

`fastner-benchmarks` converts measurement into FastNER product decisions. It is intentionally downstream of the neutral evaluator.

## 2. Boundary

```text
ner-evidence snapshot -----------+
                                 |
FastNER regression corpus -------+
                                 v
                              ner-eval
                                 |
                                 | measurement artifacts
                                 v
                       fastner-benchmarks
                                 |
                      qualification policy
                                 |
                                 v
                       support / release decision
```

Competitor/reference models flow through the same measurement layer.

## 3. Qualification is multi-corpus

Do not silently merge all evidence into one denominator.

Each population preserves identity, provenance, case count, metric artifact, and intended qualification role.

Possible policy shape:

```text
public quality floor
+ no regression on product corpus
+ adversarial precision floor
+ performance budget
+ model-size budget
= promotable candidate
```

Exact thresholds must be data-driven and versioned.

## 4. Architecture bakeoff

The first major qualification task is model architecture selection.

Candidate classes:

```text
A statistical
B linear + CRF
C compact neural
D tiny Transformer reference
```

Required dimensions:

```text
entity F1
ambiguous precision
unseen recall
latency
throughput
startup
peak memory
model size
binary size
WASM size
```

A winner must come from the Pareto frontier, not F1 alone.

## 5. Support matrix

Support status should be generated from qualification artifacts.

Potential dimensions include entity type, language, model id, quality status, performance status, and artifact-size status.

Manual marketing claims must not override measured support state.

## 6. Regression corpus

The product regression corpus may contain safe synthetic cases derived from real bug reports, previously fixed boundary errors, performance regressions, Unicode/tokenization failures, and language-specific failures.

It is product-owned and distinct from canonical public evidence.

## 7. Protected/holdout evaluation

If holdout evaluation is used:

- keep it separate from training;
- record custody/provenance;
- publish only safe aggregates;
- avoid leaking cases into model development.

## 8. Competitor/reference models

Peer comparisons must pin model name, exact version/revision, artifact digest where practical, runtime, adapter, and configuration.

Do not compare against an unspecified "BERT NER" or "spaCy" installation.

## 9. Performance budgets

FastNER-specific budgets belong here: model artifact size, runtime binary delta, latency ceiling, throughput floor, memory ceiling, startup ceiling.

Exact numbers should be introduced only after baseline measurements.

## 10. Publication

Public artifacts should avoid raw sensitive text. Prefer metrics, case IDs, bounded diagnostics, and version/digest provenance.

## 11. Release record

A release qualification should identify FastNER runtime commit/release, model artifact digest, evidence snapshots, regression corpus identity, evaluator version, qualification policy version, peer model pins, and performance environment.

## 12. Public-release gate

Before public release:

- product policy versioned;
- peer pinning reproducible;
- support matrix generation automated;
- release reports reproducible;
- no product-private corpus content leaks into public artifacts.
