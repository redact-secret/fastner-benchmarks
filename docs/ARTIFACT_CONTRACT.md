# Consumed ner-eval artifact contract (DRAFT, consumer-side)

`ner-eval` has not frozen its artifact schema (its ARCHITECTURE.md says "must be versioned").
This is what `fnbench` **assumes it will receive**. It is a request to ner-eval, not a
definition: if ner-eval's real schema differs, fnbench adapts at the loader, and
metric semantics stay ner-eval's.

Layout read by the generator: `artifacts/bakeoff/<bakeoff_id>/{quality,perf}/*.json`.

## Quality artifact (`schema: "ner-eval.quality/draft"`)
```json
{
  "schema": "ner-eval.quality/draft",
  "run_id": "...", "evaluator_version": "...", "metric_protocol_version": "...",
  "corpus": {"id": "<registered population id>", "case_count": 0, "digest": "sha256:..."},
  "model": {"id": "<pin id>", "artifact_digest": "sha256:..."},
  "adapter": {"id": "...", "version": "..."}, "config_hash": "sha256:...",
  "status": "ok | unavailable", "reason": "required when unavailable",
  "metrics": {
    "overall": {"precision": 0.0, "recall": 0.0, "f1": 0.0, "tp": 0, "fp": 0, "fn": 0},
    "slices": {"language=en": {"precision": 0.0, "recall": 0.0, "f1": 0.0, "tp": 0, "fp": 0, "fn": 0}}
  }
}
```
Slice keys are ner-eval slice-engine `key=value` strings (`difficulty=ambiguous`, `seen=false`,
`language=ko`, `shape=single-token`, `collision=common-word`, ...).

## Perf artifact (`schema: "ner-eval.perf/draft"`)
```json
{
  "schema": "ner-eval.perf/draft", "run_id": "...", "evaluator_version": "...",
  "model": {"id": "<pin id>", "artifact_digest": "sha256:..."},
  "environment": {"id": "...", "cpu": "...", "os": "...", "toolchain": "..."},
  "status": "ok | unavailable", "reason": "...",
  "startup_ms": 0, "latency_ms": {"p50": 0, "p95": 0}, "throughput_docs_per_s": 0,
  "peak_rss_mb": 0, "model_size_bytes": 0, "binary_size_bytes": 0, "wasm_size_bytes": 0,
  "binary_delta_bytes": 0, "wasm_delta_bytes": 0
}
```
Deltas are against the same runtime built without the candidate model/code; baseline identity
is ner-eval's to record.

## Rules enforced by fnbench
- Artifact `corpus.id` must be exactly one registered population; case counts/digests must match.
- `model.id` must be a known pin; if the pin is resolved, `model.artifact_digest` must equal it.
  Artifacts for unresolved pins are excluded and reported (cannot qualify anything).
- One artifact per (model, population) and per model for perf; duplicates are an error.
- All quality artifacts must share one `metric_protocol_version`.
- Missing field = not measured; `status: unavailable` = unavailable with reason. Neither is zero.
- Perf artifacts from different `environment.id`s are not comparable; perf dimensions are then
  withheld from ranking and the report says so.

## Handoff
Open question for ner-eval: confirm/freeze these fields (see issue opened in ner-eval).
