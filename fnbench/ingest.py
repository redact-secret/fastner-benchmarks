"""Ingest real ner-eval run output (`ner-eval.artifacts/1`) into normalized, aggregate-only artifacts.

Fails hard on any disagreement between the run, the committed pins and the population registry.
Diagnostics and anything resembling case text are dropped (the snapshot is internal-only).
"""
import argparse
import json
from pathlib import Path

from .artifacts import P_SCHEMA, Q_SCHEMA
from .pins import load_candidates
from .populations import by_id, load_populations
from .util import ROOT, canonical_json, get_path, sha256_file, write_text

MODES = {"strict": "strict", "boundary_lenient": "lenient"}
COUNT_KEYS = ("exact", "over_wide", "under_wide", "boundary_overlap", "wrong_type_gold", "miss", "false_positive",
              "false_positive_asserted_negative", "ambiguous", "duplicate", "gold_total", "pred_total")


class IngestError(ValueError):
    pass


def _jload(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _block(b):
    out = {"cases": b.get("cases")}
    for src, dst in MODES.items():
        m = (b["metrics"] or {}).get(src) or {}
        out[dst] = {k: m.get(k) for k in ("precision", "recall", "f1")}
    out["counts"] = {k: (b.get("counts") or {}).get(k) for k in COUNT_KEYS}
    return out


def _population_for(reg, corpus):
    for p in reg["populations"]:
        if p["identity"].get("snapshot_id") == corpus["snapshot_id"]:
            if p["identity"]["snapshot_digest"] != corpus["content_digest"]:
                raise IngestError(f"snapshot {corpus['snapshot_id']}: digest differs from pinned population")
            if p["identity"]["case_count"] != corpus["case_count"]:
                raise IngestError("snapshot case_count differs from pinned population")
            return p
    raise IngestError(f"run corpus {corpus['snapshot_id']} is not a pinned population")


def _check_pin(pin, ad):
    ident, errs = ad["identity"], []
    m = ident["model"]
    if m["digest"] != get_path(pin, "model.artifact_digest"):
        errs.append("model digest differs from pin")
    if pin["role"] != "control" and m["size_bytes"] != get_path(pin, "model.size_bytes"):
        errs.append("model size differs from pin")
    if pin["role"] == "candidate":
        if ad["tags"].get("runtime_commit") != get_path(pin, "runtime.commit"):
            errs.append("runtime commit differs from pin")
        if m.get("version") != get_path(pin, "model.version"):
            errs.append("model version differs from pin")
    if pin["role"] == "reference":
        if get_path(pin, "model.revision") and m.get("revision") != get_path(pin, "model.revision"):
            errs.append("model revision differs from pin")
        if (get_path(pin, "model.version") and m.get("version") != get_path(pin, "model.version")):
            errs.append("model version differs from pin")
    if errs:
        raise IngestError(f"{pin['id']}: " + "; ".join(errs))


def _sizes(ad):
    by = {a["role"]: a["size_bytes"] for a in ad["artifacts"]}
    return {"model_bytes": by.get("model", ad["identity"]["model"].get("size_bytes")), "binary_bytes": by.get("binary"), "wasm_bytes": by.get("wasm")}


def ingest(source, cfg=None, reg=None):
    """Return ({relative_path: json_text}, manifest_dict)."""
    src = Path(source)
    cfg, reg = cfg or load_candidates(), reg or load_populations()
    man = _jload(src / "run-manifest.json")
    run_id = man["run"]["run_id"]
    if run_id != cfg["source_run"]["ner_eval_run_id"]:
        raise IngestError(f"run {run_id} is not the pinned source run {cfg['source_run']['ner_eval_run_id']}")
    pop = _population_for(reg, man["corpus"])
    pins = {e["adapter_id"]: e for e in cfg["candidates"] if e.get("adapter_id")}
    pidx = _jload(src / "performance-index.json")
    if pidx["run"]["run_id"] != run_id:
        raise IngestError("performance index belongs to a different run")
    out, files = {}, {}
    seen = set()
    for ent in man["quality_artifacts"]:
        path = src / ent["path"]
        a = _jload(path)
        aid = a["adapter"]["adapter_id"]
        if aid != ent["adapter_id"] or a["digest"] != ent["digest"]:
            raise IngestError(f"{aid}: artifact does not match run-manifest entry")
        if a["corpus"]["content_digest"] != man["corpus"]["content_digest"]:
            raise IngestError(f"{aid}: artifact corpus differs from run corpus")
        if aid not in pins:
            raise IngestError(f"{aid}: adapter has no pin in policy/candidates.json")
        pin = pins[aid]
        _check_pin(pin, a["adapter"])
        seen.add(aid)
        norm = {"schema": Q_SCHEMA, "run_id": f"{run_id}:{aid}", "evaluator_version": a["evaluator"]["version"],
                "metric_protocol_version": a["protocols"]["measurement"], "slice_spec": a["protocols"]["slice_spec"],
                "source": {"ner_eval_run_id": run_id, "ner_eval_run_manifest_digest": man["digest"], "artifact_digest": a["digest"],
                           "artifact_file_sha256": sha256_file(path), "path": f"results/alpha1-full/{ent['path']}"},
                "corpus": {"id": pop["id"], "snapshot_id": a["corpus"]["snapshot_id"], "case_count": a["corpus"]["case_count"],
                           "digest": a["corpus"]["content_digest"], "redistribution": a["corpus"]["redistribution"]},
                "model": {"id": pin["id"], "adapter_id": aid, "artifact_digest": a["adapter"]["identity"]["model"]["digest"]},
                "status": ent["status"]}
        if ent["status"] != "ok":
            norm["reason"] = json.dumps(a.get("failure"), sort_keys=True) if a.get("failure") else f"adapter status {ent['status']}"
        else:
            res = a["results"]
            norm["metrics"] = {"overall": _block({"cases": res["cases"], **res["overall"]}),
                               "slices": {s["id"].split("/", 1)[1]: _block(s) for s in res["slices"]["slices"]}}
        out[f"quality/{pin['id']}.json"] = canonical_json(norm)
        files[ent["path"]] = norm["source"]["artifact_file_sha256"]
    for ent in pidx["artifacts"]:
        path = src / ent["path"]
        a = _jload(path)
        aid = a["adapter"]["adapter_id"]
        if aid not in pins or aid not in seen:
            raise IngestError(f"{aid}: performance artifact without a matching pinned quality artifact")
        if a["environment"]["hardware_class"] != pidx["environment_hardware_class"]:
            raise IngestError(f"{aid}: hardware class differs from index")
        _check_pin(pins[aid], a["adapter"])
        env = a["environment"]
        norm = {"schema": P_SCHEMA, "run_id": f"{run_id}:{aid}:perf", "evaluator_version": a["environment"]["evaluator"]["version"],
                "protocol": a["protocol"], "parameters": a["parameters"],
                "source": {"ner_eval_run_id": run_id, "artifact_digest": a["digest"], "artifact_file_sha256": sha256_file(path), "path": f"results/alpha1-full/{ent['path']}"},
                "model": {"id": pins[aid]["id"], "adapter_id": aid, "artifact_digest": a["adapter"]["identity"]["model"]["digest"]},
                "environment": {"id": env["hardware_class"], "description": f"{env['os']['name']} {env['os']['version']} {env['arch']}, {env['cpu']['model']} ({env['cpu']['logical_cores']} logical cores), {env['evaluator']['rustc']}, evaluator {env['evaluator']['version']} [{env['evaluator']['profile']}]"},
                "transport": a["adapter"]["transport"], "status": ent["status"],
                "measurement_notes": a["measurement_notes"], "sizes": _sizes(a["adapter"])}
        if ent["status"] != "ok":
            norm["reason"] = json.dumps(a.get("failure"), sort_keys=True) if a.get("failure") else f"adapter status {ent['status']}"
        else:
            cells = []
            for c in a["cells"]:
                if c.get("failure"):
                    continue
                cells.append({"batch_size": c["batch_size"], "threads": c["requested_threads"], "effective_threads": c["effective_threads"],
                              "cases_per_sec": c["throughput"]["cases_per_sec"], "per_case_p50_us": c["warm"]["per_case"]["p50_us"],
                              "per_case_p95_us": c["warm"]["per_case"]["p95_us"], "peak_rss_bytes": c["memory"]["peak_rss_bytes"],
                              "rss_scope": c["memory"]["scope"], "cold_startup_us": [x["startup_us"] for x in c["cold"]],
                              "first_batch_us": [x["first_batch_us"] for x in c["cold"]]})
            norm["cells"] = cells
        out[f"perf/{pins[aid]['id']}.json"] = canonical_json(norm)
        files[ent["path"]] = norm["source"]["artifact_file_sha256"]
    missing = set(pins) & {e["adapter_id"] for e in cfg["candidates"] if e["pin_status"] == "resolved"} - seen
    if missing:
        raise IngestError(f"resolved pins with no artifact in the run: {sorted(missing)}")
    manifest = {"schema": "fastner-benchmarks.ingest-manifest/1", "bakeoff_id": cfg["bakeoff_id"], "ner_eval_run_id": run_id,
                "ner_eval_commit": cfg["source_run"]["ner_eval_commit"], "ner_eval_run_manifest_digest": man["digest"],
                "measurement_protocol": man["protocols"]["measurement"], "performance_protocol": man["protocols"]["performance"],
                "snapshot_id": man["corpus"]["snapshot_id"], "redistribution": man["corpus"]["redistribution"],
                "dropped": "diagnostics, per-case records and per_projection/per_kind detail (aggregate-only ingest)",
                "source_artifact_file_sha256": dict(sorted(files.items()))}
    out["ingest-manifest.json"] = canonical_json(manifest)
    return out, manifest


def main(argv):
    ap = argparse.ArgumentParser(prog="fnbench ingest")
    ap.add_argument("--source", default=str(ROOT.parent / "ner-eval" / "results" / "alpha1-full"))
    ap.add_argument("--check", action="store_true", help="fail if committed artifacts differ from a fresh ingest")
    a = ap.parse_args(argv)
    cfg = load_candidates()
    if a.check and not Path(a.source).exists():
        print(f"ingest check skipped: source {a.source} not available (committed artifacts are the source of truth)")
        return 0
    files, _ = ingest(a.source, cfg)
    base = ROOT / "artifacts" / "bakeoff" / cfg["bakeoff_id"]
    if a.check:
        bad = [p for p, t in files.items() if not (base / p).exists() or (base / p).read_text(encoding="utf-8") != t]
        print("ingested artifacts up to date" if not bad else f"stale: {bad}")
        return 1 if bad else 0
    for p, t in files.items():
        write_text(base / p, t)
    print(f"ingested {len(files)} files into {base}")
    return 0
