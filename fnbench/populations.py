"""Qualification populations and denominator accounting (issue #3)."""
import json

from .util import ROOT, load_json

POP_PATH = ROOT / "policy" / "populations.json"


class PopulationError(ValueError):
    pass


def load_populations(path=POP_PATH):
    reg = load_json(path)
    validate_registry(reg)
    return reg


def validate_registry(reg):
    errs = []
    rules = reg["rules"]
    if rules.get("never_merge_denominators") is not True:
        errs.append("never_merge_denominators must be true")
    seen = set()
    for p in reg["populations"]:
        pid = p.get("id", "?")
        for f in rules["required_fields"]:
            if f not in p:
                errs.append(f"{pid}: missing {f}")
        if pid in seen:
            errs.append(f"duplicate population id {pid}")
        seen.add(pid)
        if p.get("role") not in rules["roles"]:
            errs.append(f"{pid}: bad role")
        if p.get("status") not in rules["statuses"]:
            errs.append(f"{pid}: bad status")
        if p.get("publication") not in rules["publications"]:
            errs.append(f"{pid}: bad publication")
        for f in rules["required_provenance_fields"]:
            if f not in p.get("provenance", {}):
                errs.append(f"{pid}: provenance missing {f}")
        if "+" in pid or "," in pid:
            errs.append(f"{pid}: id looks like a merged population")
        if p.get("status") != "available" and not p.get("blocked_by"):
            errs.append(f"{pid}: non-available population must say what blocks it")
        if p.get("role") == "holdout-gate" and p.get("publication") != "private-aggregates-only":
            errs.append(f"{pid}: holdout must be private-aggregates-only")
        if p.get("status") == "available" and p["identity"].get("corpus_version") is None and p["artifact"].get("kind") != "ner-evidence-snapshot":
            errs.append(f"{pid}: available population needs identity version")
    for c in reg.get("companions", []):
        if c.get("counts_in_denominator"):
            errs.append(f"companion {c['id']} must not count in a denominator")
        if not (ROOT / c["path"]).exists():
            errs.append(f"companion {c['id']}: {c['path']} does not exist")
    roles = [p.get("role") for p in reg["populations"]]
    if len(roles) != len(set(roles)):
        errs.append("each role must map to exactly one population")
    if errs:
        raise PopulationError("; ".join(errs))
    return True


def by_id(reg):
    return {p["id"]: p for p in reg["populations"]}


def count_cases(population, root=ROOT):
    path = population["artifact"].get("path")
    if not path or population["artifact"]["kind"] != "case-jsonl":
        return None
    f = root / path
    if not f.exists():
        return None
    return sum(1 for line in f.read_text(encoding="utf-8").splitlines() if line.strip())


def account_artifact(reg, quality_artifact, root=ROOT):
    """Check one ner-eval quality artifact against the registry.

    Returns the population id it belongs to. Raises if the artifact references an
    unknown or merged corpus, or its case count/digest disagrees with the pinned identity.
    """
    corpus = quality_artifact.get("corpus") or {}
    cid = corpus.get("id")
    pops = by_id(reg)
    if cid not in pops:
        raise PopulationError(f"artifact corpus {cid!r} is not a registered population (merged or unknown)")
    pop = pops[cid]
    if pop["status"] == "pending-pin" or pop["status"] == "planned":
        raise PopulationError(f"population {cid} is {pop['status']}; artifacts against it cannot qualify anything")
    expected = count_cases(pop, root)
    if expected is None:
        expected = pop["identity"].get("case_count")
    if expected is not None and corpus.get("case_count") != expected:
        raise PopulationError(f"{cid}: artifact case_count {corpus.get('case_count')} != registered {expected}")
    ident = pop["identity"]
    if ident.get("snapshot_digest") and corpus.get("digest") != ident["snapshot_digest"]:
        raise PopulationError(f"{cid}: corpus digest does not match pinned snapshot digest")
    return cid


def combined_denominator(*_args, **_kw):
    raise PopulationError("denominators are never merged across populations")


def accounting_table(reg, quality_artifacts, root=ROOT):
    """Per-population accounting: identity, provenance, case count, artifacts, role."""
    rows = {p["id"]: {"id": p["id"], "title": p["title"], "role": p["role"], "status": p["status"],
                      "identity": p["identity"], "provenance": p["provenance"],
                      "case_count": count_cases(p, root), "artifact_runs": []}
            for p in reg["populations"]}
    for qa in quality_artifacts:
        cid = account_artifact(reg, qa, root)
        rows[cid]["artifact_runs"].append(qa["run_id"])
    for r in rows.values():
        r["artifact_runs"].sort()
    from .corpus import CORPORA, describe
    for cid in CORPORA:
        if cid in rows and rows[cid]["case_count"] is not None:
            d = describe(cid, root)
            rows[cid].update(content_digest=d["content_digest"], origins=d["origins"])
    return [rows[k] for k in sorted(rows)]
