# Architecture Bakeoff Configuration and Pinning

Source: `policy/candidates.json` (bakeoff `alpha1-full`, source run `run-395459fbb4ecb4da`), validated by `fnbench/pins.py`.

## Scope
PERSON, languages `en` and `ko`. Quality is measured on the registered populations
`ner-evidence-public`, `fastner-regression`, `fastner-adversarial`, each reported separately.
Performance protocol (warmup, iterations, batch sizes, cold-start runs, seed) is in the config;
performance results are only comparable inside one environment id.

## Candidates
A statistical, B linear+CRF, C compact neural, D tiny Transformer reference. D is a
comparison point, not the assumed target.

## Pins (current)
| Role | Pins |
|---|---|
| candidates A-D | fastner runtime commit `007805d3e83bb6c72f604cdcdd2e338c7b6ea753` (head of fastner PR #10, **unmerged at pin time**); model-directory digests equal fastner's own `candidates/MANIFEST.tsv`; adapter = `fastner-eval-shim` v1 (shared binary), per-candidate WASM probe |
| references | spaCy `en_core_web_sm` 3.8.0, `dslim/bert-base-NER` @ `d1a3e8f1…`, `Leo97/KoELECTRA-small-v3-modu-ner` @ `bb9d5626…`, each with directory digest, size and runtime stack from ner-eval's pins |
| planned reference | GLiNER multilingual: `unresolved` (ner-eval has no adapter yet) |
| controls | ner-eval `control-null` and `control-capitalized-run` (calibration; shown, never ranked) |

`source_runs` lists the pinned ner-eval runs (public snapshot + performance; regression; adversarial).
`runtime.also_measured_at` records any additional runtime commit a candidate was measured at (CRF product runs:
`89c4134`, model digest unchanged, docs/comment-only diff).

Ingest cross-checks every artifact against these pins (digest, size, version/revision, runtime
commit). Candidate `config` records the label map, threads, batch size and ner-eval's adapter
config hash; `config_hash` is computed from it.

## Pin requirements
Candidate: runtime commit (40-hex) + version, adapter id + version, model digest/size/version, config.
Reference: model revision *or* version, digest, size, runtime name + version, adapter id + version, config.
Control: digest, adapter id + version. License is tracked separately (`license.verified`); unverified
licenses are listed as public-release limitations, they do not block measurement.

## States
- `resolved`: all required fields present, digest `sha256:<64 hex>`. Only resolved pins may enter qualification.
- `unresolved`: allowed, must state `blocked_by`, must not carry a digest.
- `unavailable`: cannot be run; needs `unavailable_reason`; shown as unavailable, never zero.
