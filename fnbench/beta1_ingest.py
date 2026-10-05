"""Ingest the ner-eval Beta 1 plan (`fastner-beta1`) into normalized, aggregate-only artifacts.

Quality (with 95% intervals), calibration and repeated native/shim performance, verified against the
committed Beta 1 pins. Fails hard on any disagreement. No diagnostics text is kept.
"""
import argparse
import json
from pathlib import Path

from .corpus import CORPORA, describe
from .populations import load_populations
from .util import ROOT, canonical_json, load_json, sha256_file, write_text

CFG_PATH = ROOT / "beta1" / "config.json"
Q_SCHEMA = "fastner-benchmarks.quality/3"
C_SCHEMA = "fastner-benchmarks.calibration/1"
P_SCHEMA = "fastner-benchmarks.perf/3"
COUNT_KEYS = ("exact", "over_wide", "under_wide", "boundary_overlap", "wrong_type_gold", "miss", "false_positive",
              "false_positive_asserted_negative", "ambiguous", "duplicate", "gold_total", "pred_total")
MODES = {"strict": "strict", "boundary_lenient": "lenient"}
MIB = 1048576


class Beta1IngestError(ValueError):
    pass


def load_cfg(path=CFG_PATH):
    return load_json(path)


def _jl(p):
    return json.loads(Path(p).read_text(encoding="utf-8"))


def _block(b, unc=None):
    out = {"cases": b.get("cases")}
    for src, dst in MODES.items():
        m = (b["metrics"] or {}).get(src) or {}
        out[dst] = {k: m.get(k) for k in ("precision", "recall", "f1")}
    out["counts"] = {k: (b.get("counts") or {}).get(k) for k in COUNT_KEYS}
    u = unc if unc is not None else b.get("uncertainty")
    if u:
        iv = ((u.get("strict_f1") or {}).get("interval")) or {}
        out["strict_f1_interval"] = [iv.get("lower"), iv.get("upper")] if iv else None
        out["low_n"] = u.get("low_n")
        out["low_n_reasons"] = u.get("low_n_reasons")
    return out


def pin_for_adapter(cfg, aid):
    c = cfg["candidate"]
    for key, a in c["adapters"].items():
        if a["adapter_id"] == aid:
            return {"id": aid, "role": "candidate", "variant": key}
    r = cfg["references"].get(aid)
    if r:
        return {"id": r["pin"], "role": r["role"], "model_digest": r["model_digest"]}
    raise Beta1IngestError(f"{aid}: adapter has no Beta 1 pin")


def check_identity(cfg, pin, ad, ctx):
    """Adapter identity (from the artifact) must equal the committed pin."""
    c, ident, errs = cfg["candidate"], ad["identity"], []
    m = ident["model"]
    if pin["role"] == "candidate":
        if m["digest"] != c["model"]["dir_digest"]:
            errs.append("model directory digest differs from pin")
        if m["size_bytes"] != c["model"]["size_bytes"]:
            errs.append("model size differs from pin")
        if m["version"] != c["model"]["version"]:
            errs.append("model version differs from pin")
        if ad["tags"].get("runtime_tree") != c["runtime"]["crate_tree"]:
            errs.append("runtime crate tree differs from pin")
        rt = {x["name"]: x["version"] for x in ident["runtime"]}
        if pin["variant"] == "native":
            # Only the native adapter reports the commit and per-model identities; the shim is tied to the
            # same source through the crate tree hash and the model directory digest checked above.
            if rt.get("fastner-commit") != c["runtime"]["commit"]:
                errs.append("runtime commit differs from pin")
            for f in c["model"]["files"]:
                if rt.get(f"fastner-model:{f['name']}") != f["model_identity"]:
                    errs.append(f"model identity of {f['name']} differs from pin")
        elif ad["tags"].get("role") != "candidate-transport-comparison":
            errs.append("shim adapter is not tagged as the transport comparison")
        want = c["adapters"][pin["variant"]].get("version")
        if want and ident["adapter_version"] != want:
            errs.append("adapter version differs from pin")
    elif pin["role"] in ("reference", "control"):
        if m["digest"] != pin["model_digest"]:
            errs.append("reference/control model digest differs from the Alpha pin")
    if errs:
        raise Beta1IngestError(f"{ctx} {pin['id']}: " + "; ".join(errs))


def _sizes(ad):
    by = {a["role"]: a["size_bytes"] for a in ad["artifacts"]}
    return {"model_bytes": by.get("model", ad["identity"]["model"].get("size_bytes")), "binary_bytes": by.get("binary"),
            "wasm_bytes": by.get("wasm")}


def _stat(s, key):
    v = (s.get(key) or {})
    return {k: v.get(k) for k in ("median", "min", "max", "max_over_min", "n")} if v else None


def ingest(root, cfg=None, reg=None):
    cfg, reg = cfg or load_cfg(), reg or load_populations()
    base = Path(root) / cfg["source"]["ner_eval_path"]
    pm = _jl(base / "plan-manifest.json")
    ver = _jl(base / "plan-verification.json")
    src = cfg["source"]
    if pm["digest"] != src["plan_manifest_digest"] or pm["plan_digest"] != src["plan_digest"]:
        raise Beta1IngestError("plan manifest/plan digest differs from the pinned plan")
    if not ver["identical"] or ver["differences"] or ver["plan_manifest_digest"] != pm["digest"]:
        raise Beta1IngestError("ner-eval plan verification is not clean or belongs to another plan")
    byid = {p["population_id"]: p for p in pm["populations"]}
    preg = {p["id"]: p for p in reg["populations"]}
    out, files, runs = {}, {}, []
    protos, evals, hw = set(), set(), set()
    for run in src["runs"]:
        pid = run["population_id"]
        rid = cfg["populations"][pid]
        rdir = base / run["path"]
        man = _jl(rdir / "run-manifest.json")
        if man["run"]["run_id"] != run["run_id"] or man["digest"] != run["run_manifest_digest"] or byid[pid]["run_manifest_digest"] != man["digest"]:
            raise Beta1IngestError(f"{pid}: run manifest differs from the pinned plan entry")
        corpus = man["corpus"]
        pop = preg[rid]
        if corpus["content_digest"] != run["content_digest"] or corpus["case_count"] != run["case_count"]:
            raise Beta1IngestError(f"{pid}: corpus identity differs from the plan pin")
        if pop["artifact"]["kind"] == "case-jsonl":
            d = describe(rid)
            if d["content_digest"] != corpus["content_digest"] or d["case_count"] != corpus["case_count"]:
                raise Beta1IngestError(f"{rid}: measured corpus differs from the committed corpus (stale measurement)")
        else:
            ident = pop["identity"]
            if corpus["content_digest"] != ident["snapshot_digest"] or corpus["case_count"] != ident["case_count"] or corpus["snapshot_id"] != ident["snapshot_id"]:
                raise Beta1IngestError(f"{pid}: snapshot differs from the pinned evidence identity")
        protos.add(json.dumps(man["protocols"], sort_keys=True))
        evals.add(man["evaluator"]["version"])
        seen = set()
        for ent in man["quality_artifacts"]:
            a = _jl(rdir / ent["path"])
            aid = a["adapter"]["adapter_id"]
            if aid != ent["adapter_id"] or a["digest"] != ent["digest"] or a["corpus"]["content_digest"] != corpus["content_digest"]:
                raise Beta1IngestError(f"{pid}/{aid}: artifact does not match the run manifest")
            if ent["status"] != "ok":
                raise Beta1IngestError(f"{pid}/{aid}: adapter run is {ent['status']} (the plan requires all ok)")
            pin = pin_for_adapter(cfg, aid)
            check_identity(cfg, pin, a["adapter"], pid)
            seen.add(aid)
            res = a["results"]
            unc = res.get("overall_uncertainty")
            norm = {"schema": Q_SCHEMA, "run_id": f"{run['run_id']}:{aid}", "evaluator_version": a["evaluator"]["version"],
                    "metric_protocol_version": a["protocols"]["measurement"], "slice_spec": a["protocols"]["slice_spec"],
                    "uncertainty_protocol": a["protocols"].get("uncertainty"),
                    "source": {"ner_eval_run_id": run["run_id"], "ner_eval_run_manifest_digest": man["digest"], "artifact_digest": a["digest"],
                               "artifact_file_sha256": sha256_file(rdir / ent["path"]), "path": f"{src['ner_eval_path']}/{run['path']}/{ent['path']}"},
                    "corpus": {"id": rid, "snapshot_id": corpus["snapshot_id"], "case_count": corpus["case_count"], "digest": corpus["content_digest"],
                               "redistribution": corpus.get("redistribution")},
                    "model": {"id": pin["id"], "adapter_id": aid, "artifact_digest": a["adapter"]["identity"]["model"]["digest"]},
                    "transport": a["adapter"]["transport"], "status": "ok",
                    "runtime": {"tree": a["adapter"]["tags"].get("runtime_tree"),
                                "commit": {x["name"]: x["version"] for x in a["adapter"]["identity"]["runtime"]}.get("fastner-commit")},
                    "metrics": {"overall": _block({"cases": res["cases"], **res["overall"]}, unc),
                                "slices": {s["id"].split("/", 1)[1]: _block(s) for s in res["slices"]["slices"]}}}
            if pop["artifact"]["kind"] == "case-jsonl" and pin["role"] != "control":
                diag = res["diagnostics"]
                if diag.get("truncated"):
                    raise Beta1IngestError(f"{pid}/{aid}: diagnostics truncated")
                norm["failures"] = sorted(({"case_id": r["case_id"], "outcome": r["outcome"], "region": r.get("region")} for r in diag["records"]),
                                          key=lambda r: (r["case_id"], r["outcome"], r["region"] or ""))
            out[f"quality/{rid}/{pin['id']}.json"] = canonical_json(norm)
            files[norm["source"]["path"]] = norm["source"]["artifact_file_sha256"]
        for ent in man["calibration_artifacts"]:
            if ent["status"] == "not-applicable":
                continue
            c = _jl(rdir / ent["path"])
            aid = c["adapter"]["adapter_id"]
            if ent["status"] != "ok" or aid not in seen:
                raise Beta1IngestError(f"{pid}/{aid}: calibration artifact is {ent['status']}")
            pin = pin_for_adapter(cfg, aid)
            st = c["results"]["overall"]["stats"]
            cal = {"schema": C_SCHEMA, "run_id": f"{run['run_id']}:{aid}:cal", "protocol": c["protocols"]["calibration"],
                   "source": {"ner_eval_run_id": run["run_id"], "artifact_digest": c["digest"], "artifact_file_sha256": sha256_file(rdir / ent["path"]),
                              "path": f"{src['ner_eval_path']}/{run['path']}/{ent['path']}"},
                   "corpus": {"id": rid, "digest": corpus["content_digest"], "case_count": corpus["case_count"]},
                   "model": {"id": pin["id"], "adapter_id": aid, "artifact_digest": c["adapter"]["identity"]["model"]["digest"]},
                   "overall": {"n": c["results"]["overall"]["n"], "low_n": c["results"]["overall"]["low_n"],
                               **{k: st.get(k) for k in ("accuracy", "mean_confidence", "confidence_minus_accuracy", "ece_equal_mass", "ece_equal_width",
                                                         "mce_equal_width", "brier", "log_loss", "auroc", "correct")}},
                   "low_n_below": c["results"]["low_n_below"]}
            out[f"calibration/{rid}/{pin['id']}.json"] = canonical_json(cal)
            files[cal["source"]["path"]] = cal["source"]["artifact_file_sha256"]
        pidx_path = rdir / "performance-index.json"
        if pidx_path.exists():
            pidx = _jl(pidx_path)
            if pidx["run"]["run_id"] != run["run_id"]:
                raise Beta1IngestError("performance index belongs to another run")
            hw.add(pidx["environment_hardware_class"])
            for ent in pidx["artifacts"]:
                a = _jl(rdir / ent["path"])
                aid = a["adapter"]["adapter_id"]
                if ent["status"] != "ok" or aid not in seen:
                    raise Beta1IngestError(f"{aid}: performance artifact is {ent['status']}")
                pin = pin_for_adapter(cfg, aid)
                check_identity(cfg, pin, a["adapter"], "perf")
                if a["environment"]["hardware_class"] != pidx["environment_hardware_class"]:
                    raise Beta1IngestError(f"{aid}: hardware class differs from the index")
                env = a["environment"]
                cells = []
                for c in a["cells"]:
                    if c.get("failure"):
                        raise Beta1IngestError(f"{aid}: failed performance cell")
                    s = c["summary"]
                    cells.append({"batch_size": c["batch_size"], "threads": c["requested_threads"], "effective_threads": c["effective_threads"],
                                  "repeats": s["repeats"], "memory_scope": c["memory"]["scope"], "baseline_rss_bytes": c["memory"].get("baseline_rss_bytes"),
                                  "cases_per_sec": _stat(s, "cases_per_sec"), "startup_us": _stat(s, "startup_us"), "first_batch_us": _stat(s, "first_batch_us"),
                                  "warm_batch_p50_us": _stat(s, "warm_batch_p50_us"), "warm_batch_p95_us": _stat(s, "warm_batch_p95_us"),
                                  "peak_rss_bytes": _stat(s, "peak_rss_bytes"), "runtime_per_case_p50_us": _stat(s, "runtime_per_case_p50_us")})
                norm = {"schema": P_SCHEMA, "run_id": f"{run['run_id']}:{aid}:perf", "protocol": a["protocol"], "parameters": a["parameters"],
                        "source": {"ner_eval_run_id": run["run_id"], "artifact_digest": a["digest"], "artifact_file_sha256": sha256_file(rdir / ent["path"]),
                                   "path": f"{src['ner_eval_path']}/{run['path']}/{ent['path']}"},
                        "model": {"id": pin["id"], "adapter_id": aid, "artifact_digest": a["adapter"]["identity"]["model"]["digest"]},
                        "environment": {"id": env["hardware_class"], "description": f"{env['os']['name']} {env['os']['version']} {env['arch']}, {env['cpu']['model']} ({env['cpu']['logical_cores']} logical cores), {env['evaluator']['rustc']}, evaluator {env['evaluator']['version']} [{env['evaluator']['profile']}]"},
                        "transport": a["adapter"]["transport"], "status": "ok", "workload": {k: a["workload"][k] for k in ("cases", "text_bytes", "order")},
                        "measurement_notes": a["measurement_notes"], "sizes": _sizes(a["adapter"]), "cells": cells}
                out[f"perf/{pin['id']}.json"] = canonical_json(norm)
                files[norm["source"]["path"]] = norm["source"]["artifact_file_sha256"]
        runs.append({"population_id": pid, "registry_id": rid, "run_id": run["run_id"], "run_manifest_digest": man["digest"]})
    if len(protos) != 1 or len(evals) != 1:
        raise Beta1IngestError("the plan mixes protocol sets or evaluator versions")
    if evals != {src["evaluator_version"]} or hw and len(hw) != 1:
        raise Beta1IngestError("evaluator version or hardware class differs from the pin")
    manifest = {"schema": "fastner-benchmarks.beta1-ingest-manifest/1", "plan_id": src["plan_id"], "plan_digest": src["plan_digest"],
                "plan_manifest_digest": pm["digest"], "plan_verification": {"identical": ver["identical"], "files_compared": ver["files_compared"], "digest": ver["digest"]},
                "ner_eval_commit": src["ner_eval_commit"], "evaluator_version": src["evaluator_version"], "protocols": json.loads(next(iter(protos))),
                "hardware_class": sorted(hw), "runs": runs,
                "dropped": "diagnostic text/spans and per-projection detail; failures kept as case id + outcome for own corpora only; calibration reliability bins and operating curves not kept",
                "source_artifact_file_sha256": dict(sorted(files.items()))}
    out["ingest-manifest.json"] = canonical_json(manifest)
    return out, manifest


def main(argv):
    ap = argparse.ArgumentParser(prog="fnbench beta1-ingest")
    ap.add_argument("--source", default=str(ROOT.parent / "ner-eval"))
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args(argv)
    if a.check and not Path(a.source).exists():
        print("beta1 ingest check skipped: ner-eval checkout not available (committed artifacts are the source of truth)")
        return 0
    files, _ = ingest(a.source)
    base = ROOT / "artifacts" / "beta1"
    if a.check:
        bad = [p for p, t in files.items() if not (base / p).exists() or (base / p).read_text(encoding="utf-8") != t]
        extra = [str(p.relative_to(base)) for p in base.rglob("*.json") if str(p.relative_to(base)) not in files]
        print("beta1 artifacts up to date" if not (bad or extra) else f"stale: {bad} extra: {extra}")
        return 1 if bad or extra else 0
    for p, t in files.items():
        write_text(base / p, t)
    print(f"ingested {len(files)} files into {base}")
    return 0
