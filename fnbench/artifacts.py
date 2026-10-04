"""Load and validate ner-eval artifacts (consumer side, issues #3/#5)."""
import json
from pathlib import Path

from .util import ROOT

Q_SCHEMA = "ner-eval.quality/draft"
P_SCHEMA = "ner-eval.perf/draft"


class ArtifactError(ValueError):
    pass


def load_dir(directory):
    d = Path(directory)
    if not d.exists():
        return []
    out = []
    for f in sorted(d.glob("*.json")):
        out.append((f.name, json.loads(f.read_text(encoding="utf-8"))))
    return out


def _need(a, name, keys):
    for k in keys:
        if k not in a:
            raise ArtifactError(f"{name}: missing {k}")


def validate_quality(name, a):
    if a.get("schema") != Q_SCHEMA:
        raise ArtifactError(f"{name}: expected schema {Q_SCHEMA}")
    _need(a, name, ["run_id", "evaluator_version", "metric_protocol_version", "corpus", "model", "status"])
    if a["status"] == "unavailable":
        if not a.get("reason"):
            raise ArtifactError(f"{name}: unavailable artifact needs reason")
        return a
    if a["status"] != "ok":
        raise ArtifactError(f"{name}: bad status")
    _need(a, name, ["metrics"])
    m = a["metrics"]
    for label, block in [("overall", m.get("overall"))] + list((m.get("slices") or {}).items()):
        if not isinstance(block, dict):
            raise ArtifactError(f"{name}: metrics {label} missing")
        for k in ("precision", "recall", "f1"):
            v = block.get(k)
            if v is not None and not (isinstance(v, (int, float)) and 0 <= v <= 1):
                raise ArtifactError(f"{name}: {label}.{k} out of range")
    return a


def validate_perf(name, a):
    if a.get("schema") != P_SCHEMA:
        raise ArtifactError(f"{name}: expected schema {P_SCHEMA}")
    _need(a, name, ["run_id", "evaluator_version", "model", "environment", "status"])
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
