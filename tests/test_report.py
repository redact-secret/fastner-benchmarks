import copy
import json
import unittest

from fnbench import report as R
from fnbench.artifacts import ArtifactError
from fnbench.util import ROOT, canonical_json
from tests import helpers as H


class ReportTests(unittest.TestCase):
    def build(self, q=None, p=None):
        pol, cfg, reg, qs, ps = H.world()
        return R.build_report(pol, cfg, reg, qs if q is None else q, ps if p is None else p)

    def test_frontier_keeps_tradeoffs_and_drops_dominated(self):
        r = self.build()
        self.assertEqual(r["pareto"]["frontier"], ["fastner-a-statistical", "fastner-b-linear-crf", "fastner-c-compact-neural"])
        self.assertEqual(r["pareto"]["dominated"], {"fastner-d-tiny-transformer": ["fastner-c-compact-neural"]})

    def test_deterministic_bytes(self):
        a, b = self.build(), self.build()
        self.assertEqual(canonical_json(a), canonical_json(b))
        self.assertEqual(R.render_markdown(a), R.render_markdown(b))

    def test_input_order_irrelevant(self):
        pol, cfg, reg, qs, ps = H.world()
        r1 = R.build_report(pol, cfg, reg, qs, ps)
        r2 = R.build_report(pol, cfg, reg, list(reversed(qs)), list(reversed(ps)))
        self.assertEqual(canonical_json(r1), canonical_json(r2))

    def test_all_views_present_and_slices_visible(self):
        r = self.build()
        for v in ("global_quality", "language_quality", "ambiguity_precision", "unseen_recall", "collision_slices",
                  "latency", "throughput", "startup", "memory", "model_size", "binary_size", "wasm_size"):
            self.assertIn(v, r["views"])
        self.assertEqual(r["views"]["collision_slices"]["dimensions"], ["collision=common-word", "collision=location"])
        wasm = {x["model"]: x for x in r["views"]["wasm_size"]["rows"]}
        self.assertEqual(wasm["fastner-a-statistical"]["delta_bytes"], 100)

    def test_no_composite_keys_anywhere(self):
        text = canonical_json(self.build()).lower()
        for bad in ("overall_score", "composite", "universal_score", "weighted"):
            self.assertNotIn(bad, text)

    def test_unmeasured_is_none_not_zero(self):
        r = self.build()
        self.assertIsNone(r["values"]["ref-spacy-en"]["entity_f1"])
        self.assertIn("n/a", R.render_markdown(r))

    def test_unavailable_artifact_reported_with_reason(self):
        pol, cfg, reg, qs, ps = H.world()
        qs.append(H.quality("ref-spacy-en", status="unavailable"))
        r = R.build_report(pol, cfg, reg, qs, ps)
        self.assertEqual(r["unavailable"]["ref-spacy-en"], "adapter crashed")
        self.assertIsNone(r["values"]["ref-spacy-en"]["entity_f1"])
        self.assertTrue(any("unavailable (adapter crashed)" in x for x in r["known_limitations"]))

    def test_unresolved_pin_artifact_rejected(self):
        qs = [H.quality("ref-bert-base-ner")]
        r = self.build(q=qs + self.build_qs())
        self.assertTrue(any(x["run_id"] == "q-ref-bert-base-ner" for x in r["rejected_artifacts"]))
        self.assertIsNone(r["values"]["ref-bert-base-ner"]["entity_f1"])

    def build_qs(self):
        return H.world()[3]

    def test_digest_mismatch_rejected(self):
        q = H.quality("fastner-a-statistical")
        q["model"]["artifact_digest"] = "sha256:" + "0" * 64
        r = self.build(q=[q])
        self.assertEqual(len(r["rejected_artifacts"]), 1)
        self.assertEqual(r["accepted_artifacts"]["quality"], [])

    def test_merged_or_unregistered_corpus_rejected(self):
        q = H.quality("fastner-a-statistical", corpus="ner-evidence-public+fastner-regression")
        r = self.build(q=[q])
        self.assertIn("not in bakeoff quality_populations", r["rejected_artifacts"][0]["reason"])

    def test_case_count_mismatch_rejected(self):
        q = H.quality("fastner-a-statistical")
        q["corpus"]["case_count"] = 99
        r = self.build(q=[q])
        self.assertEqual(r["accepted_artifacts"]["quality"], [])

    def test_duplicate_artifact_is_error(self):
        q = H.quality("fastner-a-statistical")
        q2 = copy.deepcopy(q)
        q2["run_id"] = "other"
        with self.assertRaises(ArtifactError):
            self.build(q=[q, q2])

    def test_mixed_protocol_versions_error(self):
        qs = [H.quality("fastner-a-statistical", proto="p1"), H.quality("fastner-b-linear-crf", proto="p2")]
        with self.assertRaises(ArtifactError):
            self.build(q=qs)

    def test_perf_environment_mismatch_withheld(self):
        pol, cfg, reg, qs, ps = H.world()
        ps[0] = H.perf("fastner-a-statistical", env="env-2")
        r = R.build_report(pol, cfg, reg, qs, ps)
        self.assertIsNone(r["values"]["fastner-b-linear-crf"]["latency_p95_ms"])
        self.assertEqual(r["pareto"]["frontier"], [])
        self.assertTrue(any("environments" in x for x in r["known_limitations"]))

    def test_incomplete_candidate_excluded_not_zeroed(self):
        pol, cfg, reg, qs, ps = H.world()
        del ps[0]["wasm_size_bytes"]
        r = R.build_report(pol, cfg, reg, qs, ps)
        self.assertIn("wasm_size_bytes", r["pareto"]["incomplete"]["fastner-a-statistical"])
        self.assertNotIn("fastner-a-statistical", r["pareto"]["frontier"])

    def test_empty_inputs_say_not_measured(self):
        r = self.build(q=[], p=[])
        self.assertEqual(r["pareto"]["frontier"], [])
        self.assertTrue(any("No accepted ner-eval artifacts" in x for x in r["known_limitations"]))

    def test_committed_report_is_current(self):
        js, md = R.generate()
        out = ROOT / "reports" / "bakeoff" / "alpha0-bakeoff-1"
        self.assertEqual((out / "report.json").read_text(), js)
        self.assertEqual((out / "report.md").read_text(), md)
        json.loads(js)


if __name__ == "__main__":
    unittest.main()
