# Conventions

## Principle

This repository may interpret FastNER measurements. It must not rewrite evidence or evaluator semantics to make FastNER look better.

## Product policy

Qualification thresholds and promotion rules must be explicit, versioned, reviewable, and reproducible.

## Comparisons

Competitor/reference comparisons must use pinned model versions, pinned runtimes, identical corpus populations where possible, identical metric semantics, and explicit unavailable/unsupported states.

Never represent unavailable as zero.

## Reports

Every report should identify FastNER runtime version/commit, FastNER model artifact, evaluator version, corpus identities, qualification policy version, peer pins, and performance environment when relevant.

## Metrics

Do not publish one universal score when it hides important tradeoffs. Keep quality, ambiguity handling, unseen behavior, performance, model size, and memory visible.

## Regression handling

When a production bug is found:

1. create a safe synthetic regression case;
2. place it in the appropriate product corpus;
3. run neutral evaluation;
4. only then change support/promotion state.

Do not patch benchmark expectations to match current model output.

## Performance

Performance regressions require investigation even when accuracy improves. Record binary/model-size deltas for architecture changes.

## Generated output

Generated reports should not be hand-edited. Fix the source data or generator.

## Cross-repository boundary

Do not edit canonical evidence assumptions here, fork evaluator metric semantics here, or place FastNER runtime code here.

## Commits

Prefer messages such as:

```text
Add PERSON ambiguity qualification slice
Pin GLiNER comparison artifact
Record model-size release budget
Block promotion on Korean regression
```

## Public-readiness

Before public release, add required licenses, document peer-model licenses, publish reproducibility commands, separate public/protected artifacts, and verify no private corpus text is committed.
