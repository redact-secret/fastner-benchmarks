"""Support matrix generation (issue #8). Status is derived, never typed."""
import argparse
import operator

from .artifacts import load_bakeoff
from .pins import load_candidates
from .policy import load_policy
from .populations import load_populations
from .promotion import evaluate, load_rule
from .report import build_report
from .util import ROOT, canonical_json, load_json, write_text

GATES_PATH = ROOT / "policy" / "support-gates.json"
OPS = {">=": operator.ge, "<=": operator.le}


class GateError(ValueError):
    pass


def load_gates(path=GATES_PATH):
    g = load_json(path)
    validate_gates(g, load_policy())
    return g


def validate_gates(g, policy):
    errs = []
    dims = {d["id"] for d in policy["dimensions"]}
    if g["policy_version"] != policy["policy_version"]:
        errs.append("gate set policy_version differs from qualification policy")
    if g["statuses"] != ["unsupported", "experimental", "provisional", "stable"]:
        errs.append("status vocabulary changed")
    for p in g["profiles"]:
        ids = set()
        for gate in p["gates"]:
            if gate["id"] in ids:
                errs.append(f"{p['id']}: duplicate gate {gate['id']}")
            ids.add(gate["id"])
            if gate["op"] not in OPS or not isinstance(gate["threshold"], (int, float)):
                errs.append(f"{p['id']}/{gate['id']}: bad op/threshold")
            src = gate["source"]
            if "dimension" in src and src["dimension"] not in dims:
                errs.append(f"{p['id']}/{gate['id']}: unknown dimension")
            if "dimension" not in src and not {"population", "metric"} <= set(src):
                errs.append(f"{p['id']}/{gate['id']}: gate needs a dimension or population+metric")
        if not any("regression" in x["id"] for x in p["gates"]) or not any("adversarial" in x["id"] for x in p["gates"]):
            errs.append(f"{p['id']}: needs regression and adversarial gates")
        if not any(x["id"].startswith("budget.wasm") for x in p["gates"]):
            errs.append(f"{p['id']}: needs a WASM budget gate")
    if g["ratification"] is not None and not (g["ratification"].get("baseline_run_ids") and g["ratification"].get("by")):
        errs.append("ratification needs baseline_run_ids and by")
    if errs:
        raise GateError("; ".join(errs))
    return True


def _value(gate, model, report):
    src = gate["source"]
    if "dimension" in src:
        return report["values"][model].get(src["dimension"])
    for row in report["population_quality"].get(src["population"], []):
        if row["model"] == model and row["state"] == "ok":
            block = row["overall"] if src.get("slice") is None else row["slices"].get(src["slice"])
            return None if block is None else block.get(src["metric"])
    return None


def evaluate_support(gates, report, decision, policy_version):
    sel = decision.get("selected")
    pin = next((p for p in report["pins"] if p["id"] == sel), None) if sel else None
    ratified = gates["ratification"] is not None
    promoted = decision.get("promotion_state") == "promoted"
    matrix = {"schema": "fastner-benchmarks.support-matrix/1", "policy_version": policy_version,
              "gate_set_version": gates["gate_set_version"], "thresholds_status": gates["thresholds_status"],
              "bakeoff_id": report["bakeoff_id"], "selected_architecture": sel,
              "selected_pin": None if pin is None else {k: pin[k] for k in ("id", "pin_status", "version", "artifact_digest", "config_hash")},
              "promotion_state": decision.get("promotion_state"), "profiles": []}
    for prof in gates["profiles"]:
        results, reasons = [], []
        measured_any = False
        for gate in prof["gates"]:
            v = _value(gate, sel, report) if sel else None
            if v is not None:
                measured_any = True
            res = "unmeasured" if v is None else ("pass" if OPS[gate["op"]](v, gate["threshold"]) else "fail")
            results.append({"gate": gate["id"], "op": gate["op"], "threshold": gate["threshold"], "value": v, "result": res})
        counts = {r: sum(x["result"] == r for x in results) for r in ("pass", "fail", "unmeasured")}
        if not sel:
            status = "unsupported"
            reasons.append(f"no selected architecture ({decision.get('decision')}): nothing measured or qualified for this profile")
        elif not measured_any:
            status, reasons = "unsupported", ["selected architecture has no measurements for this profile"]
        else:
            status = "experimental"
            if counts["fail"]:
                reasons.append(f"{counts['fail']} gate(s) failing")
            if counts["unmeasured"]:
                reasons.append(f"{counts['unmeasured']} gate(s) unmeasured")
            if not promoted:
                reasons.append(f"architecture not promoted (state: {decision.get('promotion_state')}); promotion needs an accepted fastner ADR on fastner main")
            if not ratified:
                reasons.append("gate thresholds are unratified proposals (no baseline ratification)")
            if not (counts["fail"] or counts["unmeasured"]) and promoted and ratified:
                status = "provisional"  # `stable` is never generated until its evidence model exists
        matrix["profiles"].append({"profile": prof["id"], "status": status, "reasons": reasons,
                                   "gate_counts": counts, "gates": results,
                                   "required_populations": prof["required_populations"]})
    return matrix


def render_markdown(m):
    L = ["# FastNER support matrix", "",
         "> Generated by `python -m fnbench support`. Do not edit; status comes from gates + artifacts.", "",
         f"- Qualification policy {m['policy_version']}, gate set {m['gate_set_version']} (`{m['thresholds_status']}`)",
         f"- Selected architecture: {m['selected_architecture'] or 'none'}; promotion state: {m['promotion_state']}",
         "- `stable` is not reachable at Alpha.", "",
         "| profile | status | pass | fail | unmeasured | why |", "|---|---|---|---|---|---|"]
    for p in m["profiles"]:
        c = p["gate_counts"]
        L.append(f"| {p['profile']} | **{p['status']}** | {c['pass']} | {c['fail']} | {c['unmeasured']} | {'; '.join(p['reasons']) or '-'} |")
    for p in m["profiles"]:
        L += ["", f"## {p['profile']} gates", "", "| gate | requirement | value | result |", "|---|---|---|---|"]
        for g in p["gates"]:
            L.append(f"| {g['gate']} | {g['op']} {g['threshold']} | {'n/a' if g['value'] is None else g['value']} | {g['result']} |")
    return "\n".join(L) + "\n"


def generate():
    policy, cfg, reg, rule, gates = load_policy(), load_candidates(), load_populations(), load_rule(), load_gates()
    q, p = load_bakeoff(cfg["bakeoff_id"])
    rep = build_report(policy, cfg, reg, q, p)
    waivers = load_json(ROOT / rule["waivers"]["file"])["waivers"]
    refs = load_json(ROOT / rule["requires"]["adr_ref_recorded_in"])["refs"]
    dec = evaluate(rule, policy, rep, waivers, refs)
    m = evaluate_support(gates, rep, dec, policy["policy_version"])
    return canonical_json(m), render_markdown(m)


def main(argv):
    ap = argparse.ArgumentParser(prog="fnbench support")
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args(argv)
    js, md = generate()
    out = ROOT / "reports" / "support"
    if a.check:
        ok = (out / "support-matrix.json").read_text() == js and (out / "support-matrix.md").read_text() == md
        print("support matrix up to date" if ok else "support matrix stale: run `python -m fnbench support`")
        return 0 if ok else 1
    write_text(out / "support-matrix.json", js)
    write_text(out / "support-matrix.md", md)
    print(f"wrote {out}")
    return 0
