# ner-eval artifact contract (as consumed)

The earlier draft contract is replaced: `ner-eval` now emits real artifacts
(`ner-eval.artifacts/1`, run manifest `ner-eval.run-manifest/1`, measurement protocol
`ner-eval.match/1.1.0`, performance protocol `ner-eval.perf-protocol/1.1.0`, slices
`ner-eval.person-slices/2`). Their schema and metric semantics belong to ner-eval; this repo only reads them.

## Flow
```
ner-eval results/<run>/ (several pinned runs) --fnbench ingest-->  artifacts/bakeoff/<bakeoff_id>/quality/<population>/<pin id>.json
                                              artifacts/bakeoff/<bakeoff_id>/perf/<pin id>.json
                                              + ingest-manifest.json (runs, ner-eval commits, file sha256)
artifacts/ --fnbench report/promotion/support/qualify--> reports/
```
`python -m fnbench ingest [--source ../ner-eval]` (reads every run in `source_runs` of `policy/candidates.json`:
the public snapshot run with performance, and one quality-only run per product corpus) verifies the run and writes
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

## Product-corpus runs
Each product corpus is its own run and its own population (`corpus.snapshot_id` = population id).
Ingest requires the run's corpus content digest and case count to equal the **committed** corpus
(`fnbench/corpus.py describe`), so a corpus edit makes older measurements stale instead of silently
reusing them. Per-case failures are kept as `{case_id, outcome, region}` (our own ids, no text) for
non-control models; truncated diagnostics are rejected. A candidate may be measured at more than one
runtime commit only if the pin lists it under `runtime.also_measured_at` with the model digest
unchanged and a recorded diff note (CRF: public snapshot at `007805d`, product corpora at `89c4134`;
the difference is documentation and one comment line).

## Dropped on ingest
Diagnostics, per-case/fixture records, `per_projection`, `per_kind`. The snapshot is
`redistribution: internal-only`; committed artifacts contain aggregates and ids only (tested).

## Known gaps (handoffs)
- Product corpora were measured for CRF and the controls only, not for candidates A/C/D or the references.
- ner-eval fixed its README "largest batch" column (ner-eval#12); this repo always read the requested-1-thread cells directly.
- Startup/latency are measured through an external-process shim; an in-process measurement is recorded as ner-eval debt.
- Artifacts carry no binary/WASM *delta* against a runtime baseline, so reports show sizes only.
