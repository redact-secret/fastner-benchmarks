# ner-eval artifact contract (as consumed)

The earlier draft contract is replaced: `ner-eval` now emits real artifacts
(`ner-eval.artifacts/1`, run manifest `ner-eval.run-manifest/1`, measurement protocol
`ner-eval.match/1.1.0`, performance protocol `ner-eval.perf-protocol/1.1.0`, slices
`ner-eval.person-slices/2`). Their schema and metric semantics belong to ner-eval; this repo only reads them.

## Flow
```
ner-eval results/<run>/  --fnbench ingest-->  artifacts/bakeoff/<bakeoff_id>/{quality,perf}/<pin id>.json
                                              + ingest-manifest.json (source run id, ner-eval commit, file sha256)
artifacts/ --fnbench report/promotion/support/qualify--> reports/
```
`python -m fnbench ingest [--source ../ner-eval/results/alpha1-full]` verifies the run and writes
normalized, **aggregate-only** artifacts. `make validate` re-ingests when the sibling checkout exists
and skips otherwise; the committed artifacts are what reports are generated from.

## What ingest enforces (hard failure, no partial output)
- run id equals `source_run.ner_eval_run_id` in `policy/candidates.json`;
- corpus snapshot id, content digest and case count equal the pinned `ner-evidence-public` identity;
- every adapter has a pin; model digest, size, model version / revision and (for candidates) the runtime commit equal the pin;
- each quality artifact matches its run-manifest entry (adapter id, artifact digest);
- performance artifacts match a quality artifact, and share the index's hardware class;
- every resolved pin has an artifact in the run.

## Normalized schemas
`fastner-benchmarks.quality/2`: run/source provenance, `corpus {id, snapshot_id, case_count, digest}`,
`model {id, adapter_id, artifact_digest}`, `status` (`unavailable` carries `reason`), and
`metrics {overall, slices}` where each block is `{cases, strict{P,R,F1}, lenient{P,R,F1}, counts}`.
Slice keys drop ner-eval's `person/` prefix (`language=en`, `difficulty=ambiguous`, `seen=false`,
`shape=single-token`, `collision=organization`, ...). Undefined metrics stay `null`.

`fastner-benchmarks.perf/2`: `environment.id` = ner-eval hardware class, `transport`, `cells`
(batch size, requested/effective threads, cases/s, per-case p50/p95 µs, peak RSS + scope, cold
startup/first-batch µs) and `sizes {model_bytes, binary_bytes, wasm_bytes}` from role-tagged
artifacts. Policy dimensions are derived by `perf_summary` (definitions in
`policy/qualification-policy.json`): latency = batch 1 / 1 thread p95; throughput = largest batch /
1 thread; startup = median cold run; RSS = max over 1-thread cells.

## Dropped on ingest
Diagnostics, per-case/fixture records, `per_projection`, `per_kind`. The snapshot is
`redistribution: internal-only`; committed artifacts contain aggregates and ids only (tested).

## Known gaps (handoffs)
- ner-eval cannot yet run or ingest product case-jsonl corpora, so regression/adversarial are unmeasured.
- ner-eval's README "largest batch" column mixes thread counts (see the issue filed on ner-eval); this repo reads the cells directly.
- Artifacts carry no binary/WASM *delta* against a runtime baseline, so reports show sizes only.
