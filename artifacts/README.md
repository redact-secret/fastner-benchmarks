# artifacts/

Drop **real** ner-eval output here: `artifacts/bakeoff/<bakeoff_id>/{quality,perf}/*.json`
(contract: `docs/ARTIFACT_CONTRACT.md`). Never hand-edit or hand-write these files and never
put synthetic data here; test fixtures live in `tests/helpers.py`.

Currently empty: ner-eval has no implementation yet, so no measurements exist.
Regenerate the report with `python -m fnbench report`.
