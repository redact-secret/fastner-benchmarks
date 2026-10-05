"""Beta 1 qualification (evaluation only).

Stages: pins -> architecture -> quality -> calibration -> performance/size -> support matrix -> record.
Rules come from beta1/acceptance.json (committed before any result was evaluated); thresholds come from
policy/support-gates.json (gate set 0.3.0, unchanged) plus the one calibration gate declared in the rules.
Nothing here changes a candidate, a corpus, evidence or evaluator semantics.
"""
import argparse
import copy
import json
import re

from .beta1_ingest import MIB, load_cfg
from .corpus import describe
from .policy import load_policy
from .populations import load_populations
from .qualify import beta_suggestions, load_criteria
from .report import _metric
from .support import evaluate_support, load_gates
from .util import ROOT, canonical_json, load_json, write_text

ACC_PATH = ROOT / "beta1" / "acceptance.json"
BASE = ROOT / "artifacts" / "beta1"
ALPHA_BASE = ROOT / "artifacts" / "bakeoff" / "alpha1-full"
OUT = ROOT / "reports" / "beta1"
FLOOR = "ner-evidence-beta1"
PRODUCT = ("fastner-regression", "fastner-adversarial")
NATIVE, SHIM = "fastner-crf-beta1-native", "fastner-crf-beta1-shim"
REFS = ("ref-spacy-en", "ref-bert-base-ner", "ref-koelectra-ko")


# ---------------------------------------------------------------- loading
def _load_tree(root):
    out = {}
    for f in sorted(root.rglob("*.json")) if root.exists() else []:
        out[str(f.relative_to(root))] = json.loads(f.read_text(encoding="utf-8"))
    return out


def load_artifacts(base=BASE, alpha=ALPHA_BASE):
    t = _load_tree(base)
    q, cal, perf = {}, {}, {}
    for k, a in t.items():
        if k.startswith("quality/"):
            q[(a["corpus"]["id"], a["model"]["id"])] = a
        elif k.startswith("calibration/"):
            cal[(a["corpus"]["id"], a["model"]["id"])] = a
        elif k.startswith("perf/"):
            perf[a["model"]["id"]] = a
    manifest = t.get("ingest-manifest.json")
    aq = {}
    for pop in PRODUCT:
        f = alpha / "quality" / pop / "fastner-b-linear-crf.json"
        if f.exists():
            aq[pop] = json.loads(f.read_text(encoding="utf-8"))
    aperf = alpha / "perf" / "fastner-b-linear-crf.json"
    return {"q": q, "cal": cal, "perf": perf, "manifest": manifest, "alpha_q": aq,
            "alpha_perf": json.loads(aperf.read_text(encoding="utf-8")) if aperf.exists() else None}


# ---------------------------------------------------------------- helpers
def strict(block, k):
    return None if block is None else block["strict"][k]


def check(cid, stage, ok, detail, hard=True, evidence=None):
    return {"id": cid, "stage": stage, "hard": hard, "pass": ok, "detail": detail, **({"evidence": evidence} if evidence is not None else {})}


def perf_values(a):
    """Policy performance dimensions from a perf/3 artifact (1 thread; median over repeats)."""
    cells = [c for c in a["cells"] if c["threads"] == 1]
    one = next(c for c in cells if c["batch_size"] == 1)
    big = max(cells, key=lambda c: c["batch_size"])
    sz = a["sizes"]
    spreads = [c["cases_per_sec"]["max_over_min"] for c in cells if c.get("cases_per_sec")]
    return {"latency_p95_ms": one["warm_batch_p95_us"]["median"] / 1000.0,
            "throughput_docs_per_s": big["cases_per_sec"]["median"],
            "startup_ms": one["startup_us"]["median"] / 1000.0,
            "peak_memory_mb": max(c["peak_rss_bytes"]["median"] for c in cells) / MIB,
            "model_size_bytes": sz["model_bytes"], "binary_size_bytes": sz["binary_bytes"], "wasm_size_bytes": sz["wasm_bytes"],
            "throughput_spread_max_over_min": max(spreads) if spreads else None,
            "memory_scope": one["memory_scope"], "transport": a["transport"]}


def candidate_values(policy, art, floor_model=NATIVE, shim=SHIM, cfg=None):
    """Policy-dimension values for the Beta 1 candidate, with sources and intervals."""
    q = art["q"][(FLOOR, floor_model)]
    pv, sv = perf_values(art["perf"][floor_model]), perf_values(art["perf"][shim])
    vals, srcs, ivs = {}, {}, {}
    for d in policy["dimensions"]:
        s = d["source"]
        if s["artifact"] == "quality":
            vals[d["id"]] = _metric(q, d)
            sl = s.get("slice")
            blk = q["metrics"]["overall"] if sl is None else q["metrics"]["slices"].get(sl)
            if s["metric"] == "f1" and blk and blk.get("strict_f1_interval"):
                ivs[d["id"]] = blk["strict_f1_interval"]
    vals.update(latency_p95_ms=pv["latency_p95_ms"], throughput_docs_per_s=pv["throughput_docs_per_s"], startup_ms=pv["startup_ms"],
                peak_memory_mb=pv["peak_memory_mb"], model_size_bytes=pv["model_size_bytes"],
                runtime_binary_size_bytes=sv["binary_size_bytes"])
    wasm = cfg["candidate"]["wasm_candidate_reported"]
    vals["wasm_size_bytes"] = wasm["bytes"]
    srcs["wasm_size_bytes"] = "candidate-reported"
    srcs["runtime_binary_size_bytes"] = "ner-eval (adapter shim binary, as in Alpha; the native host binary is the evaluator and is not a product cost)"
    cal = art["cal"].get((FLOOR, floor_model))
    vals["calibration_ece"] = cal["overall"]["ece_equal_mass"] if cal else None
    return vals, srcs, ivs, pv, sv


def flat(b):
    out = {"precision": b["strict"]["precision"], "recall": b["strict"]["recall"], "f1": b["strict"]["f1"], "lenient_f1": b["lenient"]["f1"], "cases": b.get("cases")}
    if b.get("strict_f1_interval"):
        out["strict_f1_interval"] = b["strict_f1_interval"]
    out["low_n"] = b.get("low_n")
    return out


def population_quality(art, model):
    rows = {}
    for pop in (FLOOR,) + PRODUCT:
        a = art["q"].get((pop, model))
        rows[pop] = [] if a is None else [{"model": model, "state": "ok", "overall": flat(a["metrics"]["overall"]),
                                           "slices": {k: flat(b) for k, b in sorted(a["metrics"]["slices"].items())}}]
    return rows


# ---------------------------------------------------------------- stages
def stage_pins(cfg, art, reg, acc):
    c, ev, S = cfg["candidate"], cfg["evidence"], "0-pins"
    out = []
    missing = [k for k, v in (("runtime.git_tag", c["runtime"]["git_tag"]), ("runtime.commit", c["runtime"]["commit"]), ("runtime.crate_tree", c["runtime"]["crate_tree"]),
                              ("model.dir_digest", c["model"]["dir_digest"]), ("model.version", c["model"]["version"]),
                              ("adapters.native.version", c["adapters"]["native"].get("version")), ("adapters.shim.version", c["adapters"]["shim"].get("version")))
               if not v]
    bad = []
    if not re.fullmatch(r"[0-9a-f]{40}", c["runtime"]["commit"] or ""):
        bad.append("commit is not a full SHA")
    if not re.fullmatch(r"[0-9a-f]{40}", c["runtime"]["crate_tree"] or ""):
        bad.append("crate tree is not a full SHA")
    for f in c["model"]["files"]:
        if not re.fullmatch(r"[0-9a-f]{64}", f["sha256"]) or not re.fullmatch(r"[0-9a-f]{64}", f["model_identity"]):
            bad.append(f"{f['name']}: digest malformed")
    cand_art = [art["q"][(p, m)] for (p, m) in art["q"] if m in (NATIVE, SHIM)]
    id_ok = all(a["model"]["artifact_digest"] == c["model"]["dir_digest"] and a["runtime"]["tree"] == c["runtime"]["crate_tree"] for a in cand_art)
    nat = [a for a in cand_art if a["model"]["id"] == NATIVE]
    id_ok = id_ok and all(a["runtime"]["commit"] == c["runtime"]["commit"] for a in nat) and bool(nat)
    out.append(check("candidate_pin_complete", S, not missing and not bad and id_ok,
                     f"tag {c['runtime']['git_tag']} -> commit {c['runtime']['commit'][:7]}, crate tree {c['runtime']['crate_tree'][:7]}, model dir {c['model']['dir_digest'][:19]}…; "
                     + ("all artifact identities equal the pin" if id_ok else "ARTIFACT IDENTITY MISMATCH") + (f"; missing {missing}" if missing else "") + (f"; {bad}" if bad else "")))
    fl = [a for (p, m), a in art["q"].items() if p == FLOOR]
    ok = bool(fl) and all(a["corpus"]["digest"] == ev["content_digest"] and a["corpus"]["case_count"] == ev["case_count"] for a in fl)
    pop = next(p for p in reg["populations"] if p["id"] == FLOOR)
    ok = ok and pop["identity"]["snapshot_digest"] == ev["content_digest"]
    out.append(check("evidence_pin_matches", S, ok, f"{ev['snapshot_id']} ({ev['case_count']} cases), digest {ev['content_digest'][:19]}…; published in {ev['published_in']}"))
    mism = []
    for p in PRODUCT + ("candidate-specific",):
        d = describe(p)
        for (pp, m), a in art["q"].items():
            if pp == p and (a["corpus"]["digest"] != d["content_digest"] or a["corpus"]["case_count"] != d["case_count"]):
                mism.append(f"{p}/{m}")
    out.append(check("corpus_digests_match", S, not mism and all((p, NATIVE) in art["q"] for p in PRODUCT + ("candidate-specific",)),
                     "product and candidate-specific corpora measured at the committed content digests" if not mism else f"stale: {mism}"))
    refs_ok = all(art["q"][(FLOOR, r)]["model"]["artifact_digest"] == next(v["model_digest"] for v in cfg["references"].values() if v["pin"] == r) for r in REFS if (FLOOR, r) in art["q"])
    out.append(check("reference_pins_unchanged", S, refs_ok and all((FLOOR, r) in art["q"] for r in REFS), "reference and control digests equal the Alpha pins"))
    man = art["manifest"]
    allq = list(art["q"].values())
    ok = bool(man and man["plan_verification"]["identical"] and len({a["evaluator_version"] for a in allq}) == 1 and len({a["metric_protocol_version"] for a in allq}) == 1
              and len({a["slice_spec"] for a in allq}) == 1 and len(man["hardware_class"]) == 1 and all(a["status"] == "ok" for a in allq))
    out.append(check("run_integrity", S, ok, f"plan verification identical over {man['plan_verification']['files_compared']} files; evaluator {man['evaluator_version']}; protocol {man['protocols']['measurement']}; one hardware class; {len(allq)} quality runs all ok"))
    out.append(check("same_model_both_transports", S, all(art["q"][(p, NATIVE)]["model"]["artifact_digest"] == art["q"][(p, SHIM)]["model"]["artifact_digest"] for p in (FLOOR,) + PRODUCT),
                     "native and shim carry identical model digests"))
    return out


def stage_architecture(cfg, art, acc, refs):
    c, S, tol = cfg["candidate"], "1-architecture", acc["tolerances"]
    out = [check("architecture_unchanged", S, c["class"] == "B-linear-crf" and c["runtime"]["default_features"] == ["cand-crf"], f"class {c['class']}, default features {c['runtime']['default_features']}")]
    adr = c["adrs"]
    promoted = bool(refs.get("alpha1-full", {}).get("on_main")) and refs["alpha1-full"].get("status") == "accepted"
    ok = promoted and all(adr[n]["status"] == "accepted" for n in ("0002", "0003", "0004")) and c["runtime"]["on_main"]
    out.append(check("adr_chain_on_main", S, ok, "ADR-0002 promoted (on main); ADR-0003, ADR-0004 accepted; candidate commit is fastner main"))
    out.append(check("no_new_dependencies", S, c["runtime"]["dependencies"] == 0 and c["runtime"]["cargo_dependencies_section_empty"], f"runtime crate dependencies: {c['runtime']['dependencies']}"))
    ab = cfg["alpha_baseline"]
    mg = c["model"]["size_bytes"] / ab["model_size_bytes"] - 1
    wg = c["wasm_candidate_reported"]["bytes"] / ab["wasm_bytes_ner_eval_measured"] - 1
    out.append(check("size_growth_bounded", S, mg <= tol["model_size_growth"] and wg <= tol["wasm_size_growth"],
                     f"model {ab['model_size_bytes']} -> {c['model']['size_bytes']} bytes ({mg:+.2%}, limit {tol['model_size_growth']:.0%}); WASM {ab['wasm_bytes_ner_eval_measured']} (ner-eval Alpha probe) -> {c['wasm_candidate_reported']['bytes']} (candidate-reported) ({wg:+.2%}, limit {tol['wasm_size_growth']:.0%}); WASM growth vs Alpha tree as reported by fastner: {c['wasm_candidate_reported']['bytes'] / ab['wasm_bytes_candidate_reported_alpha_tree'] - 1:+.2%}",
                     evidence={"model_growth": round(mg, 6), "wasm_growth": round(wg, 6)}))
    return out


def regression_table(art, tol):
    rows = []
    for pop in PRODUCT:
        b, a = art["q"].get((pop, NATIVE)), art["alpha_q"].get(pop)
        if not b or not a:
            continue
        for label, bb, ab in (("overall", b["metrics"]["overall"], a["metrics"]["overall"]),
                              ("language=en", b["metrics"]["slices"].get("language=en"), a["metrics"]["slices"].get("language=en")),
                              ("language=ko", b["metrics"]["slices"].get("language=ko"), a["metrics"]["slices"].get("language=ko"))):
            for m in (("precision", "recall", "f1") if label == "overall" else ("f1",)):
                bv, av = strict(bb, m), strict(ab, m)
                iv = (bb or {}).get("strict_f1_interval") if m == "f1" else None
                rows.append({"population": pop, "slice": label, "metric": m, "alpha": av, "beta1": bv, "delta": None if av is None or bv is None else round(bv - av, 6),
                             "cases": (bb or {}).get("cases"), "ok": None if av is None or bv is None else bv >= av - tol - 1e-12,
                             "beta1_interval": None if not iv else [round(iv[0], 6), round(iv[1], 6)],
                             "alpha_inside_beta1_interval": None if not iv or av is None else iv[0] <= av <= iv[1]})
    return rows


def stage_quality(cfg, art, acc, matrix):
    S, tol = "2-quality", acc["tolerances"]["no_regression_absolute"]
    out = []
    par = []
    for p in (FLOOR,) + PRODUCT + ("candidate-specific",):
        n, s = art["q"].get((p, NATIVE)), art["q"].get((p, SHIM))
        par.append(bool(n and s and n["metrics"] == s["metrics"] and n.get("failures") == s.get("failures")))
    out.append(check("native_shim_parity", S, all(par), "native and shim quality results identical on " + ", ".join(p for p, k in zip((FLOOR,) + PRODUCT + ("candidate-specific",), par) if k)))
    rows = regression_table(art, tol)
    regs = [r for r in rows if r["ok"] is False]
    out.append(check("no_regression_vs_alpha", S, bool(rows) and not regs, f"{len(rows)} like-for-like comparisons on the regression and adversarial corpora (tolerance {tol}); regressions: " + (", ".join(f"{r['population']}/{r['slice']}/{r['metric']} {r['delta']:+.3f}" for r in regs) or "none"),
                     evidence=rows))
    comp = {"regression.en_f1": ("fastner-regression", "language=en", "f1"), "regression.ko_f1": ("fastner-regression", "language=ko", "f1"),
            "adversarial.en_precision": ("fastner-adversarial", "language=en", "precision"), "adversarial.ko_precision": ("fastner-adversarial", "language=ko", "precision")}
    imps = {}
    for g, (pop, sl, m) in comp.items():
        b, a = art["q"].get((pop, NATIVE)), art["alpha_q"].get(pop)
        bv, av = strict(b["metrics"]["slices"].get(sl), m) if b else None, strict(a["metrics"]["slices"].get(sl), m) if a else None
        imps[g] = None if bv is None or av is None else round(bv - av, 6)
    better = [g for g, d in imps.items() if d is not None and d > tol]
    out.append(check("improvement_vs_alpha", S, bool(better), "improved by more than the tolerance: " + (", ".join(f"{g} {imps[g]:+.3f}" for g in better) or "none") + "; all comparable gates: " + ", ".join(f"{g} {d:+.3f}" for g, d in imps.items() if d is not None), evidence=imps))
    return out


def stage_calibration(cfg, art, acc):
    S, mn = "3-calibration", acc["tolerances"]["min_calibration_predictions"]
    n, s = art["cal"].get((FLOOR, NATIVE)), art["cal"].get((FLOOR, SHIM))
    tol = acc["tolerances"].get("calibration_parity_absolute", 0.0)

    def same(a, b):
        return a.keys() == b.keys() and all((a[k] == b[k]) if not isinstance(a[k], float) else abs(a[k] - b[k]) <= tol for k in a)

    ok = bool(n and s and same(n["overall"], s["overall"]) and n["overall"]["n"] >= mn)
    d = n["overall"] if n else {}
    return [check("calibration_measured", S, ok, f"native and shim calibration identical within {tol:g}; n={d.get('n')} scored predictions on {FLOOR}; ECE {d.get('ece_equal_mass', float('nan')):.4f}, mean confidence {d.get('mean_confidence', float('nan')):.3f} vs accuracy {d.get('accuracy', float('nan')):.3f} (over-confident by {d.get('confidence_minus_accuracy', float('nan')):.3f}), Brier {d.get('brier', float('nan')):.3f}, AUROC {d.get('auroc', float('nan')):.3f}")]


def stage_perf(cfg, art, acc, pv, sv, srcs):
    S = "4-performance-size"
    need = ("latency_p95_ms", "throughput_docs_per_s", "startup_ms", "peak_memory_mb", "model_size_bytes", "binary_size_bytes", "wasm_size_bytes")
    vals = {**pv, "binary_size_bytes": sv["binary_size_bytes"], "wasm_size_bytes": cfg["candidate"]["wasm_candidate_reported"]["bytes"]}
    miss = [k for k in need if vals.get(k) is None]
    out = [check("budgets_evaluable", S, not miss, "all seven budget values present" + ("; WASM is candidate-reported, not ner-eval-measured" if not miss else f"; missing {miss}"))]
    sp = pv["throughput_spread_max_over_min"]
    lim = acc["tolerances"]["perf_repeat_max_over_min"]
    out.append(check("perf_repeat_stability", S, sp is not None and sp <= lim, f"throughput repeat spread max/min {sp:.3f} (bound {lim}); a larger spread would make the value inconclusive, not failing"))
    return out


# ---------------------------------------------------------------- support
def build_support(cfg, policy, gates, acc, art, refs, reg):
    vals, srcs, ivs, pv, sv = candidate_values(policy, art, cfg=cfg)
    g = copy.deepcopy(gates)
    cg = acc["stages"][3]["target_gate"]
    for prof in g["profiles"]:
        # Gate caveats written for Alpha (shim-measured, no intervals) do not apply to this measurement set.
        for x in prof["gates"]:
            if x["id"] in ("budget.latency_p95_ms", "budget.throughput", "budget.startup_ms"):
                x["caveat"] = "native in-process, median of 5 repeats (ner-eval protocol 1.2.0); shim shown separately"
            elif x["id"].startswith(("regression.", "adversarial.")):
                x["caveat"] = "tiny seed corpus used during Beta 1 development; ner-eval 95% interval shown for F1 only"
        prof["gates"].append({"id": cg["id"], "title": "Confidence calibration (ECE, equal-mass bins) on the quality floor", "op": cg["op"], "threshold": cg["threshold"],
                              "source": {"dimension": "calibration_ece"}, "caveat": "ece_equal_mass on the Beta 1 snapshot"})
    adr = refs.get("alpha1-full", {})
    state = "promoted" if adr.get("on_main") and adr.get("status") == "accepted" else "recommended-awaiting-adr"
    pin = {"id": NATIVE, "pin_status": "resolved", "version": cfg["candidate"]["runtime"]["git_tag"], "artifact_digest": cfg["candidate"]["model"]["dir_digest"], "config_hash": None}
    rep = {"bakeoff_id": "beta1", "pins": [pin], "values": {NATIVE: vals}, "intervals": {NATIVE: ivs}, "value_sources": {NATIVE: srcs},
           "population_quality": population_quality(art, NATIVE)}
    dec = {"selected": NATIVE, "decision": "recommend", "promotion_state": state}
    m = evaluate_support(g, rep, dec, policy["policy_version"], acc["tolerances"]["min_slice_cases"])
    # extra provisional conditions (rules file)
    popx = {p["id"]: p.get("selection_exposed", False) for p in reg["populations"]}
    for prof in m["profiles"]:
        why = []
        if prof["status"] == "provisional":
            qual = [x for x in prof["gates"] if x["gate"].startswith(("public.", "regression.", "adversarial."))]
            if any(x.get("interval_clarity") == "straddles" for x in qual):
                why.append("a passing quality gate's 95% interval straddles its threshold")
            if any(x.get("value_source") == "candidate-reported" for x in prof["gates"]):
                why.append("a size/performance value is candidate-reported, not ner-eval-measured")
            if all(popx.get(p, False) for p in (FLOOR,) + PRODUCT):
                why.append("no quality evidence from a population outside selection (all populations were used during Beta 1 development)")
            if why:
                prof["status"] = "experimental"
                prof["reasons"] = prof["reasons"] + ["provisional blocked: " + "; ".join(why)]
        prof["selection_exposure"] = {p: popx.get(p) for p in (FLOOR,) + PRODUCT}
    m["schema"] = "fastner-benchmarks.support-matrix/2"
    m["candidate"] = NATIVE
    m["bakeoff_id"] = "beta1"
    return m, vals, srcs, pv, sv


# ---------------------------------------------------------------- record
def watchlist(art, acc):
    q = art["q"][(FLOOR, NATIVE)]
    out = []
    for k, b in sorted(q["metrics"]["slices"].items()):
        f1, pr = b["strict"]["f1"], b["strict"]["precision"]
        if (f1 is not None and f1 < 0.6) or (pr is not None and pr < 0.6):
            out.append({"slice": k, "cases": b["cases"], "strict_precision": pr, "strict_recall": b["strict"]["recall"], "strict_f1": f1, "low_n": b.get("low_n")})
    return out


def case_level_vs_alpha(art):
    """Per product corpus: cases newly failing, fixed, or failing differently vs the Alpha CRF (ids and categories only)."""
    from .corpus import read_built
    out = {}
    for pop in PRODUCT:
        b, a = art["q"].get((pop, NATIVE)), art["alpha_q"].get(pop)
        if not b or not a:
            continue
        cases = {c["id"]: c for c in read_built(pop)}
        fa, fb = {}, {}
        for x in a["failures"]:
            fa.setdefault(x["case_id"], set()).add(x["outcome"])
        for x in b["failures"]:
            fb.setdefault(x["case_id"], set()).add(x["outcome"])
        row = lambda k, oc: {"case_id": k, "outcomes": sorted(oc), "category": cases[k]["category"], "language": cases[k]["slices"]["language"]}
        out[pop] = {"alpha_failing_cases": len(fa), "beta1_failing_cases": len(fb),
                    "new_failures": [row(k, fb[k]) for k in sorted(set(fb) - set(fa))],
                    "fixed": [row(k, fa[k]) for k in sorted(set(fa) - set(fb))],
                    "changed_outcome": [{**row(k, fb[k]), "alpha_outcomes": sorted(fa[k])} for k in sorted(set(fa) & set(fb)) if fa[k] != fb[k]],
                    "unchanged_failing": [row(k, fb[k]) for k in sorted(set(fa) & set(fb)) if fa[k] == fb[k]]}
    return out


def references_table(art):
    q = art["q"]
    base = q[(FLOOR, NATIVE)]["metrics"]["overall"]["strict"]
    rows = []
    for r in REFS + ("control-null", "control-capitalized-run"):
        a = q.get((FLOOR, r))
        if not a:
            continue
        s = a["metrics"]["overall"]["strict"]
        rows.append({"model": r, "strict_precision": s["precision"], "strict_recall": s["recall"], "strict_f1": s["f1"],
                     "en_f1": strict(a["metrics"]["slices"].get("language=en"), "f1"), "ko_f1": strict(a["metrics"]["slices"].get("language=ko"), "f1"),
                     "beta1_f1_minus_this": None if s["f1"] is None else round(base["f1"] - s["f1"], 6)})
    return rows


def evaluate(cfg, acc, policy, gates, reg, art, refs):
    checks = stage_pins(cfg, art, reg, acc) + stage_architecture(cfg, art, acc, refs)
    matrix, vals, srcs, pv, sv = build_support(cfg, policy, gates, acc, art, refs, reg)
    checks += stage_quality(cfg, art, acc, matrix) + stage_calibration(cfg, art, acc) + stage_perf(cfg, art, acc, pv, sv, srcs)
    hard_fail = [c for c in checks if c["hard"] and not c["pass"]]
    prov = [p["profile"] for p in matrix["profiles"] if p["status"] == "provisional"]
    outcome = "A" if hard_fail else ("C" if prov else "B")
    crit = load_criteria()
    sugg, gaps = beta_suggestions(crit, matrix)
    cand_spec = art["q"].get(("candidate-specific", NATIVE))
    feedback = []
    for c in checks:
        if c["id"] == "no_regression_vs_alpha" and not c["pass"]:
            for x in c["evidence"]:
                if x["ok"] is False:
                    feedback.append(f"{x['population']}/{x['slice']}/{x['metric']}: {x['delta']:+.3f} on {x['cases']} cases; Alpha value {x['alpha']:.3f} lies "
                                    + ("inside" if x["alpha_inside_beta1_interval"] else "outside") + f" Beta 1's 95% interval {x['beta1_interval']}. "
                                    "The pre-declared tolerance (0.02 absolute) is not sample-size aware, so on slices this small one extra error exceeds it. "
                                    "The outcome follows the rule as declared; a sample-size-aware tolerance should be proposed for the next rule version, not applied retroactively.")
    perf = {"native": pv, "shim": sv, "alpha_shim_note": "Alpha shim startup (~1.3 s) used protocol 1.1.0 and is not comparable to this plan's protocol 1.2.0 measurements; no performance regression claim is made against Alpha."}
    return {
        "schema": "fastner-benchmarks.beta1-qualification/1", "rule_version": acc["rule_version"], "policy_version": policy["policy_version"],
        "gate_set_version": gates["gate_set_version"], "candidate": {"id": cfg["candidate"]["id"], "tag": cfg["candidate"]["runtime"]["git_tag"], "commit": cfg["candidate"]["runtime"]["commit"],
                                                                      "crate_tree": cfg["candidate"]["runtime"]["crate_tree"], "model_dir_digest": cfg["candidate"]["model"]["dir_digest"], "model_bytes": cfg["candidate"]["model"]["size_bytes"]},
        "ner_eval": {"plan_id": cfg["source"]["plan_id"], "plan_manifest_digest": cfg["source"]["plan_manifest_digest"], "evaluator_version": cfg["source"]["evaluator_version"], "commit": cfg["source"]["ner_eval_commit"]},
        "outcome": outcome, "outcome_label": acc["outcomes"][outcome],
        "outcome_reason": (("hard checks failed: " + ", ".join(c["id"] for c in hard_fail)) if hard_fail else
                           ("every hard check passed; provisional support granted to " + ", ".join(prov)) if prov else
                           "every hard check passed; no profile meets the provisional conditions, so support stays experimental"),
        "checks": checks, "support": [{"profile": p["profile"], "status": p["status"], "reasons": p["reasons"], "gate_counts": p["gate_counts"]} for p in matrix["profiles"]],
        "provisional_blockers": sorted({r for p in matrix["profiles"] for r in p["reasons"] if r.startswith("provisional blocked")}),
        "values": {k: (round(v, 6) if isinstance(v, float) else v) for k, v in vals.items()}, "value_sources": srcs, "performance": perf,
        "regression_vs_alpha": next(c["evidence"] for c in checks if c["id"] == "no_regression_vs_alpha"),
        "case_level_vs_alpha": case_level_vs_alpha(art), "rule_feedback": feedback,
        "references": references_table(art), "slice_watchlist": watchlist(art, acc),
        "candidate_specific_diagnostic": None if not cand_spec else {"cases": cand_spec["corpus"]["case_count"], "strict": cand_spec["metrics"]["overall"]["strict"], "interval": cand_spec["metrics"]["overall"].get("strict_f1_interval"), "non_exact": len(cand_spec.get("failures", []))},
        "evidence_exposure": {"populations": {p["id"]: {"selection_exposed": p.get("selection_exposed"), "is_holdout": p.get("is_holdout"), "note": p.get("selection_note")} for p in reg["populations"] if p["id"] in (FLOOR,) + PRODUCT + ("candidate-specific",)},
                              "statement": cfg["evidence"]["development_exposure"]},
        "calibration": {k: art["cal"][(FLOOR, NATIVE)]["overall"][k] for k in ("n", "accuracy", "mean_confidence", "confidence_minus_accuracy", "ece_equal_mass", "brier", "auroc")},
        "beta2_planning": {"measured_deficits": sugg, "measurement_gaps": gaps, "inputs_not_scheduled": [
            "Independent holdout or independently reviewed population outside selection (required before provisional)",
            "ner-eval to measure the WASM probe (currently candidate-reported)",
            "Add fastner's 18 proposed regression cases (origin beta1-proposal) to the product corpus, then requalify (a corpus change makes older measurements stale)",
            "Mixed-script and organization/person precision slices (see slice watchlist)",
            "Calibration on realistic text (confidence is over-confident on this evidence)"]},
        "_support_matrix": matrix,
    }


def render(r, matrix):
    L = ["# FastNER Beta 1 qualification", "", "> Generated by `python -m fnbench beta1`. Do not edit.", "",
         f"## Outcome: **{r['outcome']}. {r['outcome_label']}**", "", r["outcome_reason"] + ".", "",
         f"- Candidate `{r['candidate']['tag']}` (commit `{r['candidate']['commit'][:12]}`, crate tree `{r['candidate']['crate_tree'][:12]}`), model dir `{r['candidate']['model_dir_digest'][:19]}…`, {r['candidate']['model_bytes']} bytes",
         f"- Rules {r['rule_version']} (committed before results), qualification policy {r['policy_version']}, gate set {r['gate_set_version']} + calibration gate",
         f"- ner-eval {r['ner_eval']['evaluator_version']}, plan `{r['ner_eval']['plan_id']}`", ""]
    L += ["## Stage checks", "", "| stage | check | result | detail |", "|---|---|---|---|"]
    for c in r["checks"]:
        L.append(f"| {c['stage']} | {c['id']} | {'pass' if c['pass'] else '**FAIL**'} | {c['detail']} |")
    L += ["", "## Support matrix", "", "| profile | status | pass | fail | unmeasured | note |", "|---|---|---|---|---|---|"]
    for p in r["support"]:
        c = p["gate_counts"]
        L.append(f"| {p['profile']} | **{p['status']}** | {c['pass']} | {c['fail']} | {c['unmeasured']} | {'; '.join(p['reasons'])} |")
    for p in matrix["profiles"]:
        L += ["", f"### {p['profile']} gates", "", "| gate | requirement | value | result | 95% interval | note |", "|---|---|---|---|---|---|"]
        for g in p["gates"]:
            note = "; ".join(x for x in ([f"n={g['cases']}" + (" low n" if g.get("low_n") else "")] if "cases" in g else []) + ([g["value_source"]] if g.get("value_source") else []) + ([g["caveat"]] if g.get("caveat") else []))
            iv = f"[{g['interval'][0]:.3f}, {g['interval'][1]:.3f}] {g['interval_clarity']}" if g.get("interval") else ""
            v = "n/a" if g["value"] is None else (f"{g['value']:.4g}" if isinstance(g["value"], float) else g["value"])
            L.append(f"| {g['gate']} | {g['op']} {g['threshold']} | {v} | {g['result']} | {iv} | {note} |")
    L += ["", "## Like-for-like vs Alpha CRF (product corpora, strict)", "", "| population | slice | metric | Alpha | Beta 1 | delta | n | ok |", "|---|---|---|---|---|---|---|---|"]
    for x in r["regression_vs_alpha"]:
        f = lambda v: "n/a" if v is None else f"{v:.3f}"
        L.append(f"| {x['population']} | {x['slice']} | {x['metric']} | {f(x['alpha'])} | {f(x['beta1'])} | {'n/a' if x['delta'] is None else format(x['delta'], '+.3f')} | {x['cases']} | {x['ok']} |")
    cal = r["calibration"]
    L += ["", "## Calibration (Beta 1 snapshot)", "", f"n={cal['n']}, accuracy {cal['accuracy']:.3f}, mean confidence {cal['mean_confidence']:.3f}, over-confidence {cal['confidence_minus_accuracy']:.3f}, ECE {cal['ece_equal_mass']:.3f}, Brier {cal['brier']:.3f}, AUROC {cal['auroc']:.3f}."]
    pf = r["performance"]
    L += ["", "## Performance and size (Beta 1 snapshot workload, 1 thread, median of 5 repeats)", "", "| | native (in-process) | shim (external process) |", "|---|---|---|",
          f"| latency p95 (batch 1) ms | {pf['native']['latency_p95_ms']:.4f} | {pf['shim']['latency_p95_ms']:.4f} |",
          f"| throughput (largest batch) cases/s | {pf['native']['throughput_docs_per_s']:.0f} | {pf['shim']['throughput_docs_per_s']:.0f} |",
          f"| startup ms | {pf['native']['startup_ms']:.2f} | {pf['shim']['startup_ms']:.2f} |",
          f"| peak RSS MiB ({pf['native']['memory_scope']} / {pf['shim']['memory_scope']}) | {pf['native']['peak_memory_mb']:.2f} | {pf['shim']['peak_memory_mb']:.2f} |",
          f"| model bytes | {pf['native']['model_size_bytes']} | {pf['shim']['model_size_bytes']} |",
          f"| binary bytes | {pf['native']['binary_size_bytes']} (evaluator host) | {pf['shim']['binary_size_bytes']} (shim) |",
          f"| WASM bytes | {r['values']['wasm_size_bytes']} (candidate-reported) | |",
          f"| throughput repeat spread max/min | {pf['native']['throughput_spread_max_over_min']:.3f} | {pf['shim']['throughput_spread_max_over_min']:.3f} |", "", pf["alpha_shim_note"]]
    L += ["", "## References (Beta 1 snapshot, strict)", "", "| model | P | R | F1 | EN F1 | KO F1 | Beta 1 F1 minus this |", "|---|---|---|---|---|---|---|"]
    g = lambda v: "n/a" if v is None else f"{v:.3f}"
    for x in r["references"]:
        L.append(f"| {x['model']} | {g(x['strict_precision'])} | {g(x['strict_recall'])} | {g(x['strict_f1'])} | {g(x['en_f1'])} | {g(x['ko_f1'])} | {g(x['beta1_f1_minus_this'])} |")
    L += ["", "References are monolingual (spaCy/dslim English, KoELECTRA Korean); off-language slices measure a monolingual model, not a defect. Controls are calibration points.", "",
          "## Slice watchlist (Beta 1 snapshot, strict precision or F1 below 0.6)", ""]
    L += [f"- `{w['slice']}` ({w['cases']} cases{', low n' if w['low_n'] else ''}): P {g(w['strict_precision'])}, R {g(w['strict_recall'])}, F1 {g(w['strict_f1'])}" for w in r["slice_watchlist"]] or ["- none"]
    cs = r["candidate_specific_diagnostic"]
    if cs:
        L += ["", f"Candidate-specific diagnostic corpus ({cs['cases']} cases, my variants of the Alpha failure classes): strict P {cs['strict']['precision']:.3f} / R {cs['strict']['recall']:.3f} / F1 {cs['strict']['f1']:.3f}, {cs['non_exact']} non-exact outcomes. Diagnostic only; never a gate."]
    L += ["", "## Evidence exposure", "", r["evidence_exposure"]["statement"], ""]
    L += [f"- `{k}`: selection_exposed={v['selection_exposed']}, holdout={v['is_holdout']}" for k, v in r["evidence_exposure"]["populations"].items()]
    L += ["", "## Case-level changes vs Alpha CRF (product corpora; ids and categories only)", ""]
    for pop, v in r["case_level_vs_alpha"].items():
        L.append(f"- `{pop}`: failing cases {v['alpha_failing_cases']} -> {v['beta1_failing_cases']}")
        L.append("  - new failures: " + (", ".join(f"{x['case_id']} ({x['category']}, {x['language']}, {'/'.join(x['outcomes'])})" for x in v["new_failures"]) or "none"))
        L.append("  - fixed: " + (", ".join(f"{x['case_id']} ({x['category']}, {x['language']})" for x in v["fixed"]) or "none"))
        L.append("  - failing differently: " + (", ".join(f"{x['case_id']} ({'/'.join(x['alpha_outcomes'])} -> {'/'.join(x['outcomes'])})" for x in v["changed_outcome"]) or "none"))
        L.append(f"  - still failing: {len(v['unchanged_failing'])}")
    if r["rule_feedback"]:
        L += ["", "## Rule feedback (does not change the outcome)", ""] + [f"- {x}" for x in r["rule_feedback"]]
    if r["outcome"] == "A":
        L += ["", "## Required before re-measurement (blocking)", ""]
        for c in r["checks"]:
            if c["hard"] and not c["pass"]:
                L.append(f"- **{c['id']}**: {c['detail']}")
        L += ["", "Re-measurement request: fix the candidate (FastNER repository), publish a new pinned candidate, have ner-eval re-run the same plan, then requalify with the same rules. No candidate code is changed here.", ""]
    title = "Beta 2 planning (from measured deficits; nothing scheduled)" if r["outcome"] != "A" else "Other measured deficits (not blocking; informational until Beta 1 is accepted, then Beta 2 planning)"
    L += ["", f"## {title}", ""]
    for s in r["beta2_planning"]["measured_deficits"]:
        L.append(f"{s['priority']}. **{s['title']}** (shortfall {s['relative_shortfall']:.1%}): " + "; ".join(f"{e['profile']} {e['gate']} = {e['value']:.4g} vs {e['op']} {e['threshold']}" + (f" (n={e['cases']})" if "cases" in e else "") for e in s["evidence"]))
        if s.get("caveat"):
            L.append(f"   - caveat: {s['caveat']}")
    if r["beta2_planning"]["measurement_gaps"]:
        L += ["", "Measurement gaps: " + ", ".join(f"{x['profile']}:{x['gate']}" for x in r["beta2_planning"]["measurement_gaps"])]
    L += ["", "Inputs that are not deficits and not scheduled:"] + [f"- {x}" for x in r["beta2_planning"]["inputs_not_scheduled"]]
    if r["provisional_blockers"]:
        L += ["", "Provisional blockers: " + " | ".join(r["provisional_blockers"])]
    return "\n".join(L) + "\n"


def generate(root=ROOT):
    cfg, acc, policy, gates, reg = load_cfg(), load_json(ACC_PATH), load_policy(), load_gates(), load_populations()
    refs = load_json(ROOT / "policy" / "promotion-adr-refs.json")["refs"]
    art = load_artifacts()
    r = evaluate(cfg, acc, policy, gates, reg, art, refs)
    matrix = r.pop("_support_matrix")
    return canonical_json(r), render(r, matrix), canonical_json(matrix), r, matrix


def main(argv):
    ap = argparse.ArgumentParser(prog="fnbench beta1")
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args(argv)
    js, md, mjs, r, matrix = generate()
    from .support import render_markdown as render_matrix
    mmd = render_matrix({**matrix, "selected_architecture": matrix["candidate"]})
    files = {"qualification.json": js, "qualification.md": md, "support-matrix.json": mjs, "support-matrix.md": mmd}
    if a.check:
        bad = [k for k, v in files.items() if not (OUT / k).exists() or (OUT / k).read_text(encoding="utf-8") != v]
        print("beta1 outputs up to date" if not bad else f"beta1 outputs stale: {bad}")
        return 1 if bad else 0
    for k, v in files.items():
        write_text(OUT / k, v)
    print(f"Outcome {r['outcome']}: {r['outcome_label']}")
    print(r["outcome_reason"])
    return 0


def verify_pins(argv=None):
    """Re-verify the committed Beta 1 pins against the sibling fastner / ner-evidence / ner-eval checkouts (skipped when absent)."""
    import subprocess
    from pathlib import Path
    cfg = load_cfg()
    f, ev, ne = ROOT.parent / "fastner", ROOT.parent / "ner-evidence", ROOT.parent / "ner-eval"
    if not (f.exists() and ev.exists() and ne.exists()):
        print("beta1 pin verification skipped: sibling checkouts not available")
        return 0

    def git(repo, *a):
        return subprocess.run(["git", "-C", str(repo), *a], capture_output=True, text=True, check=True).stdout.strip()

    c, errs = cfg["candidate"], []
    tag = c["runtime"]["git_tag"]
    if git(f, "rev-parse", f"{tag}^{{commit}}") != c["runtime"]["commit"]:
        errs.append("tag does not point at the pinned commit")
    if git(f, "rev-parse", f"{c['runtime']['commit']}:crates/fastner") != c["runtime"]["crate_tree"]:
        errs.append("crate tree hash differs")
    if subprocess.run(["git", "-C", str(f), "merge-base", "--is-ancestor", c["runtime"]["commit"], "origin/main"]).returncode != 0:
        errs.append("pinned commit is not on fastner main")
    h = json.loads(git(f, "show", f"{tag}:docs/beta1/handoff.json"))
    for x in c["model"]["files"]:
        hh = h["candidates"][x["lang"]]
        if (hh["file_sha256"], hh["model_identity"], hh["bytes"]) != (x["sha256"], x["model_identity"], x["bytes"]):
            errs.append(f"{x['name']}: hand-off digest differs")
    if h["candidate_dir"]["dirdigest"] != c["model"]["dir_digest"]:
        errs.append("candidate directory digest differs from the hand-off")
    idx = json.loads((ev / "snapshots" / "index.json").read_text())["snapshots"]
    if not any("sha256:" + s["content_digest"] == cfg["evidence"]["content_digest"] and s["snapshot_id"] == cfg["evidence"]["snapshot_id"] for s in idx):
        errs.append("snapshot digest is not in ner-evidence's index")
    pm = json.loads((ne / cfg["source"]["ner_eval_path"] / "plan-manifest.json").read_text())
    if pm["digest"] != cfg["source"]["plan_manifest_digest"]:
        errs.append("ner-eval plan manifest digest differs")
    print("beta1 pins verified against fastner, ner-evidence and ner-eval" if not errs else "beta1 pin verification FAILED: " + "; ".join(errs))
    return 1 if errs else 0
