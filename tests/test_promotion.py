import copy
import unittest

from fnbench import promotion as PR
from fnbench import report as R
from fnbench.pareto import frontier
from fnbench.policy import load_policy
from fnbench.util import ROOT
from tests import helpers as H

POL = load_policy()
RULE = PR.load_rule()
DIMS = POL["dimensions"]


def fake_report(vals, measured=True, resolved=True):
    cands = list(vals)
    front, dom, inc = frontier(vals, DIMS)
    return {"bakeoff_id": "t", "values": vals,
            "pins": [{"id": c, "role": "candidate", "pin_status": "resolved" if resolved else "unresolved"} for c in cands],
            "populations": [{"id": "ner-evidence-public", "artifact_runs": ["r"] if measured else []}],
            "pareto": {"frontier": front, "dominated": dom, "incomplete": inc}}


def vec(f1=0.9, en=None, ko=None, amb=0.85, coll=0.85, model=1000, binary=5000, wasm=3000):
    v = {d["id"]: 0.9 for d in DIMS if d["unit"] == "ratio"}
    v.update(entity_f1=f1, en_f1=en if en is not None else f1, ko_f1=ko if ko is not None else f1,
             ambiguous_name_precision=amb, collision_precision_worst=coll,
             latency_p95_ms=5, throughput_docs_per_s=1000, startup_ms=10, peak_memory_mb=50,
             model_size_bytes=model, runtime_binary_size_bytes=binary, wasm_size_bytes=wasm)
    return v


class RuleTests(unittest.TestCase):
    def test_rule_valid_and_guards_all_axes(self):
        g = RULE["guardrails"]
        self.assertEqual(set(g), {"quality_floor", "language_floor", "ambiguity_floor", "size_ceiling"})

    def test_rule_rejects_removing_size_or_language_guard(self):
        r = copy.deepcopy(RULE)
        del r["guardrails"]["size_ceiling"]
        with self.assertRaises(PR.RuleError):
            PR.validate_rule(r, POL)
        r = copy.deepcopy(RULE)
        r["guardrails"]["language_floor"]["dimensions"] = ["entity_f1"]
        with self.assertRaises(PR.RuleError):
            PR.validate_rule(r, POL)
        r = copy.deepcopy(RULE)
        r["guardrails"]["size_ceiling"]["dimensions"] = ["model_size_bytes"]
        with self.assertRaises(PR.RuleError):
            PR.validate_rule(r, POL)


class EvaluateTests(unittest.TestCase):
    def ev(self, vals, **kw):
        return PR.evaluate(RULE, POL, fake_report(vals, **kw), kw.get("waivers"), kw.get("refs"))

    def test_insufficient_evidence_means_no_decision(self):
        d = PR.evaluate(RULE, POL, fake_report({"a": {x["id"]: None for x in DIMS}}))
        self.assertEqual(d["decision"], "no-decision-insufficient-evidence")
        self.assertEqual(d["promotion_state"], "not-promoted")

    def test_unresolved_pin_blocks(self):
        d = PR.evaluate(RULE, POL, fake_report({"a": vec()}, resolved=False))
        self.assertEqual(d["decision"], "no-decision-insufficient-evidence")

    def test_unmeasured_public_population_blocks(self):
        d = PR.evaluate(RULE, POL, fake_report({"a": vec()}, measured=False))
        self.assertEqual(d["decision"], "no-decision-insufficient-evidence")

    def test_not_chosen_solely_by_smallest_size(self):
        d = self.ev({"tiny": vec(f1=0.70, model=10, binary=100, wasm=80), "big": vec(f1=0.90, model=100, binary=500, wasm=400)})
        self.assertEqual(d["selected"], "big")
        self.assertFalse(d["candidates"]["tiny"]["guardrails"]["quality_floor"]["pass"])

    def test_not_chosen_solely_by_f1_when_wasm_huge(self):
        d = self.ev({"best": vec(f1=0.95, wasm=500_000), "ok": vec(f1=0.91, wasm=3000)})
        self.assertEqual(d["selected"], "ok")
        self.assertFalse(d["candidates"]["best"]["guardrails"]["size_ceiling"]["pass"])

    def test_best_f1_with_huge_binary_alone_is_not_promoted(self):
        d = self.ev({"best": vec(f1=0.95, binary=900_000), "small": vec(f1=0.70, binary=1000)})
        self.assertEqual(d["decision"], "no-eligible-candidate")

    def test_language_regression_not_hidden_by_global_average(self):
        d = self.ev({"skewed": vec(f1=0.93, en=0.95, ko=0.60), "balanced": vec(f1=0.90, en=0.91, ko=0.89)})
        self.assertEqual(d["selected"], "balanced")
        gl = d["candidates"]["skewed"]["guardrails"]["language_floor"]
        self.assertFalse(gl["pass"])
        self.assertIn("ko_f1", gl["failures"][0])

    def test_dominated_candidate_never_selected(self):
        d = self.ev({"a": vec(f1=0.90, model=100), "b": vec(f1=0.89, model=200)})
        self.assertFalse(d["candidates"]["b"]["on_frontier"])
        self.assertEqual(d["selected"], "a")

    def test_quality_equivalent_prefers_smaller_footprint(self):
        d = self.ev({"small": vec(f1=0.900, model=100, binary=1000, wasm=800),
                     "large": vec(f1=0.905, model=900, binary=9000, wasm=7000)})
        self.assertEqual(d["decision"], "recommend")
        self.assertEqual(d["selected"], "small")

    def test_real_tradeoff_requires_adr_decision(self):
        d = self.ev({"small": vec(f1=0.90, model=100, binary=1000, wasm=800),
                     "large": vec(f1=0.93, model=900, binary=9000, wasm=7000)})
        self.assertEqual(d["decision"], "needs-adr-decision")
        self.assertIsNone(d["selected"])
        self.assertEqual(d["eligible"], ["large", "small"])

    def test_waiver_needs_reason_and_adr(self):
        vals = {"best": vec(f1=0.95, wasm=500_000), "ok": vec(f1=0.91, wasm=3000)}
        bad = [{"candidate": "best", "guardrail": "size_ceiling"}]
        self.assertEqual(PR.evaluate(RULE, POL, fake_report(vals), bad)["selected"], "ok")
        good = [{"candidate": "best", "guardrail": "size_ceiling", "reason": "WASM not shipping in v1", "adr_ref": "fastner#12"}]
        d = PR.evaluate(RULE, POL, fake_report(vals), good)
        self.assertTrue(d["candidates"]["best"]["guardrails"]["size_ceiling"]["waived"])
        self.assertIn("best", d["eligible"])

    def test_promotion_requires_accepted_matching_adr_on_main(self):
        vals = {"a": vec()}
        adr = {"decision": "a", "status": "accepted", "on_main": True, "adr": "docs/adr/1.md", "pr": "x#1"}

        def state(**over):
            return PR.evaluate(RULE, POL, fake_report(vals), [], {"t": {**adr, **over}})["promotion_state"]

        self.assertEqual(PR.evaluate(RULE, POL, fake_report(vals), [], {})["promotion_state"], "recommended-awaiting-adr")
        self.assertEqual(state(status="proposed"), "recommended-awaiting-adr")
        self.assertEqual(state(on_main=False), "adr-accepted-pending-merge")
        self.assertEqual(state(decision="other"), "adr-decision-mismatch")
        self.assertEqual(state(), "promoted")

    def test_end_to_end_with_synthetic_world(self):
        pol, cfg, reg, qs, ps = H.world()
        rep = R.build_report(pol, cfg, reg, qs, ps)
        d = PR.evaluate(RULE, pol, rep)
        self.assertEqual(d["selected"], "fastner-c-compact-neural")
        self.assertFalse(d["candidates"]["fastner-a-statistical"]["eligible"])  # smallest, but too weak
        text = PR.render_adr_handoff(RULE, pol, rep, d)
        for s in ("## Decision", "## Evidence", "## Frontier", "## Guardrails", "## Waivers", "## Tradeoffs", "## Known deficits", "## Requested actions for fastner"):
            self.assertIn(s, text)

    def test_committed_outputs_current(self):
        js, md, bid = PR.generate()
        out = ROOT / "reports" / "promotion"
        self.assertEqual((out / f"{bid}.decision.json").read_text(), js)
        self.assertEqual((out / f"{bid}.adr-handoff.md").read_text(), md)
        self.assertIn('"selected": "fastner-b-linear-crf"', js)
        self.assertIn('"promotion_state": "promoted"', js)


if __name__ == "__main__":
    unittest.main()
