import copy
import unittest

from fnbench import populations as P


def qa(cid, n=None, digest=None):
    return {"run_id": "r1", "corpus": {"id": cid, "case_count": n, "digest": digest}}


class PopulationTests(unittest.TestCase):
    def setUp(self):
        self.reg = P.load_populations()

    def test_five_distinct_populations_with_roles(self):
        ids = {p["id"] for p in self.reg["populations"]}
        self.assertEqual(ids, {"ner-evidence-public", "fastner-regression", "fastner-adversarial",
                               "candidate-specific", "protected-holdout"})
        self.assertEqual(len({p["role"] for p in self.reg["populations"]}), 5)

    def test_each_population_carries_provenance_and_identity(self):
        for p in self.reg["populations"]:
            for f in ("source", "license", "synthetic", "personal_data", "custody"):
                self.assertIn(f, p["provenance"])
            self.assertIn("identity", p)

    def test_unpinned_populations_say_what_blocks_them(self):
        for p in self.reg["populations"]:
            if p["status"] != "available":
                self.assertTrue(p["blocked_by"])

    def test_merged_population_rejected(self):
        with self.assertRaises(P.PopulationError):
            P.account_artifact(self.reg, qa("fastner-regression+fastner-adversarial"))

    def test_unknown_population_rejected(self):
        with self.assertRaises(P.PopulationError):
            P.account_artifact(self.reg, qa("some-other-corpus"))

    def test_planned_population_cannot_qualify(self):
        with self.assertRaises(P.PopulationError):
            P.account_artifact(self.reg, qa("candidate-specific", 10))

    def test_public_snapshot_is_pinned_and_identity_enforced(self):
        pub = P.by_id(self.reg)["ner-evidence-public"]
        ident = pub["identity"]
        self.assertEqual(pub["status"], "available")
        self.assertEqual(ident["case_count"], 545)
        self.assertFalse(pub["is_holdout"])
        self.assertTrue(pub["caveats"])
        self.assertEqual(P.account_artifact(self.reg, qa("ner-evidence-public", 545, ident["snapshot_digest"])), "ner-evidence-public")
        with self.assertRaises(P.PopulationError):
            P.account_artifact(self.reg, qa("ner-evidence-public", 544, ident["snapshot_digest"]))
        with self.assertRaises(P.PopulationError):
            P.account_artifact(self.reg, qa("ner-evidence-public", 545, "sha256:" + "0" * 64))

    def test_denominators_never_combined(self):
        with self.assertRaises(P.PopulationError):
            P.combined_denominator(1, 2)

    def test_holdout_must_be_private(self):
        reg = copy.deepcopy(self.reg)
        for p in reg["populations"]:
            if p["role"] == "holdout-gate":
                p["publication"] = "public"
        with self.assertRaises(P.PopulationError):
            P.validate_registry(reg)

    def test_duplicate_roles_rejected(self):
        reg = copy.deepcopy(self.reg)
        reg["populations"][2]["role"] = reg["populations"][1]["role"]
        with self.assertRaises(P.PopulationError):
            P.validate_registry(reg)

    def test_missing_provenance_rejected(self):
        reg = copy.deepcopy(self.reg)
        del reg["populations"][1]["provenance"]["custody"]
        with self.assertRaises(P.PopulationError):
            P.validate_registry(reg)


if __name__ == "__main__":
    unittest.main()
