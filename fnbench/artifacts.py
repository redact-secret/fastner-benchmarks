"""Normalized ner-eval artifacts as consumed by fnbench (issues #3/#5).

`fnbench ingest` converts real `ner-eval.artifacts/1` output into these schemas
(aggregates only: no diagnostics, no case text). Everything downstream reads only these.
"""
import json
from pathlib import Path

from .util import ROOT, get_path

Q_SCHEMA = "fastner-benchmarks.quality/2"
P_SCHEMA = "fastner-benchmarks.perf/2"
MIB = 1048576


class ArtifactError(ValueError):
    pass


def load_dir(directory):
    d = Path(directory)
    if not d.exists():
        return []
    return [(f.name, json.loads(f.read_text(encoding="utf-8"))) for f in sorted(d.glob("*.json"))]


def _need(a, name, keys):
    for k in keys:
        if k not in a:
            raise ArtifactError(f"{name}: missing {k}")


def _check_block(name, label, block):
    if not isinstance(block, dict):
        raise ArtifactError(f"{name}: metrics {label} missing")
    for mode in ("strict", "lenient"):
        for k in ("precision", "recall", "f1"):
            v = (block.get(mode) or {}).get(k)
            if v is not None and not (isinstance(v, (int, float)) and 0 <= v <= 1):
                raise ArtifactError(f"{name}: {label}.{mode}.{k} out of range")


def validate_quality(name, a):
    if a.get("schema") != Q_SCHEMA:
        raise ArtifactError(f"{name}: expected schema {Q_SCHEMA}")
    _need(a, name, ["run_id", "evaluator_version", "metric_protocol_version", "corpus", "model", "status", "source"])
    if a["status"] == "unavailable":
        if not a.get("reason"):
            raise ArtifactError(f"{name}: unavailable artifact needs reason")
        return a
    if a["status"] != "ok":
        raise ArtifactError(f"{name}: bad status")
    _need(a, name, ["metrics"])
    m = a["metrics"]
    _check_block(name, "overall", m.get("overall"))
    for k, b in (m.get("slices") or {}).items():
        _check_block(name, k, b)
    return a


def perf_summary(a, spec):
    """Derive the policy's performance dimensions from cells using the declared selection."""
    if a["status"] != "ok":
        return {}
    cells = a.get("cells") or []
    t = spec["threads"]
    one = [c for c in cells if c["batch_size"] == spec["latency_batch"] and c["threads"] == t]
    biggest = [c for c in cells if c["threads"] == t]
    out = {}
    if one:
        c = one[0]
        out["latency_p95_ms"] = None if c.get("per_case_p95_us") is None else c["per_case_p95_us"] / 1000.0
        cold = sorted(c.get("cold_startup_us") or [])
        out["startup_ms"] = (cold[len(cold) // 2] / 1000.0) if cold else None
    if biggest:
        top = max(biggest, key=lambda c: c["batch_size"])
        out["throughput_docs_per_s"] = top.get("cases_per_sec")
    rss = [c["peak_rss_bytes"] for c in biggest if c.get("peak_rss_bytes") is not None]
    out["peak_rss_mb"] = max(rss) / MIB if rss else None
    sz = a.get("sizes") or {}
    out["model_size_bytes"] = sz.get("model_bytes")
    out["binary_size_bytes"] = sz.get("binary_bytes")
    out["wasm_size_bytes"] = sz.get("wasm_bytes")
    return out


def validate_perf(name, a):
    if a.get("schema") != P_SCHEMA:
        raise ArtifactError(f"{name}: expected schema {P_SCHEMA}")
    _need(a, name, ["run_id", "evaluator_version", "model", "environment", "status", "source"])
    if not a["environment"].get("id"):
        raise ArtifactError(f"{name}: environment.id required")
    if a["status"] == "unavailable":
        if not a.get("reason"):
            raise ArtifactError(f"{name}: unavailable artifact needs reason")
    elif a["status"] != "ok":
        raise ArtifactError(f"{name}: bad status")
    return a


def load_bakeoff(bakeoff_id, base=None):
    base = Path(base) if base else ROOT / "artifacts" / "bakeoff" / bakeoff_id
    q = [validate_quality(n, a) for n, a in load_dir(base / "quality")]
    p = [validate_perf(n, a) for n, a in load_dir(base / "perf")]
    return q, p
