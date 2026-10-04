import copy
import unittest

from fnbench import report as R
from fnbench import support as S
from fnbench.promotion import evaluate, load_rule
from fnbench.util import ROOT, canonical_json
from tests import helpers as H

GATES = S.load_gates()
RULE = load_rule()


def full_world(good=True, ko_bad=False, wasm=3000):
    pol, cfg, reg, qs, ps = H.world()
    # candidate C is the one the rule picks in the synthetic world
    qs = [q for q in qs]
    m = "fastner-c-compact-neural"
    for corpus in ("fastner-regression", "fastner-adversarial"):
        a = H.quality(m, 1.0 if good else 0.5, corpus=corpus, run=corpus)
        a["metrics"]["slices"]["language=ko"] = H.block(0.92, 0.92)
        qs.append(a)
    for q in qs:  # make the chosen candidate comfortably inside the proposed gates
        if q["model"]["id"] == m and q["status"] == "ok" and q["corpus"]["id"] == "ner-evidence-public":
            q["metrics"]["slices"]["difficulty=ambiguous"] = H.block(0.92, 0.8)
    for pf in ps:
        if pf["model"]["id"] == m:
            for c in pf["cells"]:
                if c["batch_size"] == 1 and c["threads"] == 1:
                    c["per_case_p95_us"] = 4000
    if ko_bad:
        for q in qs:
            if q["model"]["id"] == m and q["status"] == "ok":
                q["metrics"]["slices"]["language=ko"] = H.block(0.4, 0.4)
    return pol, cfg, reg, qs, ps


ADR = {"alpha1-full": {"decision": "fastner-c-compact-neural", "status": "accepted", "on_main": True, "adr": "x.md", "pr": "x#1"}}


def matrix(world, ratified=False, refs=None, gates=None):
    pol, cfg, reg, qs, ps = world
    rep = R.build_report(pol, cfg, reg, qs, ps)
    dec = evaluate(RULE, pol, rep, [], refs or {})
    g = copy.deepcopy(gates or GATES)
    if ratified:
        g["ratification"] = {"baseline_run_ids": ["x"], "by": "test"}
    return S.evaluate_support(g, rep, dec, pol["policy_version"]), dec


def status(m, prof):
    return next(p for p in m["profiles"] if p["profile"] == prof)


class SupportTests(unittest.TestCase):
    def test_gates_valid(self):
        self.assertEqual({p["id"] for p in GATES["profiles"]}, {"PERSON/en", "PERSON/ko"})
        self.assertFalse(GATES["stable_enabled"])
        self.assertIsNone(GATES["ratification"])

    def test_no_evidence_is_unsupported_not_failed(self):
        m, _ = matrix(H.world()[:3] + ([], []))
        for p in m["profiles"]:
            self.assertEqual(p["status"], "unsupported")
            self.assertEqual(p["gate_counts"]["unmeasured"], len(p["gates"]))
            self.assertTrue(all(g["value"] is None for g in p["gates"]))

    def test_intention_to_ship_does_not_raise_status(self):
        # even with everything passing, unratified + unpromoted => experimental at most
        m, dec = matrix(full_world())
        self.assertEqual(dec["selected"], "fastner-c-compact-neural")
        for p in m["profiles"]:
            self.assertEqual(p["status"], "experimental")
            self.assertTrue(any("not promoted" in r for r in p["reasons"]))
            self.assertTrue(any("unratified" in r for r in p["reasons"]))

    def test_provisional_requires_adr_and_ratification(self):
        refs = ADR
        self.assertEqual(status(matrix(full_world(), ratified=True)[0], "PERSON/en")["status"], "experimental")
        self.assertEqual(status(matrix(full_world(), refs=refs)[0], "PERSON/en")["status"], "experimental")
        m, _ = matrix(full_world(), ratified=True, refs=refs)
        self.assertEqual(status(m, "PERSON/en")["status"], "provisional")
        self.assertEqual(status(m, "PERSON/ko")["status"], "provisional")
        # ADR accepted but unmerged keeps support at experimental
        pending = {"alpha1-full": {**ADR["alpha1-full"], "on_main": False}}
        m2, _ = matrix(full_world(), ratified=True, refs=pending)
        self.assertEqual(status(m2, "PERSON/en")["status"], "experimental")

    def test_failing_gate_blocks_one_language_only(self):
        refs = ADR
        w = full_world(ko_bad=True)
        # relax the promotion language guard impact by checking per-profile gate results directly
        pol, cfg, reg, qs, ps = w
        rep = R.build_report(pol, cfg, reg, qs, ps)
        sel = "fastner-c-compact-neural"
        dec = {"selected": sel, "promotion_state": "promoted", "decision": "recommend"}
        g = copy.deepcopy(GATES)
        g["ratification"] = {"baseline_run_ids": ["x"], "by": "t"}
        m = S.evaluate_support(g, rep, dec, "0.1.0")
        self.assertEqual(status(m, "PERSON/en")["status"], "provisional")
        ko = status(m, "PERSON/ko")
        self.assertEqual(ko["status"], "experimental")
        self.assertTrue(any(x["result"] == "fail" and "ko" in x["gate"] for x in ko["gates"]))

    def test_missing_wasm_measurement_blocks(self):
        pol, cfg, reg, qs, ps = full_world()
        for p in ps:
            p["sizes"]["wasm_bytes"] = None
        rep = R.build_report(pol, cfg, reg, qs, ps)
        dec = {"selected": "fastner-c-compact-neural", "promotion_state": "promoted", "decision": "recommend"}
        g = copy.deepcopy(GATES)
        g["ratification"] = {"baseline_run_ids": ["x"], "by": "t"}
        m = S.evaluate_support(g, rep, dec, "0.1.0")
        self.assertEqual(status(m, "PERSON/en")["status"], "experimental")
        self.assertTrue(any(x["gate"] == "budget.wasm_size" and x["result"] == "unmeasured" for x in status(m, "PERSON/en")["gates"]))

    def test_stable_never_generated(self):
        refs = ADR
        m, _ = matrix(full_world(), ratified=True, refs=refs)
        self.assertNotIn("stable", {p["status"] for p in m["profiles"]})
        g = copy.deepcopy(GATES)
        g["stable_enabled"] = True
        m, _ = matrix(full_world(), ratified=True, refs=refs, gates=g)
        self.assertNotIn("stable", {p["status"] for p in m["profiles"]})

    def test_deterministic(self):
        a, _ = matrix(full_world())
        b, _ = matrix(full_world())
        self.assertEqual(canonical_json(a), canonical_json(b))

    def test_gate_validation(self):
        bad = copy.deepcopy(GATES)
        bad["profiles"][0]["gates"] = [x for x in bad["profiles"][0]["gates"] if not x["id"].startswith("budget.wasm")]
        with self.assertRaises(S.GateError):
            S.validate_gates(bad, __import__("fnbench.policy", fromlist=["x"]).load_policy())
        bad = copy.deepcopy(GATES)
        bad["profiles"][0]["gates"][0]["threshold"] = None
        with self.assertRaises(S.GateError):
            S.validate_gates(bad, __import__("fnbench.policy", fromlist=["x"]).load_policy())
        bad = copy.deepcopy(GATES)
        bad["ratification"] = {"by": "x"}
        with self.assertRaises(S.GateError):
            S.validate_gates(bad, __import__("fnbench.policy", fromlist=["x"]).load_policy())

    def test_committed_matrix_current(self):
        js, md = S.generate()
        out = ROOT / "reports" / "support"
        self.assertEqual((out / "support-matrix.json").read_text(), js)
        self.assertEqual((out / "support-matrix.md").read_text(), md)


if __name__ == "__main__":
    unittest.main()
