"""Qualification policy loading and validation (issue #2)."""
from .util import ROOT, load_json

POLICY_PATH = ROOT / "policy" / "qualification-policy.json"
REQUIRED_DIMENSIONS = {
    "entity_precision", "entity_recall", "entity_f1", "ambiguous_name_precision",
    "unseen_name_recall", "en_f1", "ko_f1", "single_token_recall", "multi_token_f1",
    "collision_precision_worst", "latency_p95_ms", "throughput_docs_per_s", "startup_ms",
    "peak_memory_mb", "model_size_bytes", "runtime_binary_size_bytes", "wasm_size_bytes",
}


class PolicyError(ValueError):
    pass


def load_policy(path=POLICY_PATH):
    policy = load_json(path)
    validate_policy(policy)
    return policy


def validate_policy(policy):
    errs = []
    if policy.get("schema") != "fastner-benchmarks.policy/1":
        errs.append("unknown policy schema")
    if not policy.get("policy_version"):
        errs.append("policy_version missing")
    if policy.get("no_single_score") is not True:
        errs.append("no_single_score must be true")
    if policy.get("decision_method") != "pareto-frontier":
        errs.append("decision_method must be pareto-frontier")
    if policy.get("missing_value_rule") != "unavailable-is-never-zero":
        errs.append("missing_value_rule must be unavailable-is-never-zero")
    forbidden = set(policy.get("forbidden_aggregate_keys", []))
    dims = policy.get("dimensions", [])
    ids = [d.get("id") for d in dims]
    if len(ids) != len(set(ids)):
        errs.append("duplicate dimension ids")
    missing = REQUIRED_DIMENSIONS - set(ids)
    if missing:
        errs.append(f"missing required dimensions: {sorted(missing)}")
    for d in dims:
        if d.get("id") in forbidden:
            errs.append(f"dimension {d.get('id')} is a forbidden aggregate")
        if d.get("direction") not in ("max", "min"):
            errs.append(f"{d.get('id')}: direction must be max|min")
        for k in ("group", "title", "unit", "source"):
            if k not in d:
                errs.append(f"{d.get('id')}: missing {k}")
        src = d.get("source", {})
        if src.get("artifact") not in ("quality", "perf"):
            errs.append(f"{d.get('id')}: source.artifact must be quality|perf")
        if "weight" in d:
            errs.append(f"{d.get('id')}: weights imply a composite score and are not allowed")
    if errs:
        raise PolicyError("; ".join(errs))
    return True


def dimension_map(policy):
    return {d["id"]: d for d in policy["dimensions"]}
