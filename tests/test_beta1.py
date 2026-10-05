import copy
import json
import unittest

from fnbench import beta1 as B
from fnbench import beta1_ingest as BI
from fnbench.policy import load_policy
from fnbench.populations import load_populations
from fnbench.support import load_gates
from fnbench.util import ROOT, load_json

CFG = BI.load_cfg()
ACC = load_json(B.ACC_PATH)
POLICY = load_policy()
GATES = load_gates()
REG = load_populations()
REFS = load_json(ROOT / "policy" / "promotion-adr-refs.json")["refs"]


def run(art=None, cfg=None, refs=None, reg=None, acc=None):
    art = art or B.load_artifacts()
    out = B.evaluate(cfg or CFG, acc or ACC, POLICY, GATES, reg or REG, art, refs or REFS)
    return out, out["_support_matrix"]


def check(rec, cid):
    return next(c for c in rec["checks"] if c["id"] == cid)


def fresh():
    return copy.deepcopy(B.load_artifacts())


class RulesFileTests(unittest.TestCase):
    def test_rules_declare_order_outcomes_and_unchanged_thresholds(self):
        self.assertTrue(ACC["declared_before_results"]["statement"])
        self.assertEqual(set(ACC["outcomes"]), {"A", "B", "C"})
        self.assertEqual(ACC["support_gates"]["thresholds"], "unchanged")
        self.assertEqual([s["id"] for s in ACC["stages"]], ["0-pins", "1-architecture", "2-quality", "3-calibration", "4-performance-size"])

    def test_clarifications_are_explicit_and_do_not_relax_regression_tolerance(self):
        self.assertTrue(all(c["after_first_evaluation"] for c in ACC["clarifications"]))
        self.assertEqual(ACC["tolerances"]["no_regression_absolute"], 0.02)
        self.assertTrue(any("NOT" in c["effect"] and "no_regression_vs_alpha" in c["effect"] for c in ACC["clarifications"]))

    def test_provisional_needs_evidence_outside_selection(self):
        self.assertTrue(any("not used for selection" in c for c in ACC["provisional_conditions"]))


class CurrentResultTests(unittest.TestCase):
    def setUp(self):
        self.rec, self.matrix = run()

    def test_outcome_follows_the_declared_rule(self):
        # Exactly one hard check fails on the real data: KO regression-corpus F1 fell by more than the declared 0.02.
        failed = [c["id"] for c in self.rec["checks"] if c["hard"] and not c["pass"]]
        self.assertEqual(failed, ["no_regression_vs_alpha"])
        self.assertEqual(self.rec["outcome"], "A")
        rows = [x for x in check(self.rec, "no_regression_vs_alpha")["evidence"] if x["ok"] is False]
        self.assertEqual([(x["population"], x["slice"]) for x in rows], [("fastner-regression", "language=ko")])
        self.assertAlmostEqual(rows[0]["delta"], -0.035573, places=5)
        self.assertEqual(rows[0]["cases"], 18)
        self.assertTrue(rows[0]["alpha_inside_beta1_interval"])
        self.assertTrue(self.rec["rule_feedback"])

    def test_all_pin_and_architecture_checks_pass(self):
        for cid in ("candidate_pin_complete", "evidence_pin_matches", "corpus_digests_match", "reference_pins_unchanged", "run_integrity",
                    "same_model_both_transports", "architecture_unchanged", "adr_chain_on_main", "no_new_dependencies", "size_growth_bounded",
                    "native_shim_parity", "improvement_vs_alpha", "calibration_measured", "budgets_evaluable", "perf_repeat_stability"):
            self.assertTrue(check(self.rec, cid)["pass"], cid)

    def test_support_is_experimental_with_expected_failing_gates(self):
        self.assertEqual({p["profile"]: p["status"] for p in self.rec["support"]}, {"PERSON/en": "experimental", "PERSON/ko": "experimental"})
        failing = {p["profile"]: {g["gate"] for g in p["gates"] if g["result"] == "fail"} for p in self.matrix["profiles"]}
        self.assertEqual(failing["PERSON/en"], {"public.en_f1", "public.ambiguous_precision", "public.collision_precision_worst", "calibration.ece"})
        self.assertEqual(failing["PERSON/ko"], {"public.ambiguous_precision", "public.collision_precision_worst", "regression.ko_f1", "calibration.ece"})

    def test_budgets_pass_but_wasm_is_marked_candidate_reported(self):
        for p in self.matrix["profiles"]:
            budgets = {g["gate"]: g for g in p["gates"] if g["gate"].startswith("budget.")}
            self.assertTrue(all(g["result"] == "pass" for g in budgets.values()))
            self.assertEqual(budgets["budget.wasm_size"]["value_source"], "candidate-reported")
        self.assertEqual(self.rec["value_sources"]["wasm_size_bytes"], "candidate-reported")

    def test_intervals_are_attached_and_straddling_is_visible(self):
        en = next(g for p in self.matrix["profiles"] for g in p["gates"] if g["gate"] == "regression.en_f1")
        self.assertEqual(en["interval_clarity"], "straddles")
        self.assertTrue(en["low_n"])

    def test_numbers_match_ner_eval_reports(self):
        v = self.rec["values"]
        self.assertAlmostEqual(v["entity_f1"], 0.8034, places=3)
        self.assertAlmostEqual(v["en_f1"], 0.7595, places=3)
        self.assertAlmostEqual(v["ambiguous_name_precision"], 0.584, places=3)
        self.assertAlmostEqual(v["calibration_ece"], 0.1503, places=3)
        self.assertEqual(v["model_size_bytes"], 590760)

    def test_exposure_is_stated_and_no_population_is_independent(self):
        pops = self.rec["evidence_exposure"]["populations"]
        self.assertTrue(all(p["selection_exposed"] for p in pops.values()))
        self.assertFalse(any(p["is_holdout"] for p in pops.values()))

    def test_case_level_diff_has_ids_and_categories_only(self):
        d = self.rec["case_level_vs_alpha"]["fastner-regression"]
        self.assertEqual({x["case_id"] for x in d["new_failures"]}, {"fnb-reg-006", "fnb-reg-046", "fnb-reg-047"})
        for rows in d.values():
            if isinstance(rows, list):
                for x in rows:
                    self.assertFalse({"text", "surface"} & set(x))

    def test_references_and_controls_are_context_not_gates(self):
        names = {r["model"] for r in self.rec["references"]}
        self.assertEqual(names, {"ref-spacy-en", "ref-bert-base-ner", "ref-koelectra-ko", "control-null", "control-capitalized-run"})
        self.assertIsNone(next(r for r in self.rec["references"] if r["model"] == "control-null")["strict_f1"])  # undefined stays None

    def test_committed_outputs_are_current(self):
        js, md, mjs, _, _ = B.generate()
        for name, text in (("qualification.json", js), ("qualification.md", md), ("support-matrix.json", mjs)):
            self.assertEqual((B.OUT / name).read_text(encoding="utf-8"), text, name)

    def test_outputs_contain_no_case_text(self):
        from fnbench.corpus import CORPORA, read_built
        blob = "".join(p.read_text(encoding="utf-8") for p in B.OUT.glob("*"))
        for cid in CORPORA:
            for r in read_built(cid):
                for e in r["entities"]:
                    self.assertNotIn(e["surface"], blob)


class PathTests(unittest.TestCase):
    def regression_fixed(self, art):
        a, b = art["alpha_q"]["fastner-regression"], art["q"][("fastner-regression", B.NATIVE)]
        for model in (B.NATIVE, B.SHIM):
            blk = art["q"][("fastner-regression", model)]["metrics"]["slices"]["language=ko"]
            blk["strict"] = copy.deepcopy(a["metrics"]["slices"]["language=ko"]["strict"])
        return art

    def test_outcome_b_when_no_hard_check_fails(self):
        rec, _ = run(self.regression_fixed(fresh()))
        self.assertEqual(rec["outcome"], "B")
        self.assertEqual(rec["beta2_planning"]["measured_deficits"][0]["priority"], 1)
        self.assertIn("support stays experimental", rec["outcome_reason"])

    def test_outcome_c_requires_every_provisional_condition(self):
        art = self.regression_fixed(fresh())
        # make every gate pass on a population that is not selection-exposed, with measured WASM and clear intervals
        gates = copy.deepcopy(GATES)
        for prof in gates["profiles"]:
            for g in prof["gates"]:
                g["threshold"] = 0 if g["op"] == ">=" else 10 ** 12
        acc = copy.deepcopy(ACC)
        acc["stages"][3]["target_gate"]["threshold"] = 1.0
        reg = copy.deepcopy(REG)
        cfg = copy.deepcopy(CFG)

        def go(reg=reg, cfg=cfg):
            out = B.evaluate(cfg, acc, POLICY, gates, reg, art, REFS)
            return out, out["_support_matrix"]

        rec, m = go()
        self.assertEqual(rec["outcome"], "B")                       # all gates pass, but everything is selection-exposed + WASM reported
        self.assertIn("outside selection", " ".join(rec["provisional_blockers"]))
        for p in reg["populations"]:
            if p["id"] in (B.FLOOR,):
                p["selection_exposed"] = False
        rec, m = go()
        self.assertEqual(rec["outcome"], "B")                       # WASM still candidate-reported
        self.assertIn("candidate-reported", " ".join(rec["provisional_blockers"]))
        # measured WASM and a clear interval remove the remaining blockers
        orig = B.candidate_values

        def measured(policy, art_, **kw):
            vals, srcs, ivs, pv, sv = orig(policy, art_, **kw)
            srcs.pop("wasm_size_bytes", None)
            return vals, srcs, {}, pv, sv
        B.candidate_values = measured
        try:
            rec, m = go()
        finally:
            B.candidate_values = orig
        self.assertEqual(rec["outcome"], "C")
        self.assertEqual({p["profile"]: p["status"] for p in rec["support"]}, {"PERSON/en": "provisional", "PERSON/ko": "provisional"})

    def test_straddling_interval_blocks_provisional(self):
        art = self.regression_fixed(fresh())
        gates = copy.deepcopy(GATES)
        for prof in gates["profiles"]:
            for g in prof["gates"]:
                g["threshold"] = 0 if g["op"] == ">=" else 10 ** 12
        # threshold inside the F1 interval of regression.en_f1 (0.837-0.984) while the point passes
        for g in gates["profiles"][0]["gates"]:
            if g["id"] == "regression.en_f1":
                g["threshold"] = 0.9
        acc = copy.deepcopy(ACC)
        acc["stages"][3]["target_gate"]["threshold"] = 1.0
        reg = copy.deepcopy(REG)
        for p in reg["populations"]:
            p["selection_exposed"] = False
        orig = B.candidate_values

        def measured(policy, art_, **kw):
            vals, srcs, ivs, pv, sv = orig(policy, art_, **kw)
            srcs.pop("wasm_size_bytes", None)
            return vals, srcs, ivs, pv, sv
        B.candidate_values = measured
        try:
            out = B.evaluate(CFG, acc, POLICY, gates, reg, art, REFS)
        finally:
            B.candidate_values = orig
        en = next(p for p in out["support"] if p["profile"] == "PERSON/en")
        self.assertEqual(en["status"], "experimental")
        self.assertTrue(any("straddles" in r for r in en["reasons"]))

    def hard_fail(self, mutate, cid, **kw):
        art = fresh()
        cfg, refs = copy.deepcopy(CFG), copy.deepcopy(REFS)
        mutate(art, cfg, refs)
        rec, _ = run(art, cfg, refs)
        self.assertFalse(check(rec, cid)["pass"], cid)
        self.assertEqual(rec["outcome"], "A")

    def test_pin_failures_force_a(self):
        def digest(art, cfg, refs):
            art["q"][(B.FLOOR, B.NATIVE)]["model"]["artifact_digest"] = "sha256:" + "0" * 64
        self.hard_fail(digest, "candidate_pin_complete")

        def tree(art, cfg, refs):
            art["q"][(B.FLOOR, B.SHIM)]["runtime"]["tree"] = "1" * 40
        self.hard_fail(tree, "candidate_pin_complete")

        def snap(art, cfg, refs):
            art["q"][(B.FLOOR, B.NATIVE)]["corpus"]["digest"] = "sha256:" + "1" * 64
        self.hard_fail(snap, "evidence_pin_matches")

        def stale(art, cfg, refs):
            art["q"][("fastner-regression", B.NATIVE)]["corpus"]["digest"] = "sha256:" + "2" * 64
        self.hard_fail(stale, "corpus_digests_match")

        def plan(art, cfg, refs):
            art["manifest"]["plan_verification"]["identical"] = False
        self.hard_fail(plan, "run_integrity")

        def refpin(art, cfg, refs):
            art["q"][(B.FLOOR, "ref-spacy-en")]["model"]["artifact_digest"] = "sha256:" + "3" * 64
        self.hard_fail(refpin, "reference_pins_unchanged")

        def short(art, cfg, refs):
            cfg["candidate"]["runtime"]["commit"] = "544484a"
        self.hard_fail(short, "candidate_pin_complete")

    def test_architecture_failures_force_a(self):
        def cls(art, cfg, refs):
            cfg["candidate"]["class"] = "C-compact-neural"
        self.hard_fail(cls, "architecture_unchanged")

        def adr(art, cfg, refs):
            refs["alpha1-full"]["on_main"] = False
        self.hard_fail(adr, "adr_chain_on_main")

        def adr34(art, cfg, refs):
            cfg["candidate"]["adrs"]["0004"]["status"] = "proposed"
        self.hard_fail(adr34, "adr_chain_on_main")

        def deps(art, cfg, refs):
            cfg["candidate"]["runtime"]["dependencies"] = 2
        self.hard_fail(deps, "no_new_dependencies")

        def wasm(art, cfg, refs):
            cfg["candidate"]["wasm_candidate_reported"]["bytes"] = 90000
        self.hard_fail(wasm, "size_growth_bounded")

        def model(art, cfg, refs):
            cfg["candidate"]["model"]["size_bytes"] = 700000
        self.hard_fail(model, "size_growth_bounded")

    def test_quality_calibration_perf_failures_force_a(self):
        def parity(art, cfg, refs):
            art["q"][("fastner-adversarial", B.SHIM)]["metrics"]["overall"]["strict"]["f1"] = 0.1
        self.hard_fail(parity, "native_shim_parity")

        def noimp(art, cfg, refs):
            for m in (B.NATIVE, B.SHIM):
                for pop in B.PRODUCT:
                    a = art["q"][(pop, m)]["metrics"]
                    for k in ("language=en", "language=ko"):
                        a["slices"][k]["strict"] = copy.deepcopy(art["alpha_q"][pop]["metrics"]["slices"][k]["strict"])
                    a["overall"]["strict"] = copy.deepcopy(art["alpha_q"][pop]["metrics"]["overall"]["strict"])
        self.hard_fail(noimp, "improvement_vs_alpha")

        def cal(art, cfg, refs):
            art["cal"][(B.FLOOR, B.SHIM)]["overall"]["ece_equal_mass"] += 0.05
        self.hard_fail(cal, "calibration_measured")

        def few(art, cfg, refs):
            for m in (B.NATIVE, B.SHIM):
                art["cal"][(B.FLOOR, m)]["overall"]["n"] = 5
        self.hard_fail(few, "calibration_measured")

        def noperf(art, cfg, refs):
            art["perf"][B.SHIM]["sizes"]["binary_bytes"] = None
        self.hard_fail(noperf, "budgets_evaluable")

        def spread(art, cfg, refs):
            for c in art["perf"][B.NATIVE]["cells"]:
                c["cases_per_sec"]["max_over_min"] = 3.0
        self.hard_fail(spread, "perf_repeat_stability")

    def test_calibration_parity_tolerates_float_rounding_only(self):
        art = fresh()
        art["cal"][(B.FLOOR, B.SHIM)]["overall"]["log_loss"] += 2e-6
        rec, _ = run(art)
        self.assertTrue(check(rec, "calibration_measured")["pass"])
        art["cal"][(B.FLOOR, B.SHIM)]["overall"]["log_loss"] += 1e-3
        rec, _ = run(art)
        self.assertFalse(check(rec, "calibration_measured")["pass"])

    def test_regression_tolerance_boundary(self):
        art = fresh()
        a = art["alpha_q"]["fastner-regression"]["metrics"]["slices"]["language=ko"]["strict"]["f1"]
        for m in (B.NATIVE, B.SHIM):
            art["q"][("fastner-regression", m)]["metrics"]["slices"]["language=ko"]["strict"]["f1"] = a - 0.019
        rec, _ = run(art)
        self.assertTrue(check(rec, "no_regression_vs_alpha")["pass"])
        for m in (B.NATIVE, B.SHIM):
            art["q"][("fastner-regression", m)]["metrics"]["slices"]["language=ko"]["strict"]["f1"] = a - 0.021
        rec, _ = run(art)
        self.assertFalse(check(rec, "no_regression_vs_alpha")["pass"])

    def test_perf_summary_definitions(self):
        pv = B.perf_values(B.load_artifacts()["perf"][B.NATIVE])
        self.assertAlmostEqual(pv["startup_ms"], 1.426, places=3)           # median cold start, in-process
        self.assertAlmostEqual(pv["throughput_docs_per_s"], 441849.2, delta=1)  # largest batch (32), median of repeats
        self.assertAlmostEqual(pv["peak_memory_mb"], 3.6254, places=3)


class IdentityCheckTests(unittest.TestCase):
    def adapter(self, **over):
        c = CFG["candidate"]
        ad = {"identity": {"adapter_version": "native-1", "model": {"digest": c["model"]["dir_digest"], "size_bytes": c["model"]["size_bytes"], "version": c["model"]["version"]},
                           "runtime": [{"name": "fastner-commit", "version": c["runtime"]["commit"]}] + [{"name": f"fastner-model:{f['name']}", "version": f["model_identity"]} for f in c["model"]["files"]]},
              "tags": {"runtime_tree": c["runtime"]["crate_tree"], "role": "candidate"}}
        for k, v in over.items():
            ad[k] = v
        return ad

    def test_valid_native_identity(self):
        BI.check_identity(CFG, {"id": B.NATIVE, "role": "candidate", "variant": "native"}, self.adapter(), "t")

    def test_mismatches_rejected(self):
        pin = {"id": B.NATIVE, "role": "candidate", "variant": "native"}
        ad = self.adapter()
        ad["identity"]["model"]["digest"] = "sha256:x"
        with self.assertRaises(BI.Beta1IngestError):
            BI.check_identity(CFG, pin, ad, "t")
        ad = self.adapter()
        ad["tags"]["runtime_tree"] = "0" * 40
        with self.assertRaises(BI.Beta1IngestError):
            BI.check_identity(CFG, pin, ad, "t")
        ad = self.adapter()
        ad["identity"]["runtime"][0]["version"] = "1" * 40
        with self.assertRaises(BI.Beta1IngestError):
            BI.check_identity(CFG, pin, ad, "t")

    def test_shim_must_be_tagged_as_transport_comparison(self):
        pin = {"id": B.SHIM, "role": "candidate", "variant": "shim"}
        ad = self.adapter()
        ad["identity"]["adapter_version"] = "1"
        with self.assertRaises(BI.Beta1IngestError):
            BI.check_identity(CFG, pin, ad, "t")
        ad["tags"]["role"] = "candidate-transport-comparison"
        BI.check_identity(CFG, pin, ad, "t")

    def test_unknown_adapter_has_no_pin(self):
        with self.assertRaises(BI.Beta1IngestError):
            BI.pin_for_adapter(CFG, "mystery")

    def test_reference_digest_must_equal_alpha_pin(self):
        r = next(iter(CFG["references"].items()))
        pin = BI.pin_for_adapter(CFG, r[0])
        ad = {"identity": {"model": {"digest": "sha256:bad", "size_bytes": 1, "version": None}}, "tags": {}}
        with self.assertRaises(BI.Beta1IngestError):
            BI.check_identity(CFG, pin, ad, "t")


class CommittedArtifactTests(unittest.TestCase):
    def test_no_case_text_or_diagnostics(self):
        bad = {"text", "surface", "diagnostics", "records", "pred", "gold", "fixture_id", "operating_curve", "reliability_equal_mass"}

        def walk(o):
            if isinstance(o, dict):
                for k, v in o.items():
                    yield k
                    yield from walk(v)
            elif isinstance(o, list):
                for v in o:
                    yield from walk(v)
        for f in (ROOT / "artifacts" / "beta1").rglob("*.json"):
            self.assertFalse(set(walk(json.loads(f.read_text(encoding="utf-8")))) & bad, f.name)

    def test_failures_only_for_own_corpora_and_non_controls(self):
        base = ROOT / "artifacts" / "beta1" / "quality"
        for f in base.rglob("*.json"):
            a = json.loads(f.read_text(encoding="utf-8"))
            has = "failures" in a
            own = a["corpus"]["id"] != B.FLOOR
            ctrl = a["model"]["id"].startswith("control-")
            self.assertEqual(has, own and not ctrl, f"{a['corpus']['id']}/{a['model']['id']}")

    def test_every_adapter_measured_on_every_population(self):
        art = B.load_artifacts()
        models = {B.NATIVE, B.SHIM, *B.REFS, "control-null", "control-capitalized-run"}
        for pop in (B.FLOOR,) + B.PRODUCT + ("candidate-specific",):
            self.assertEqual({m for (p, m) in art["q"] if p == pop}, models, pop)

    def test_perf_only_on_the_evidence_snapshot_with_repeats(self):
        art = B.load_artifacts()
        self.assertEqual(set(art["perf"]), {B.NATIVE, B.SHIM, *B.REFS, "control-null", "control-capitalized-run"})
        for c in art["perf"][B.NATIVE]["cells"]:
            self.assertEqual(c["repeats"], 5)

    @unittest.skipUnless((ROOT.parent / "ner-eval").exists(), "sibling ner-eval checkout not available")
    def test_ingest_reproducible_from_source(self):
        files, _ = BI.ingest(ROOT.parent / "ner-eval")
        base = ROOT / "artifacts" / "beta1"
        self.assertEqual(set(files), {str(p.relative_to(base)) for p in base.rglob("*.json")})
        for rel, text in files.items():
            self.assertEqual((base / rel).read_text(encoding="utf-8"), text, rel)


if __name__ == "__main__":
    unittest.main()
