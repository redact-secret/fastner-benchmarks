import copy
import unittest

from fnbench import qualify as Q
from fnbench import report as R
from fnbench import support as S
from fnbench.promotion import evaluate, load_rule
from fnbench.util import ROOT, canonical_json
from tests import helpers as H
from tests.test_support import full_world

CRIT = Q.load_criteria()
GATES = S.load_gates()
RULE = load_rule()


def run(world, ratified=True, adr=True, gates_override=None):
    pol, cfg, reg, qs, ps = world
    rep = R.build_report(pol, cfg, reg, qs, ps)
    refs = {"alpha1-full": {"decision": "fastner-c-compact-neural", "status": "accepted", "on_main": True, "adr": "x.md", "pr": "x#1"}} if adr else {}
    dec = evaluate(RULE, pol, rep, [], refs)
    g = copy.deepcopy(gates_override or GATES)
    if ratified:
        g["ratification"] = {"baseline_run_ids": ["x"], "by": "t"}
    m = S.evaluate_support(g, rep, dec, pol["policy_version"])
    return Q.qualify(CRIT, pol, cfg, reg, rep, dec, m, g), m


def world_with_refs():
    """Candidate C selected; EN reference measured, KO reference measured."""
    pol, cfg, reg, qs, ps = full_world()
    qs.append(H.quality("ref-spacy-en", 0.9))
    qs.append(H.quality("ref-koelectra-ko", 0.9))
    return pol, cfg, reg, qs, ps


class QualifyTests(unittest.TestCase):
    def test_no_evidence_remains_in_alpha_with_blockers_and_no_beta_work(self):
        pol, cfg, reg, _, _ = H.world()
        rec, _ = run((pol, cfg, reg, [], []))
        self.assertEqual((rec["outcome"], rec["decision"]), ("B", "REMAIN IN ALPHA"))
        self.assertEqual(rec["measured_deficits_beta_suggestions"], [])
        self.assertTrue(rec["alpha_blockers"])
        self.assertTrue(all(b["next_action"] for b in rec["alpha_blockers"]))
        self.assertIn("No measured deficits exist", rec["beta_planning_note"])

    def test_enter_beta_when_all_criteria_met(self):
        rec, m = run(world_with_refs(), ratified=True)
        failing = [c["id"] for c in rec["criteria"] if not c["met"]]
        self.assertEqual(failing, [], failing)
        self.assertEqual(rec["decision"], "ENTER BETA")
        self.assertEqual(rec["alpha_blockers"], [])

    def test_each_missing_criterion_blocks_beta(self):
        base = world_with_refs()
        rec, _ = run(base, adr=False)
        self.assertEqual(rec["outcome"], "B")
        self.assertIn("architecture_promoted", [b["criterion"] for b in rec["alpha_blockers"]])
        rec, _ = run(base, ratified=False)
        self.assertIn("gates_ratified", [b["criterion"] for b in rec["alpha_blockers"]])
        pol, cfg, reg, qs, ps = world_with_refs()
        qs = [q for q in qs if q["corpus"]["id"] != "fastner-adversarial"]
        rec, _ = run((pol, cfg, reg, qs, ps))
        self.assertIn("adversarial_measured", [b["criterion"] for b in rec["alpha_blockers"]])
        pol, cfg, reg, qs, ps = world_with_refs()
        for p in ps:
            p["sizes"]["wasm_bytes"] = None
        rec, _ = run((pol, cfg, reg, qs, ps))
        self.assertIn("budgets_measured", [b["criterion"] for b in rec["alpha_blockers"]])

    def test_unavailable_reference_with_reason_is_accounted_unresolved_is_not(self):
        pol, cfg, reg, qs, ps = world_with_refs()
        qs = [q for q in qs if q["model"]["id"] != "ref-koelectra-ko"]
        for e in cfg["candidates"]:
            if e["id"] == "ref-koelectra-ko":
                e["pin_status"] = "unavailable"
                e["unavailable_reason"] = "model license forbids redistribution"
        rec, _ = run((pol, cfg, reg, qs, ps))
        self.assertTrue(next(c for c in rec["criteria"] if c["id"] == "references_accounted")["met"])
        for e in cfg["candidates"]:
            if e["id"] == "ref-koelectra-ko":
                e["pin_status"] = "unresolved"
                e["blocked_by"] = "not yet"
                e.pop("unavailable_reason")
        rec, _ = run((pol, cfg, reg, qs, ps))
        self.assertFalse(next(c for c in rec["criteria"] if c["id"] == "references_accounted")["met"])
        row = next(r for r in rec["references"] if r["id"] == "ref-koelectra-ko")
        self.assertNotEqual(row["state"], "measured")
        self.assertIsNone(row["dimensions"]["ko_f1"]["reference"])  # unavailable is never zero

    def test_failing_gates_become_ranked_measured_deficits_not_blockers(self):
        pol, cfg, reg, qs, ps = world_with_refs()
        for p in ps:  # all models larger than the 5 MiB proposal (relative sizes stay within the promotion ceiling)
            H.patch_perf(p, model={"fastner-a-statistical": 15_000_000, "fastner-b-linear-crf": 16_000_000,
                                   "fastner-c-compact-neural": 20_000_000}.get(p["model"]["id"], 60_000_000))
            if p["model"]["id"] == "fastner-c-compact-neural":
                H.patch_perf(p, startup=200)
        rec, m = run((pol, cfg, reg, qs, ps))
        self.assertEqual(rec["decision"], "ENTER BETA")
        self.assertTrue(all("caveat" in x for x in rec["measured_deficits_beta_suggestions"] if x["area"] == "startup"))
        areas = [s["area"] for s in rec["measured_deficits_beta_suggestions"]]
        self.assertIn("size", areas)
        self.assertIn("startup", areas)
        sh = [s["relative_shortfall"] for s in rec["measured_deficits_beta_suggestions"]]
        self.assertEqual(sh, sorted(sh, reverse=True))
        self.assertEqual([s["priority"] for s in rec["measured_deficits_beta_suggestions"]], list(range(1, len(sh) + 1)))
        # every suggestion cites a real failing gate and measured value
        for s in rec["measured_deficits_beta_suggestions"]:
            for e in s["evidence"]:
                self.assertIsNotNone(e["value"])

    def test_no_suggestion_without_measured_failure(self):
        rec, _ = run(world_with_refs())
        for s in rec["measured_deficits_beta_suggestions"]:
            self.assertTrue(s["evidence"])

    def test_language_deficit_maps_to_korean_particle_work(self):
        pol, cfg, reg, qs, ps = world_with_refs()
        for q in qs:
            if q["model"]["id"] == "fastner-c-compact-neural" and q["corpus"]["id"] == "fastner-adversarial":
                q["metrics"]["slices"]["language=ko"] = H.block(0.5, 0.9)
        rec, _ = run((pol, cfg, reg, qs, ps))
        self.assertEqual(rec["decision"], "ENTER BETA")
        self.assertTrue(any(s["area"] == "adversarial-ko" for s in rec["measured_deficits_beta_suggestions"]))

    def test_deterministic(self):
        a, _ = run(world_with_refs())
        b, _ = run(world_with_refs())
        self.assertEqual(canonical_json(a), canonical_json(b))
        self.assertEqual(Q.render_markdown(a), Q.render_markdown(b))

    def test_release_identity_carries_required_fields(self):
        rec, _ = run(world_with_refs())
        self.assertRegex(rec["release_identity"]["fastner_runtime_commit"], r"^[0-9a-f]{40}$")
        for k in ("fastner_runtime_version", "model_artifact_digest", "evidence_snapshots", "regression_corpus",
                  "evaluator_versions", "metric_protocol_versions", "performance_environments", "peer_pins"):
            self.assertIn(k, rec["release_identity"])

    def test_committed_record_current_and_remains_in_alpha(self):
        js, md = Q.generate()
        out = ROOT / "reports" / "qualification"
        self.assertEqual((out / "alpha1-qualification.json").read_text(), js)
        self.assertEqual((out / "alpha1-qualification.md").read_text(), md)
        self.assertIn("REMAIN IN ALPHA", md)
        self.assertIn("fastner-b-linear-crf", md)


if __name__ == "__main__":
    unittest.main()
