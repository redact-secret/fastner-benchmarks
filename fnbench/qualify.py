"""First candidate qualification record and Beta-entry decision (issue #9)."""
import argparse
import re

from .artifacts import load_bakeoff
from .corpus import CORPORA, describe
from .pins import load_candidates
from .policy import load_policy
from .populations import load_populations
from .promotion import evaluate, load_rule
from .report import build_report
from .support import evaluate_support, load_gates
from .util import ROOT, canonical_json, load_json, write_text

PATH = ROOT / "policy" / "beta-entry.json"


def load_criteria():
    c = load_json(PATH)
    pol = load_policy()
    if c["policy_version"] != pol["policy_version"]:
        raise ValueError("beta-entry policy_version differs from qualification policy")
    return c


def _measured(report, pop, model):
    return any(r["model"] == model and r["state"] == "ok" for r in report["population_quality"].get(pop, []))


def reference_rows(report, matrix_profiles, sel):
    rows = []
    v = report["values"]
    for p in report["pins"]:
        if p["role"] != "reference":
            continue
        measured = any(v[p["id"]].get(d) is not None for d in ("entity_f1", "en_f1", "ko_f1"))
        row = {"id": p["id"], "pin_status": p["pin_status"], "availability": p["availability"],
               "state": "measured" if measured else (p["pin_status"] if p["pin_status"] != "resolved" else "not-measured"),
               "blocked_by": p["blocked_by"], "dimensions": {}}
        for d in ("entity_f1", "en_f1", "ko_f1", "ambiguous_name_precision", "unseen_name_recall", "model_size_bytes", "latency_p95_ms"):
            ref, own = v[p["id"]].get(d), v[sel].get(d) if sel else None
            row["dimensions"][d] = {"reference": ref, "selected": own, "delta": None if ref is None or own is None else round(own - ref, 6)}
        rows.append(row)
    return rows


def beta_suggestions(criteria, matrix):
    """Measured deficits only: failing gates, ranked by relative shortfall. No invented work."""
    tmpl = criteria["beta_suggestion_templates"]
    items, gaps = {}, []
    for prof in matrix["profiles"]:
        for g in prof["gates"]:
            if g["result"] == "unmeasured":
                gaps.append({"profile": prof["profile"], "gate": g["gate"]})
                continue
            if g["result"] != "fail":
                continue
            t = next((x for x in tmpl if x["match"] == g["gate"]), None)
            if t is None:
                continue
            short = abs(g["value"] - g["threshold"]) / abs(g["threshold"])
            lang_specific = bool(re.search(r"\.(en|ko)_", g["gate"]))
            key = (t["area"], prof["profile"]) if lang_specific else t["area"]  # shared deficits are listed once
            cur = items.get(key)
            ev = {"profile": prof["profile"], "gate": g["gate"], "value": g["value"], "op": g["op"], "threshold": g["threshold"], "relative_shortfall": round(short, 6)}
            if cur is None:
                items[key] = {"title": t["title"], "area": t["area"], "evidence": [ev], "relative_shortfall": round(short, 6), **({"caveat": t["caveat"]} if "caveat" in t else {})}
            else:
                cur["evidence"].append(ev)
                cur["relative_shortfall"] = max(cur["relative_shortfall"], round(short, 6))
    out = sorted(items.values(), key=lambda x: (-x["relative_shortfall"], x["area"], x["evidence"][0]["profile"]))
    for i, it in enumerate(out, 1):
        it["priority"] = i
    return out, sorted(gaps, key=lambda g: (g["profile"], g["gate"]))


def qualify(criteria, policy, cfg, pop_reg, report, decision, matrix, gates, root=ROOT):
    sel = decision.get("selected")
    pin = next((p for p in report["pins"] if p["id"] == sel), None) if sel else None
    prof_gates = [g for prof in matrix["profiles"] for g in prof["gates"]]
    budget = [g for g in prof_gates if g["gate"].startswith("budget.")]
    ref_rows = reference_rows(report, matrix["profiles"], sel)
    langs = sorted({p["language"] for p in gates["profiles"]})
    ref_langs = {e["id"]: e.get("languages", []) for e in cfg["candidates"] if e["role"] == "reference"}

    def lang_ok(lang):
        for r in ref_rows:
            if lang in ref_langs[r["id"]] and (r["state"] == "measured" or (r["pin_status"] == "unavailable")):
                return True
        return False

    status = {
        "architecture_selected": (bool(sel), decision["decision"]),
        "architecture_promoted": (decision.get("promotion_state") == "promoted", decision.get("promotion_state")),
        "candidate_pin_resolved": (bool(pin and pin["pin_status"] == "resolved"), pin["pin_status"] if pin else "no selected candidate"),
        "public_snapshot_measured": (bool(sel) and _measured(report, "ner-evidence-public", sel), "ner-evidence-public: " + ("measured" if sel and _measured(report, "ner-evidence-public", sel) else "not measured")),
        "regression_measured": (bool(sel) and _measured(report, "fastner-regression", sel), "fastner-regression: " + ("measured" if sel and _measured(report, "fastner-regression", sel) else "not measured")),
        "adversarial_measured": (bool(sel) and _measured(report, "fastner-adversarial", sel), "fastner-adversarial: " + ("measured" if sel and _measured(report, "fastner-adversarial", sel) else "not measured")),
        "budgets_measured": (bool(budget) and all(g["result"] != "unmeasured" for g in budget), f"{sum(g['result'] != 'unmeasured' for g in budget)}/{len(budget)} budget gates measured"),
        "references_accounted": (all(lang_ok(l) for l in langs), ", ".join(f"{l}={'ok' if lang_ok(l) else 'missing'}" for l in langs)),
        "gates_ratified": (gates["ratification"] is not None, gates["thresholds_status"]),
    }
    crit = []
    for c in criteria["criteria"]:
        met, detail = status[c["id"]]
        crit.append({**c, "met": bool(met), "detail": detail})
    enter = all(c["met"] for c in crit)
    suggestions, gaps = beta_suggestions(criteria, matrix)
    unmet = [c for c in crit if not c["met"]]
    return {
        "schema": "fastner-benchmarks.qualification-record/1",
        "record": "alpha1-first-candidate-qualification",
        "criteria_version": criteria["criteria_version"],
        "policy_version": policy["policy_version"],
        "outcome": "A" if enter else "B",
        "decision": criteria["outcomes"]["A" if enter else "B"],
        "decision_reason": ("every entry criterion is met" if enter else
                            "architecture/product viability is not proven: " + ", ".join(c["id"] for c in unmet)),
        "release_identity": {
            "fastner_runtime_commit": pin["runtime_commit"] if pin else None,
            "fastner_runtime_version": pin["version"] if pin else None,
            "model_artifact_digest": pin["artifact_digest"] if pin else None,
            "candidate": sel,
            "evidence_snapshots": [p["identity"] for p in pop_reg["populations"] if p["id"] == "ner-evidence-public"],
            "regression_corpus": {k: {"content_digest": describe(k, root)["content_digest"], "case_count": describe(k, root)["case_count"]} for k in CORPORA},
            "evaluator_versions": report["evaluator_versions"],
            "metric_protocol_versions": report["metric_protocol_versions"],
            "performance_environments": report["performance_environments"],
            "peer_pins": [{k: p[k] for k in ("id", "pin_status", "version", "artifact_digest")} for p in report["pins"] if p["role"] == "reference"],
        },
        "criteria": crit,
        "promotion": {"decision": decision["decision"], "state": decision["promotion_state"], "reason": decision["reason"]},
        "support": [{"profile": p["profile"], "status": p["status"]} for p in matrix["profiles"]],
        "references": ref_rows,
        "measured_deficits_beta_suggestions": suggestions,
        "measurement_gaps": gaps,
        "alpha_blockers": [] if enter else [{"priority": i, "criterion": c["id"], "title": c["title"], "owner": c["owner"], "detail": c["detail"], "next_action": c["next_action"]} for i, c in enumerate(unmet, 1)],
        "architecture_outcome": ({"candidate": sel, "state": decision["promotion_state"], "summary": f"{sel} is the only candidate on the frontier that passes every promotion guardrail" if decision["decision"] == "recommend" else decision["reason"]}),
        "beta_planning_note": (("Deficits above are derived only from measured failing gates and are the Beta backlog." if enter else
                                "Deficits above are derived only from measured failing gates, ordered by relative shortfall (a screening heuristic, not a priority judgment). They are a candidate Beta backlog; Beta is not entered until the alpha blockers are resolved.") if suggestions else
                               "No measured deficits exist, so no Beta work is generated. Resolve the alpha blockers first."),
    }


def render_markdown(r):
    ao = r["architecture_outcome"]
    L = ["# FastNER qualification record: Alpha 1 first candidate", "",
         "> Generated by `python -m fnbench qualify`. Do not edit.", "",
         f"## Architecture: `{ao['candidate'] or 'none'}`, promotion state `{ao['state']}`", "", ao["summary"] + ".", "",
         f"## Product readiness: **{r['outcome']}. {r['decision']}**", "", r["decision_reason"] + ".", "",
         f"- Criteria {r['criteria_version']}, qualification policy {r['policy_version']}",
         f"- Architecture: {r['promotion']['decision']} / promotion {r['promotion']['state']}", "",
         "## Entry criteria", "", "| criterion | met | owner | detail |", "|---|---|---|---|"]
    for c in r["criteria"]:
        L.append(f"| {c['title']} | {'yes' if c['met'] else '**no**'} | {c['owner']} | {c['detail']} |")
    ri = r["release_identity"]
    L += ["", "## Release identity", "",
          f"- Candidate: {ri['candidate'] or 'none'}; runtime version {ri['fastner_runtime_version'] or 'n/a'}; model digest {ri['model_artifact_digest'] or 'n/a'}",
          f"- Evidence snapshot: {', '.join(str(s.get('snapshot_id') or 'pending pin') for s in ri['evidence_snapshots']) or 'n/a'}",
          *[f"- {k}: {v['case_count']} cases, {v['content_digest']}" for k, v in sorted(ri["regression_corpus"].items())],
          f"- Evaluator: {', '.join(ri['evaluator_versions']) or 'none'}; protocol {', '.join(ri['metric_protocol_versions']) or 'none'}; perf env {', '.join(ri['performance_environments']) or 'none'}",
          "", "## Support state", ""]
    L += [f"- {s['profile']}: **{s['status']}**" for s in r["support"]]
    L += ["", "## External references", "", "| reference | state | note |", "|---|---|---|"]
    for x in r["references"]:
        L.append(f"| {x['id']} | {x['state']} | {x['blocked_by'] or ''} |")
    if r["measured_deficits_beta_suggestions"]:
        L += ["", "## Measured deficits (candidate Beta backlog)", ""]
        for s in r["measured_deficits_beta_suggestions"]:
            L.append(f"{s['priority']}. **{s['title']}** (worst relative shortfall {s['relative_shortfall']:.1%}): " + "; ".join(f"{e['profile']} {e['gate']} = {e['value']:.4g} vs {e['op']} {e['threshold']}" for e in s["evidence"]))
            if s.get("caveat"):
                L.append(f"   - caveat: {s['caveat']}")
    if r["measurement_gaps"]:
        L += ["", "Measurement gaps (not deficits): " + ", ".join(f"{g['profile']}:{g['gate']}" for g in r["measurement_gaps"])]
    if r["alpha_blockers"]:
        L += ["", "## Alpha blockers (prioritized)", ""]
        L += [f"{b['priority']}. `{b['criterion']}` ({b['owner']}; now: {b['detail']}). Next: {b['next_action']}" for b in r["alpha_blockers"]]
    L += ["", f"_{r['beta_planning_note']}_"]
    return "\n".join(L) + "\n"


def generate():
    policy, cfg, reg, rule, gates, crit = load_policy(), load_candidates(), load_populations(), load_rule(), load_gates(), load_criteria()
    q, p = load_bakeoff(cfg["bakeoff_id"])
    rep = build_report(policy, cfg, reg, q, p)
    waivers = load_json(ROOT / rule["waivers"]["file"])["waivers"]
    refs = load_json(ROOT / rule["requires"]["adr_ref_recorded_in"])["refs"]
    dec = evaluate(rule, policy, rep, waivers, refs)
    matrix = evaluate_support(gates, rep, dec, policy["policy_version"])
    rec = qualify(crit, policy, cfg, reg, rep, dec, matrix, gates)
    return canonical_json(rec), render_markdown(rec)


def main(argv):
    ap = argparse.ArgumentParser(prog="fnbench qualify")
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args(argv)
    js, md = generate()
    out = ROOT / "reports" / "qualification"
    if a.check:
        ok = (out / "alpha1-qualification.json").read_text() == js and (out / "alpha1-qualification.md").read_text() == md
        print("qualification record up to date" if ok else "qualification record stale: run `python -m fnbench qualify`")
        return 0 if ok else 1
    write_text(out / "alpha1-qualification.json", js)
    write_text(out / "alpha1-qualification.md", md)
    print(f"wrote {out}")
    return 0
