"""Bakeoff report generator (issue #5).

Pure function of: committed policy + candidates config + population registry + ner-eval
artifacts. No timestamps, no hand-edited values; output is byte-deterministic.
"""
import argparse
import sys

from .artifacts import ArtifactError, load_bakeoff
from .pareto import frontier
from .pins import load_candidates, pin_table
from .policy import dimension_map, load_policy
from .populations import PopulationError, account_artifact, accounting_table, by_id, load_populations
from .util import ROOT, canonical_json, get_path, write_text

VIEWS = [
    ("global_quality", "Global quality (public snapshot)", ["entity_precision", "entity_recall", "entity_f1"]),
    ("language_quality", "EN / KO quality", ["en_f1", "ko_f1"]),
    ("ambiguity_precision", "Ambiguous-name precision", ["ambiguous_name_precision"]),
    ("unseen_recall", "Unseen-name recall", ["unseen_name_recall"]),
    ("shape_quality", "Single / multi-token behaviour", ["single_token_recall", "multi_token_f1"]),
    ("latency", "Latency (warm p95)", ["latency_p95_ms"]),
    ("throughput", "Throughput", ["throughput_docs_per_s"]),
    ("startup", "Startup (cold)", ["startup_ms"]),
    ("memory", "Peak memory", ["peak_memory_mb"]),
    ("model_size", "Model size", ["model_size_bytes"]),
    ("binary_size", "Runtime binary size", ["runtime_binary_size_bytes"]),
    ("wasm_size", "WASM size", ["wasm_size_bytes"]),
]


def _metric(art, dim):
    src = dim["source"]
    m = art["metrics"]
    if "slice_prefix" in src:
        vals = [b.get(src["metric"]) for k, b in (m.get("slices") or {}).items() if k.startswith(src["slice_prefix"])]
        vals = [v for v in vals if v is not None]
        return min(vals) if vals else None
    block = m.get("overall") if src.get("slice") is None else (m.get("slices") or {}).get(src["slice"])
    return None if block is None else block.get(src["metric"])


def _index(items, key_fn, what):
    out = {}
    for a in items:
        k = key_fn(a)
        if k in out:
            raise ArtifactError(f"duplicate {what} artifact for {k}")
        out[k] = a
    return out


def build_report(policy, cfg, pop_reg, quality, perf, root=ROOT):
    pins = {e["id"]: e for e in cfg["candidates"]}
    rejected, limitations = [], []

    def pin_ok(a, kind):
        mid = a["model"].get("id")
        if mid not in pins:
            return f"unknown model id {mid!r}"
        pin = pins[mid]
        if pin["pin_status"] != "resolved":
            return "pin unresolved: artifact cannot qualify an unpinned model"
        if a["model"].get("artifact_digest") != get_path(pin, "model.artifact_digest"):
            return "artifact_digest does not match pin"
        return None

    acc_q = []
    for a in quality:
        reason = pin_ok(a, "quality")
        if reason is None and a["corpus"].get("id") not in cfg["quality_populations"]:
            reason = f"corpus {a['corpus'].get('id')!r} not in bakeoff quality_populations"
        if reason is None:
            try:
                account_artifact(pop_reg, a, root)
            except PopulationError as e:
                reason = str(e)
        if reason:
            rejected.append({"run_id": a["run_id"], "kind": "quality", "reason": reason})
        else:
            acc_q.append(a)
    acc_p = []
    for a in perf:
        reason = pin_ok(a, "perf")
        if reason:
            rejected.append({"run_id": a["run_id"], "kind": "perf", "reason": reason})
        else:
            acc_p.append(a)

    protos = sorted({a["metric_protocol_version"] for a in acc_q})
    if len(protos) > 1:
        raise ArtifactError(f"mixed metric protocol versions in one report: {protos}")
    q_idx = _index(acc_q, lambda a: (a["model"]["id"], a["corpus"]["id"]), "quality")
    p_idx = _index(acc_p, lambda a: a["model"]["id"], "perf")

    envs = sorted({a["environment"]["id"] for a in acc_p if a["status"] == "ok"})
    perf_comparable = len(envs) <= 1
    if not perf_comparable:
        limitations.append(f"Performance artifacts come from {len(envs)} environments ({', '.join(envs)}); performance dimensions are withheld from ranking.")

    dims = policy["dimensions"]
    dmap = dimension_map(policy)
    ids = [e["id"] for e in cfg["candidates"]]
    values, unavailable = {}, {}
    for mid in ids:
        v = {}
        for d in dims:
            src = d["source"]
            val = None
            if src["artifact"] == "quality":
                a = q_idx.get((mid, src["population"]))
                if a is not None:
                    if a["status"] == "ok":
                        val = _metric(a, d)
                    else:
                        unavailable[mid] = a["reason"]
            else:
                a = p_idx.get(mid)
                if a is not None:
                    if a["status"] == "ok" and perf_comparable:
                        val = get_path(a, src["field"])
                    elif a["status"] != "ok":
                        unavailable[mid] = a["reason"]
            v[d["id"]] = val
        values[mid] = v

    cand_ids = [e["id"] for e in cfg["candidates"] if e["role"] == "candidate"]
    front, dominated, incomplete = frontier({m: values[m] for m in cand_ids}, dims)

    views = {}
    for vid, title, dim_ids in VIEWS:
        rows = [{"model": m, **{d: values[m][d] for d in dim_ids}} for m in ids]
        views[vid] = {"title": title, "dimensions": dim_ids, "rows": rows}
    for vid, field in (("binary_size", "binary_delta_bytes"), ("wasm_size", "wasm_delta_bytes")):
        for row in views[vid]["rows"]:
            a = p_idx.get(row["model"])
            row["delta_bytes"] = a.get(field) if a and a["status"] == "ok" and perf_comparable else None
    # Collision slices: every collision=* slice shown, never collapsed.
    pop = "ner-evidence-public"
    slice_names = sorted({k for (m, p), a in q_idx.items() if p == pop and a["status"] == "ok"
                          for k in (a["metrics"].get("slices") or {}) if k.startswith("collision=")})
    views["collision_slices"] = {"title": "Collision slices (precision)", "dimensions": slice_names, "rows": [
        {"model": m, **{s: (((q_idx.get((m, pop)) or {}).get("metrics") or {}).get("slices") or {}).get(s, {}).get("precision") for s in slice_names}} for m in ids]}

    # Per-population quality, never pooled.
    pop_quality = {}
    for pid in cfg["quality_populations"]:
        rows = []
        for m in ids:
            a = q_idx.get((m, pid))
            if a is None:
                rows.append({"model": m, "state": "not-measured"})
            elif a["status"] != "ok":
                rows.append({"model": m, "state": "unavailable", "reason": a["reason"]})
            else:
                rows.append({"model": m, "state": "ok", "run_id": a["run_id"], "overall": a["metrics"]["overall"],
                             "slices": a["metrics"].get("slices") or {}})
        pop_quality[pid] = rows

    # Generated known limitations.
    for e in cfg["candidates"]:
        if e["pin_status"] != "resolved":
            limitations.append(f"{e['id']}: pin {e['pin_status']} ({e.get('blocked_by') or e.get('unavailable_reason')})")
    for pid in cfg["quality_populations"]:
        p = by_id(pop_reg)[pid]
        if p["status"] != "available":
            limitations.append(f"population {pid} is {p['status']}: {p.get('blocked_by')}")
    for m, miss in sorted(incomplete.items()):
        limitations.append(f"{m}: incomplete on {len(miss)} dimension(s), excluded from Pareto ranking")
    for m, why in sorted(unavailable.items()):
        limitations.append(f"{m}: unavailable ({why})")
    for r in rejected:
        limitations.append(f"artifact {r['run_id']} ({r['kind']}) rejected: {r['reason']}")
    if not acc_q and not acc_p:
        limitations.append("No accepted ner-eval artifacts: every value in this report is 'not measured'.")

    return {
        "schema": "fastner-benchmarks.bakeoff-report/1",
        "bakeoff_id": cfg["bakeoff_id"],
        "policy_version": policy["policy_version"],
        "no_single_score": policy["no_single_score"],
        "metric_protocol_versions": protos,
        "evaluator_versions": sorted({a["evaluator_version"] for a in acc_q + acc_p}),
        "performance_environments": envs,
        "populations": accounting_table(pop_reg, acc_q, root),
        "pins": pin_table(cfg),
        "accepted_artifacts": {"quality": sorted(a["run_id"] for a in acc_q), "perf": sorted(a["run_id"] for a in acc_p)},
        "rejected_artifacts": sorted(rejected, key=lambda r: (r["kind"], r["run_id"])),
        "values": values,
        "unavailable": unavailable,
        "views": views,
        "population_quality": pop_quality,
        "pareto": {"dimensions": [d["id"] for d in dims], "frontier": front, "dominated": dominated, "incomplete": incomplete},
        "known_limitations": limitations,
    }


def _fmt(v, unit=None):
    if v is None:
        return "n/a"
    if isinstance(v, float):
        return f"{v:.4f}" if v <= 1 else f"{v:.2f}"
    return str(v)


def render_markdown(r):
    L = [f"# Bakeoff report: {r['bakeoff_id']}", "",
         "> Generated by `python -m fnbench report`. Do not edit; fix the data or the generator.", "",
         f"- Qualification policy: **{r['policy_version']}** (no single score: {r['no_single_score']})",
         f"- Metric protocol: {', '.join(r['metric_protocol_versions']) or 'none (no artifacts)'}",
         f"- Evaluator: {', '.join(r['evaluator_versions']) or 'none (no artifacts)'}",
         f"- Performance environment: {', '.join(r['performance_environments']) or 'none'}",
         "- `n/a` means not measured or unavailable. It is never zero.", ""]
    L += ["## Populations (never pooled)", "", "| population | role | status | cases | runs |", "|---|---|---|---|---|"]
    for p in r["populations"]:
        L.append(f"| {p['id']} | {p['role']} | {p['status']} | {_fmt(p['case_count'])} | {', '.join(p['artifact_runs']) or 'none'} |")
    L += ["", "## Pins", "", "| id | role | pin | version/revision | digest | size | config hash |", "|---|---|---|---|---|---|---|"]
    for p in r["pins"]:
        L.append(f"| {p['id']} | {p['role']} | {p['pin_status']} | {_fmt(p['version'])} | {_fmt(p['artifact_digest'])} | {_fmt(p['model_size_bytes'])} | {p['config_hash'][:19]}… |")
    for vid, v in r["views"].items():
        L += ["", f"## {v['title']}", ""]
        cols = v["dimensions"]
        extra = ["delta_bytes"] if vid in ("binary_size", "wasm_size") else []
        if not cols:
            L.append("No collision slices measured.")
            continue
        L += ["| model | " + " | ".join(cols + extra) + " |", "|---|" + "---|" * len(cols + extra)]
        for row in v["rows"]:
            L.append(f"| {row['model']} | " + " | ".join(_fmt(row.get(c)) for c in cols + extra) + " |")
    L += ["", "## Per-population quality", ""]
    for pid, rows in r["population_quality"].items():
        L += [f"### {pid}", "", "| model | state | P | R | F1 |", "|---|---|---|---|---|"]
        for row in rows:
            o = row.get("overall") or {}
            L.append(f"| {row['model']} | {row['state']}{' — ' + row['reason'] if row.get('reason') else ''} | {_fmt(o.get('precision'))} | {_fmt(o.get('recall'))} | {_fmt(o.get('f1'))} |")
        L.append("")
    pa = r["pareto"]
    L += ["## Pareto frontier (candidates only)", "",
          f"- Frontier: {', '.join(pa['frontier']) or 'empty — no candidate is complete on every dimension'}",
          *[f"- Dominated: {k} by {', '.join(v)}" for k, v in sorted(pa["dominated"].items())],
          *[f"- Incomplete: {k} (missing {len(v)}: {', '.join(v[:4])}{'…' if len(v) > 4 else ''})" for k, v in sorted(pa["incomplete"].items())],
          "", "## Known limitations", ""]
    L += [f"- {x}" for x in r["known_limitations"]] or ["- none"]
    return "\n".join(L) + "\n"


def generate(root=ROOT, artifacts_dir=None):
    policy, cfg, reg = load_policy(), load_candidates(), load_populations()
    q, p = load_bakeoff(cfg["bakeoff_id"], artifacts_dir)
    rep = build_report(policy, cfg, reg, q, p, root)
    return canonical_json(rep), render_markdown(rep)


def main(argv):
    ap = argparse.ArgumentParser(prog="fnbench report")
    ap.add_argument("--check", action="store_true", help="fail if committed reports differ from regenerated output")
    a = ap.parse_args(argv)
    js, md = generate()
    cfg = load_candidates()
    out = ROOT / "reports" / "bakeoff" / cfg["bakeoff_id"]
    if a.check:
        ok = (out / "report.json").read_text() == js and (out / "report.md").read_text() == md
        print("reports up to date" if ok else "reports are stale: run `python -m fnbench report`")
        return 0 if ok else 1
    write_text(out / "report.json", js)
    write_text(out / "report.md", md)
    print(f"wrote {out}")
    return 0
