# Architecture Bakeoff Configuration and Pinning

Source: `policy/candidates.json` (bakeoff `alpha0-bakeoff-1`), validated by `fnbench/pins.py`.

## Scope
PERSON, languages `en` and `ko`. Quality is measured on the registered populations
`ner-evidence-public`, `fastner-regression`, `fastner-adversarial`, each reported separately.
Performance protocol (warmup, iterations, batch sizes, cold-start runs, seed) is in the config;
performance results are only comparable inside one environment id.

## Candidates
A statistical, B linear+CRF, C compact neural, D tiny Transformer reference. D is a
comparison point, not the assumed target.

## External references
spaCy `en_core_web_sm`, spaCy `ko_core_news_sm`, `dslim/bert-base-NER`, GLiNER multilingual.
These identify the model only. **Revision, digest, size, runtime version, adapter version and
license are unresolved** and must be filled in by a networked pinning step; none were invented.

## Pin requirements
Candidate: runtime commit+version, adapter id+version, model digest/size/format, config.
Reference: model revision, digest, size, runtime name+version, adapter id+version, config, license.
`config_hash` is computed from the canonical config JSON, never hand-entered.

## States
- `resolved`: all required fields present, digest `sha256:<64 hex>`, digest matches the file
  on disk when a path is given. Only resolved pins may enter qualification (`require_resolved`).
- `unresolved`: allowed in the repo, must state `blocked_by`, must not carry a digest.
- `unavailable`: reference cannot be run (license, hardware, ...); needs `unavailable_reason`.
  Reports show it as unavailable, never as zero.

## Current state
All 8 pins are `unresolved`: `fastner` is documentation-only (no runtime, model format, or
artifacts) and no reference was downloaded/verified. Blockers are recorded per entry.
