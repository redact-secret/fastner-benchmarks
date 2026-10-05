# Beta 1 qualification

Evaluation only: no candidate code, corpus, evidence or evaluator semantics are changed here.
Rules: `beta1/acceptance.json` (committed **before** any Beta 1 artifact was ingested; two dated clarifications are
recorded in the file). Pins: `beta1/config.json`. Outputs: `reports/beta1/` (generated).

```bash
python -m fnbench beta1-ingest        # ner-eval plan fastner-beta1 -> artifacts/beta1 (aggregate-only)
python -m fnbench beta1-verify-pins   # re-verify pins against fastner, ner-evidence, ner-eval checkouts
python -m fnbench beta1               # stages -> support matrix -> record
```

## Inputs
| input | pin |
|---|---|
| FastNER Beta 1 candidate | tag `beta1-candidate-1`, commit `544484a` (= fastner main), crate tree `4399c7a`, model dir `sha256:39411273…` (590,760 bytes) |
| Evidence | `person-en-ko-beta.1-1dc0b13fe0ff` (872 cases), published in ner-evidence's snapshot index |
| Measurement | ner-eval 0.2.0 plan `fastner-beta1` (4 populations, native + shim adapters, 3 references, 2 controls; verify-plan identical over 60 files) |
| Baseline | Alpha CRF artifacts (`artifacts/bakeoff/alpha1-full`), like-for-like on the two product corpora |

## Stages and outcomes
`0 pins -> 1 architecture -> 2 quality -> 3 calibration -> 4 performance/size -> support matrix -> record`.
Any failed hard check is **A. BETA 1 FAIL** (fix the candidate, re-measure). Otherwise **B. ACCEPT** (Beta 2 planning), or
**C. ACCEPT + provisional support** only if every provisional condition holds (all gates pass, no straddling interval, every
size/performance value measured by ner-eval, quality evidence from a population outside selection, ADR on main, ratification).
Support-gate thresholds are the unchanged gate set 0.3.0 plus one calibration gate (ECE <= 0.10). `stable` is never an outcome.

## Current result
See `reports/beta1/qualification.md`. Summary: every pin, architecture, calibration and performance check passes; one
hard check fails (Korean slice of the regression corpus: F1 0.818 -> 0.783 on 18 cases, one extra false positive, beyond the
declared 0.02 tolerance), so the outcome is **A**. The record states that Alpha's value lies inside Beta 1's 95% interval and
that the rule is not sample-size aware; that feedback is for the next rule version and is not applied retroactively.

## Evidence limits (carried into every output)
- The Beta 1 snapshot and the product corpora were all observed during FastNER's Beta 1 development, so none is a blind test and
  none counts as evidence outside selection; no protected holdout exists. Provisional support is therefore not reachable yet.
- WASM size is candidate-reported (ner-eval's Beta 1 artifacts carry no WASM probe); everything else is ner-eval measured.
- The shim does not report the runtime commit or per-model identities; it is tied to the pin by crate tree hash and model
  directory digest, and the native adapter (same bytes, identical quality results) carries the commit.
- Alpha shim startup used protocol 1.1.0 and is not comparable to this plan's 1.2.0 numbers.
