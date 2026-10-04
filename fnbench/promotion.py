"""Architecture promotion rule (issue #6). Evaluates a generated bakeoff report."""
import argparse

from .pins import load_candidates
from .policy import dimension_map, load_policy
from .report import build_report
from .artifacts import load_bakeoff
from .populations import load_populations
from .util import ROOT, canonical_json, load_json, write_text

RULE_PATH = ROOT / "policy" / "promotion-rule.json"
FORBIDDEN_CRITERIA = {"f1_only", "size_only"}


class RuleError(ValueError):
    pass


def load_rule(path=RULE_PATH):
    rule = load_json(path)
    validate_rule(rule, load_policy())
    return rule


def validate_rule(rule, policy):
    errs = []
    dmap = dimension_map(policy)
    g = rule["guardrails"]
    # The rule must cover quality, language, ambiguity AND size: no single-axis selection.
    for need in ("quality_floor", "language_floor", "ambiguity_floor", "size_ceiling"):
        if need not in g:
            errs.append(f"missing guardrail {need}")
    if not {"en_f1", "ko_f1"} <= set(g.get("language_floor", {}).get("dimensions", [])):
        errs.append("language_floor must cover en_f1 and ko_f1")
    if not {"runtime_binary_size_bytes", "wasm_size_bytes"} <= set(g.get("size_ceiling", {}).get("dimensions", [])):
        errs.append("size_ceiling must cover binary and WASM size")
    for name, spec in g.items():
        for d in spec["dimensions"]:
            if d not in dmap:
                errs.append(f"{name}: unknown dimension {d}")
        if not (spec.get("max_gap_to_best", 0) >= 0) or spec.get("max_ratio_to_smallest", 1) < 1:
            errs.append(f"{name}: bad threshold")
    if rule["policy_version"] != policy["policy_version"]:
        errs.append("rule policy_version differs from qualification policy version")
    if "weight" in str(rule).lower():
        errs.append("weights are not allowed")
    if errs:
        raise RuleError("; ".join(errs))
    return True


def _complete(values, dim_ids):
    return all(values.get(d) is not None for d in dim_ids)


def evaluate(rule, policy, report, waivers=None, adr_refs=None):
    waivers = waivers or []
    adr_refs = adr_refs or {}
    dmap = dimension_map(policy)
    cands = [p["id"] for p in report["pins"] if p["role"] == "candidate"]
    resolved = {p["id"] for p in report["pins"] if p["pin_status"] == "resolved"}
    all_dims = [d["id"] for d in policy["dimensions"]]
    vals = report["values"]
    measured_pops = {p["id"] for p in report["populations"] if p["artifact_runs"]}
    out = {"schema": "fastner-benchmarks.promotion-decision/1", "bakeoff_id": report["bakeoff_id"],
           "rule_version": rule["rule_version"], "policy_version": policy["policy_version"],
           "candidates": {}, "frontier": report["pareto"]["frontier"]}

    missing_pops = [p for p in rule["requires"]["quality_populations_measured"] if p not in measured_pops]
    complete = [c for c in cands if c in resolved and _complete(vals[c], all_dims)]
    for c in cands:
        why = []
        if c not in resolved:
            why.append("pin unresolved")
        if not _complete(vals[c], all_dims):
            why.append("missing dimensions: " + ", ".join(d for d in all_dims if vals[c].get(d) is None))
        out["candidates"][c] = {"evidence": "complete" if not why else "insufficient", "evidence_gaps": why,
                                "on_frontier": c in report["pareto"]["frontier"], "guardrails": {}, "eligible": False}
    if missing_pops or not complete:
        out.update(decision="no-decision-insufficient-evidence", selected=None, eligible=[],
                   reason=("populations not measured: " + ", ".join(missing_pops) if missing_pops else "no candidate has a resolved pin and a complete measurement vector"))
        return _finish(out, rule, adr_refs)

    best = {}
    for d in all_dims:
        xs = [vals[c][d] for c in complete]
        best[d] = max(xs) if dmap[d]["direction"] == "max" else min(xs)
    wv = {(w["candidate"], w["guardrail"]): w for w in waivers if w.get("reason") and w.get("adr_ref")}
    g = rule["guardrails"]
    for c in complete:
        res, ok = {}, c in report["pareto"]["frontier"]
        for gname, spec in g.items():
            fails = []
            for d in spec["dimensions"]:
                v = vals[c][d]
                if "max_gap_to_best" in spec:
                    if best[d] - v > spec["max_gap_to_best"] + 1e-12:
                        fails.append(f"{d}={v} is {best[d]-v:.4f} below best {best[d]} (max {spec['max_gap_to_best']})")
                else:
                    if v > best[d] * spec["max_ratio_to_smallest"]:
                        fails.append(f"{d}={v} is {v/best[d]:.2f}x smallest {best[d]} (max {spec['max_ratio_to_smallest']}x)")
            waived = bool(fails) and (c, gname) in wv
            res[gname] = {"pass": not fails, "waived": waived, "failures": fails}
            if fails and not waived:
                ok = False
        out["candidates"][c]["guardrails"] = res
        out["candidates"][c]["eligible"] = ok
    elig = sorted(c for c in complete if out["candidates"][c]["eligible"])
    out["eligible"] = elig
    if not elig:
        out.update(decision="no-eligible-candidate", selected=None,
                   reason="every candidate is dominated or fails a guardrail; improve candidates, do not relax guardrails to fit")
    elif len(elig) == 1:
        out.update(decision="recommend", selected=elig[0], reason="single frontier candidate passing all guardrails")
    else:
        sel, why = _tie(rule["tie_handling"], dmap, vals, elig)
        out.update(decision="recommend" if sel else "needs-adr-decision", selected=sel, reason=why)
    return _finish(out, rule, adr_refs)


def _tie(t, dmap, vals, elig):
    tol, ratio = t["quality_tolerance"], t["size_tolerance_ratio"]
    q, s = t["quality_dimensions"], t["size_dimensions"]

    def q_eq(a, b):
        return all(abs(vals[a][d] - vals[b][d]) <= tol for d in q)

    def s_eq(a, b):
        return all(max(vals[a][d], vals[b][d]) <= ratio * min(vals[a][d], vals[b][d]) for d in s)

    pairs = [(a, b) for i, a in enumerate(elig) for b in elig[i + 1:]]
    if all(q_eq(a, b) for a, b in pairs):
        best = [c for c in elig if all(vals[c][d] <= vals[o][d] for o in elig for d in s)]
        if len(best) == 1:
            return best[0], "quality-equivalent within tolerance; chose the candidate no larger on every size dimension"
    if all(s_eq(a, b) for a, b in pairs):
        best = [c for c in elig if all(vals[c][d] >= vals[o][d] for o in elig for d in q)]
        if len(best) == 1:
            return best[0], "size-equivalent within tolerance; chose the candidate no worse on every quality dimension"
    return None, "eligible candidates trade quality against size; an explicit ADR tradeoff decision is required (" + ", ".join(elig) + ")"


def _finish(out, rule, adr_refs):
    ref = adr_refs.get(out["bakeoff_id"])
    out["adr_ref"] = ref
    if out["decision"] == "recommend":
        out["promotion_state"] = "promoted" if ref else "recommended-awaiting-adr"
    else:
        out["promotion_state"] = "not-promoted"
    return out


def render_adr_handoff(rule, policy, report, decision):
    d = decision
    L = [f"# ADR handoff to `fastner`: architecture selection ({d['bakeoff_id']})", "",
         "> Generated by `python -m fnbench promotion`. Do not edit.", "",
         f"Target repo: `{rule['adr_handoff']['target_repo']}`. Policy {policy['policy_version']}, promotion rule {rule['rule_version']}.", "",
         "## Decision", "",
         f"- Outcome: **{d['decision']}**", f"- Selected: {d.get('selected') or 'none'}",
         f"- Promotion state: **{d['promotion_state']}** (promotion is effective only once a fastner ADR is recorded in `policy/promotion-adr-refs.json`)",
         f"- Reason: {d['reason']}", "",
         "## Evidence", "",
         f"- Metric protocol: {', '.join(report['metric_protocol_versions']) or 'none'}; evaluator: {', '.join(report['evaluator_versions']) or 'none'}",
         f"- Accepted artifacts: quality {len(report['accepted_artifacts']['quality'])}, perf {len(report['accepted_artifacts']['perf'])}",
         f"- Performance environment: {', '.join(report['performance_environments']) or 'none'}",
         "- Full report: `reports/bakeoff/" + d["bakeoff_id"] + "/report.md`", "",
         "## Frontier", "", f"- {', '.join(d['frontier']) or 'empty'}", "", "## Guardrails", ""]
    for c, v in sorted(d["candidates"].items()):
        if v["evidence"] != "complete":
            L.append(f"- {c}: evidence insufficient ({'; '.join(v['evidence_gaps'])})")
            continue
        fails = [f"{g}: " + "; ".join(r["failures"]) + (" [waived]" if r["waived"] else "") for g, r in v["guardrails"].items() if r["failures"]]
        L.append(f"- {c}: frontier={v['on_frontier']} eligible={v['eligible']}" + (f"; failures: {' | '.join(fails)}" if fails else ""))
    L += ["", "## Waivers", "", "- none recorded", "", "## Tradeoffs", "",
          "- " + d["reason"], "", "## Known deficits", ""]
    L += [f"- {x}" for x in report["known_limitations"]] or ["- none"]
    L += ["", "## Requested actions for fastner", ""]
    if d["decision"] == "recommend":
        L += ["1. Record an ADR adopting the selected architecture, citing this handoff and the report digest.",
              "2. Reply with the ADR reference so it can be added to `policy/promotion-adr-refs.json`."]
    else:
        L += ["1. **Do not adopt an architecture yet.** No promotable candidate exists.",
              "2. Deliver resolvable candidate artifacts (runtime commit, model digest, adapter) so ner-eval can measure them."]
    return "\n".join(L) + "\n"


def generate(root=ROOT):
    policy, cfg, reg, rule = load_policy(), load_candidates(), load_populations(), load_rule()
    q, p = load_bakeoff(cfg["bakeoff_id"])
    rep = build_report(policy, cfg, reg, q, p, root)
    waivers = load_json(ROOT / rule["waivers"]["file"])["waivers"]
    refs = load_json(ROOT / rule["requires"]["adr_ref_recorded_in"])["refs"]
    dec = evaluate(rule, policy, rep, waivers, refs)
    return canonical_json(dec), render_adr_handoff(rule, policy, rep, dec), cfg["bakeoff_id"]


def main(argv):
    ap = argparse.ArgumentParser(prog="fnbench promotion")
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args(argv)
    js, md, bid = generate()
    out = ROOT / "reports" / "promotion"
    if a.check:
        ok = (out / f"{bid}.decision.json").read_text() == js and (out / f"{bid}.adr-handoff.md").read_text() == md
        print("promotion outputs up to date" if ok else "promotion outputs stale: run `python -m fnbench promotion`")
        return 0 if ok else 1
    write_text(out / f"{bid}.decision.json", js)
    write_text(out / f"{bid}.adr-handoff.md", md)
    print(f"wrote {out}")
    return 0
