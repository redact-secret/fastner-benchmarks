"""SYNTHETIC test worlds. Numbers here are fabricated for exercising code paths only and
must never be written under artifacts/ or used for a real decision."""
import copy

from fnbench.pins import load_candidates
from fnbench.policy import load_policy
from fnbench.populations import load_populations

DIG = {m: "sha256:" + c * 64 for m, c in
       zip(["fastner-a-statistical", "fastner-b-linear-crf", "fastner-c-compact-neural", "fastner-d-tiny-transformer", "ref-spacy-en"], "abcde")}


def resolved_cfg():
    cfg = copy.deepcopy(load_candidates())
    for e in cfg["candidates"]:
        if e["id"] in DIG:
            e["pin_status"] = "resolved"
            e["model"].update(artifact_digest=DIG[e["id"]], size_bytes=1)
            if e["role"] == "candidate":
                e["runtime"].update(commit="deadbeef", version="0.0.0-test")
                e["adapter"]["version"] = "1"
                e["model"]["format_version"] = "1"
            else:
                e["availability"] = "available"
                e["model"]["revision"] = "rev"
                e["runtime"]["version"] = "1"
                e["adapter"]["version"] = "1"
                e["license"] = "test"
    return cfg


def pop_reg():
    reg = copy.deepcopy(load_populations())
    for p in reg["populations"]:
        if p["id"] == "ner-evidence-public":
            p["status"] = "available"
            p["identity"] = {"snapshot_id": "synthetic", "snapshot_digest": "sha256:" + "9" * 64, "case_count": 100, "corpus_version": "t"}
    return reg


def block(p, r, f1=None):
    return {"precision": p, "recall": r, "f1": f1 if f1 is not None else round(2 * p * r / (p + r), 4)}


def quality(model, f1_scale=1.0, corpus="ner-evidence-public", run="q", proto="p1", status="ok"):
    a = {"schema": "ner-eval.quality/draft", "run_id": f"{run}-{model}", "evaluator_version": "ev1", "metric_protocol_version": proto,
         "corpus": {"id": corpus, "case_count": 100, "digest": "sha256:" + "9" * 64},
         "model": {"id": model, "artifact_digest": DIG.get(model)}, "status": status}
    if status != "ok":
        a["reason"] = "adapter crashed"
        return a
    s = f1_scale
    a["metrics"] = {"overall": block(0.9 * s, 0.9 * s), "slices": {
        "difficulty=ambiguous": block(0.8 * s, 0.7), "seen=false": block(0.8, 0.6 * s),
        "language=en": block(0.9 * s, 0.9 * s), "language=ko": block(0.8 * s, 0.8 * s),
        "shape=single-token": block(0.8, 0.8 * s), "shape=multi-token": block(0.9, 0.9 * s),
        "collision=common-word": block(0.85 * s, 0.9), "collision=location": block(0.7 * s, 0.9)}}
    return a


def perf(model, latency=5.0, thr=1000.0, startup=20, mem=50, msize=1000, bsize=5000, wsize=3000, env="env-1", run="p"):
    return {"schema": "ner-eval.perf/draft", "run_id": f"{run}-{model}", "evaluator_version": "ev1",
            "model": {"id": model, "artifact_digest": DIG.get(model)}, "environment": {"id": env}, "status": "ok",
            "startup_ms": startup, "latency_ms": {"p50": latency / 2, "p95": latency}, "throughput_docs_per_s": thr,
            "peak_rss_mb": mem, "model_size_bytes": msize, "binary_size_bytes": bsize, "wasm_size_bytes": wsize,
            "binary_delta_bytes": msize, "wasm_delta_bytes": msize}


def world():
    """Four candidates on the public snapshot + perf. A: small/weak, B: mid, C: big/strong, D dominated by C."""
    qs = [quality("fastner-a-statistical", 0.80), quality("fastner-b-linear-crf", 0.92),
          quality("fastner-c-compact-neural", 1.0), quality("fastner-d-tiny-transformer", 0.99)]
    ps = [perf("fastner-a-statistical", 2, 3000, 5, 10, 100, 1000, 800),
          perf("fastner-b-linear-crf", 3, 2500, 8, 15, 500, 1500, 1200),
          perf("fastner-c-compact-neural", 6, 1500, 30, 60, 5000, 6000, 5500),
          perf("fastner-d-tiny-transformer", 20, 300, 200, 300, 50000, 60000, 55000)]
    return load_policy(), resolved_cfg(), pop_reg(), qs, ps
