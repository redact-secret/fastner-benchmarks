import copy
import unittest

from fnbench import pins as P

DIG = "sha256:" + "a" * 64


class PinTests(unittest.TestCase):
    def setUp(self):
        self.cfg = P.load_candidates()

    def test_four_architecture_classes_and_references_pinned_in_config(self):
        classes = {e["class"] for e in self.cfg["candidates"] if e["role"] == "candidate"}
        self.assertEqual(classes, P.REQUIRED_CLASSES)
        self.assertGreaterEqual(sum(e["role"] == "reference" for e in self.cfg["candidates"]), 3)

    def test_candidate_pins_are_real_and_complete(self):
        for e in self.cfg["candidates"]:
            if e["role"] == "candidate":
                self.assertEqual(e["pin_status"], "resolved")
                self.assertRegex(e["runtime"]["commit"], r"^[0-9a-f]{40}$")
                self.assertRegex(e["model"]["artifact_digest"], r"^sha256:[0-9a-f]{64}$")
                self.assertEqual(P.missing_pin_fields(self.cfg, e), [])

    def test_all_candidates_share_one_runtime_commit(self):
        commits = {e["runtime"]["commit"] for e in self.cfg["candidates"] if e["role"] == "candidate"}
        self.assertEqual(len(commits), 1)

    def test_planned_reference_stays_unresolved_and_cannot_qualify(self):
        g = next(e for e in self.cfg["candidates"] if e["id"] == "ref-gliner-multi")
        self.assertEqual(g["pin_status"], "unresolved")
        self.assertIsNone(g["model"]["artifact_digest"])
        with self.assertRaises(P.PinError):
            P.require_resolved(self.cfg, {"ref-gliner-multi"})

    def test_resolved_pin_requires_all_fields(self):
        cfg = copy.deepcopy(self.cfg)
        e = next(x for x in cfg["candidates"] if x["id"] == "fastner-b-linear-crf")
        e["model"]["artifact_digest"] = None
        with self.assertRaises(P.PinError) as cm:
            P.validate_config(cfg)
        self.assertIn("model.artifact_digest", str(cm.exception))

    def test_short_commit_rejected(self):
        cfg = copy.deepcopy(self.cfg)
        next(x for x in cfg["candidates"] if x["role"] == "candidate")["runtime"]["commit"] = "007805d"
        with self.assertRaises(P.PinError):
            P.validate_config(cfg)

    def test_reference_accepts_revision_or_version(self):
        cfg = copy.deepcopy(self.cfg)
        spacy = next(x for x in cfg["candidates"] if x["id"] == "ref-spacy-en")  # version-pinned, no revision
        self.assertIsNone(spacy["model"]["revision"])
        self.assertEqual(P.missing_pin_fields(cfg, spacy), [])
        spacy["model"]["version"] = None
        self.assertEqual(P.missing_pin_fields(cfg, spacy), ["model.revision|model.version"])

    def test_bad_digest_rejected(self):
        cfg = copy.deepcopy(self.cfg)
        next(x for x in cfg["candidates"] if x["id"] == "fastner-b-linear-crf")["model"]["artifact_digest"] = "md5:xyz"
        with self.assertRaises(P.PinError):
            P.validate_config(cfg)

    def test_unresolved_must_not_carry_digest(self):
        cfg = copy.deepcopy(self.cfg)
        next(x for x in cfg["candidates"] if x["id"] == "ref-gliner-multi")["model"]["artifact_digest"] = DIG
        with self.assertRaises(P.PinError):
            P.validate_config(cfg)

    def test_unavailable_reference_needs_reason_and_is_not_zero(self):
        cfg = copy.deepcopy(self.cfg)
        ref = next(e for e in cfg["candidates"] if e["id"] == "ref-gliner-multi")
        ref["pin_status"] = "unavailable"
        with self.assertRaises(P.PinError):
            P.validate_config(cfg)
        ref["unavailable_reason"] = "license forbids redistribution of weights"
        P.validate_config(cfg)
        row = next(r for r in P.pin_table(cfg) if r["id"] == ref["id"])
        self.assertIsNone(row["model_size_bytes"])
        self.assertEqual(row["pin_status"], "unavailable")

    def test_controls_are_pinned_but_are_neither_candidates_nor_references(self):
        roles = {e["id"]: e["role"] for e in self.cfg["candidates"]}
        self.assertEqual(roles["control-null"], "control")
        self.assertEqual(roles["control-capitalized-run"], "control")

    def test_config_hash_is_deterministic_and_sensitive(self):
        e = copy.deepcopy(self.cfg["candidates"][0])
        h = P.config_hash(e)
        self.assertEqual(h, P.config_hash(copy.deepcopy(e)))
        e["config"]["decoder"] = "other"
        self.assertNotEqual(h, P.config_hash(e))

    def test_unknown_population_rejected(self):
        cfg = copy.deepcopy(self.cfg)
        cfg["quality_populations"].append("nope")
        with self.assertRaises(P.PinError):
            P.validate_config(cfg)


if __name__ == "__main__":
    unittest.main()
