"""SYNTHETIC test worlds. Numbers here are fabricated for exercising code paths only and
must never be written under artifacts/ or used for a real decision.

Pins, populations and policy are the REAL committed ones; only the measurements are fake."""
import copy

from fnbench.pins import load_candidates
from fnbench.policy import load_policy
from fnbench.populations import load_populations
from fnbench.artifacts import MIB, P_SCHEMA, Q_SCHEMA


def resolved_cfg():
    return copy.deepcopy(load_candidates())


def pop_reg():
    return copy.deepcopy(load_populations())


_CFG = load_candidates()
DIG = {e["id"]: e["model"]["artifact_digest"] for e in _CFG["candidates"] if e.get("model", {}).get("artifact_digest")}


def _counts():
    from fnbench.corpus import CORPORA, read_built
    c = {k: len(read_built(k)) for k in CORPORA}
    for p in load_populations()["populations"]:
        if p["id"] == "ner-evidence-public":
            c["ner-evidence-public"] = p["identity"]["case_count"]
    return c


COUNTS = _counts()


def _digests():
    from fnbench.corpus import CORPORA, describe
    return {k: describe(k)["content_digest"] for k in CORPORA}


DIGESTS = _digests()
SNAP = next(p for p in load_populations()["populations"] if p["id"] == "ner-evidence-public")["identity"]["snapshot_digest"]


def block(p, r, f1=None, cases=100):
    f = f1 if f1 is not None else round(2 * p * r / (p + r), 4)
    s = {"precision": p, "recall": r, "f1": f}
    return {"strict": s, "lenient": dict(s), "cases": cases, "counts": {}}


def quality(model, f1_scale=1.0, corpus="ner-evidence-public", run="q", proto="p1", status="ok"):
    a = {"schema": Q_SCHEMA, "run_id": f"{run}-{model}", "evaluator_version": "ev1", "metric_protocol_version": proto,
         "source": {"ner_eval_run_id": "test"},
         "corpus": {"id": corpus, "case_count": COUNTS.get(corpus, 100), "digest": DIGESTS.get(corpus, SNAP)},
         "model": {"id": model, "artifact_digest": DIG.get(model)}, "status": status}
    if status != "ok":
        a["reason"] = "adapter crashed"
        return a
    s = f1_scale
    a["metrics"] = {"overall": block(0.9 * s, 0.9 * s, cases=545), "slices": {
        "difficulty=ambiguous": block(0.8 * s, 0.7), "seen=false": block(0.8, 0.6 * s),
        "language=en": block(0.9 * s, 0.9 * s), "language=ko": block(0.8 * s, 0.8 * s),
        "shape=single-token": block(0.8, 0.8 * s), "shape=multi-token": block(0.9, 0.9 * s),
        "collision=common-word": block(0.85 * s, 0.9), "collision=location": block(0.7 * s, 0.9),
        "collision=organization": block(0.9 * s, 0.9, cases=33)}}
    return a


def perf(model, latency=5.0, thr=1000.0, startup=20, mem=50, msize=1000, bsize=5000, wsize=3000, env="env-1", run="p"):
    cells = []
    for b in (1, 16):
        for t in (1, 4):
            cells.append({"batch_size": b, "threads": t, "effective_threads": 1,
                          "cases_per_sec": thr if (b == 16 and t == 1) else thr / 3, "per_case_p50_us": latency * 500,
                          "per_case_p95_us": latency * 1000 if (b == 1 and t == 1) else latency * 100,
                          "peak_rss_bytes": int(mem * MIB), "rss_scope": "adapter-process",
                          "cold_startup_us": [startup * 1000] * 3, "first_batch_us": [100] * 3})
    return {"schema": P_SCHEMA, "run_id": f"{run}-{model}", "evaluator_version": "ev1", "source": {"ner_eval_run_id": "test"},
            "model": {"id": model, "artifact_digest": DIG.get(model)}, "environment": {"id": env}, "transport": "external-process",
            "status": "ok", "cells": cells, "measurement_notes": [], "sizes": {"model_bytes": msize, "binary_bytes": bsize, "wasm_bytes": wsize}}


def patch_perf(a, startup=None, model=None, binary=None, wasm="keep"):
    if startup is not None:
        for c in a["cells"]:
            c["cold_startup_us"] = [startup * 1000] * 3
    if model is not None:
        a["sizes"]["model_bytes"] = model
    if binary is not None:
        a["sizes"]["binary_bytes"] = binary
    if wasm != "keep":
        a["sizes"]["wasm_bytes"] = wasm
    return a


def world():
    """Four candidates on the public snapshot + perf. A: small/weak, B: mid, C: big/strong, D dominated by C."""
    qs = [quality("fastner-a-statistical", 0.80), quality("fastner-b-linear-crf", 0.92),
          quality("fastner-c-compact-neural", 1.0), quality("fastner-d-tiny-transformer", 0.99)]
    ps = [perf("fastner-a-statistical", 2, 3000, 5, 10, 100, 1000, 800),
          perf("fastner-b-linear-crf", 3, 2500, 8, 15, 300, 1500, 1200),
          perf("fastner-c-compact-neural", 6, 1500, 30, 60, 800, 6000, 5500),
          perf("fastner-d-tiny-transformer", 20, 300, 200, 300, 50000, 60000, 55000)]
    return load_policy(), resolved_cfg(), pop_reg(), qs, ps
