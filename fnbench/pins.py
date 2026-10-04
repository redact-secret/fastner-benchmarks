"""Candidate / reference pinning and validation (issue #4)."""
import re

from .util import ROOT, canonical_json, get_path, load_json, sha256_bytes, sha256_file

CAND_PATH = ROOT / "policy" / "candidates.json"
DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
REQUIRED_CLASSES = {"A-statistical", "B-linear-crf", "C-compact-neural", "D-tiny-transformer"}


class PinError(ValueError):
    pass


def load_candidates(path=CAND_PATH):
    cfg = load_json(path)
    validate_config(cfg)
    return cfg


def config_hash(entry):
    """Hash of the behaviour-defining config; computed, never hand-entered."""
    return sha256_bytes(canonical_json(entry["config"]).encode("utf-8"))


def missing_pin_fields(cfg, entry):
    out = []
    for dotted in cfg["pin_requirements"][entry["role"]]:
        v = get_path(entry, dotted)
        if v is None or v == "" or v == {}:
            out.append(dotted)
    return out


def validate_config(cfg):
    errs = []
    entries = cfg["candidates"]
    ids = [e["id"] for e in entries]
    if len(ids) != len(set(ids)):
        errs.append("duplicate ids")
    classes = {e.get("class") for e in entries if e["role"] == "candidate"}
    if classes != REQUIRED_CLASSES:
        errs.append(f"candidate classes must be exactly {sorted(REQUIRED_CLASSES)}")
    if not any(e["role"] == "reference" for e in entries):
        errs.append("at least one external reference required")
    from .populations import load_populations, by_id
    pops = by_id(load_populations())
    for pid in cfg["quality_populations"]:
        if pid not in pops:
            errs.append(f"unknown population {pid}")
    for e in entries:
        eid = e["id"]
        if e["role"] not in ("candidate", "reference"):
            errs.append(f"{eid}: bad role")
        status = e.get("pin_status")
        miss = missing_pin_fields(cfg, e)
        dig = get_path(e, "model.artifact_digest")
        if status == "resolved":
            if miss:
                errs.append(f"{eid}: resolved pin missing {miss}")
            if dig is not None and not DIGEST_RE.match(dig):
                errs.append(f"{eid}: artifact_digest must be sha256:<64 hex>")
            path = get_path(e, "model.artifact_path")
            if path and (ROOT / path).exists() and sha256_file(ROOT / path) != dig:
                errs.append(f"{eid}: artifact_digest does not match file on disk")
            if e["role"] == "reference" and e.get("availability") not in ("available",):
                errs.append(f"{eid}: resolved reference must be availability=available")
        elif status == "unresolved":
            if not e.get("blocked_by"):
                errs.append(f"{eid}: unresolved pin must say what blocks it")
            if dig is not None:
                errs.append(f"{eid}: unresolved pin must not carry a digest")
        elif status == "unavailable":
            if not e.get("unavailable_reason"):
                errs.append(f"{eid}: unavailable pin needs unavailable_reason")
        else:
            errs.append(f"{eid}: pin_status must be resolved|unresolved|unavailable")
    if errs:
        raise PinError("; ".join(errs))
    return True


def pin_table(cfg):
    rows = []
    for e in cfg["candidates"]:
        rows.append({
            "id": e["id"], "role": e["role"], "class": e.get("class"), "display": e["display"],
            "pin_status": e["pin_status"], "availability": e.get("availability", "n/a"),
            "version": get_path(e, "runtime.version") if e["role"] == "candidate" else get_path(e, "model.revision"),
            "artifact_digest": get_path(e, "model.artifact_digest"),
            "model_size_bytes": get_path(e, "model.size_bytes"),
            "runtime": get_path(e, "runtime.name"), "adapter": get_path(e, "adapter.id"),
            "config_hash": config_hash(e), "missing": missing_pin_fields(cfg, e),
            "blocked_by": e.get("blocked_by") or e.get("unavailable_reason"),
        })
    return rows


def require_resolved(cfg, ids):
    unresolved = [e["id"] for e in cfg["candidates"] if e["id"] in ids and e["pin_status"] != "resolved"]
    if unresolved:
        raise PinError(f"unresolved pins cannot qualify: {sorted(unresolved)}")
