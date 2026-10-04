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

    def test_nothing_is_falsely_resolved(self):
        # No runtime/model/digest exists yet; any "resolved" pin here would be fabricated.
        self.assertTrue(all(e["pin_status"] == "unresolved" for e in self.cfg["candidates"]))
        with self.assertRaises(P.PinError):
            P.require_resolved(self.cfg, {"fastner-a-statistical"})

    def test_resolved_pin_requires_all_fields(self):
        cfg = copy.deepcopy(self.cfg)
        cfg["candidates"][0]["pin_status"] = "resolved"
        with self.assertRaises(P.PinError) as cm:
            P.validate_config(cfg)
        self.assertIn("model.artifact_digest", str(cm.exception))

    def test_complete_pin_validates(self):
        cfg = copy.deepcopy(self.cfg)
        e = cfg["candidates"][0]
        e["pin_status"] = "resolved"
        e["runtime"].update(commit="abc123", version="0.0.1")
        e["adapter"]["version"] = "1"
        e["model"].update(artifact_digest=DIG, size_bytes=1000, format_version="1")
        self.assertTrue(P.validate_config(cfg))
        self.assertEqual(P.missing_pin_fields(cfg, e), [])

    def test_bad_digest_rejected(self):
        cfg = copy.deepcopy(self.cfg)
        e = cfg["candidates"][0]
        e["pin_status"] = "resolved"
        e["runtime"].update(commit="abc", version="1")
        e["adapter"]["version"] = "1"
        e["model"].update(artifact_digest="md5:xyz", size_bytes=1, format_version="1")
        with self.assertRaises(P.PinError):
            P.validate_config(cfg)

    def test_unresolved_must_not_carry_digest(self):
        cfg = copy.deepcopy(self.cfg)
        cfg["candidates"][0]["model"]["artifact_digest"] = DIG
        with self.assertRaises(P.PinError):
            P.validate_config(cfg)

    def test_unavailable_reference_needs_reason_and_is_not_zero(self):
        cfg = copy.deepcopy(self.cfg)
        ref = next(e for e in cfg["candidates"] if e["role"] == "reference")
        ref["pin_status"] = "unavailable"
        with self.assertRaises(P.PinError):
            P.validate_config(cfg)
        ref["unavailable_reason"] = "license forbids redistribution of weights"
        P.validate_config(cfg)
        row = next(r for r in P.pin_table(cfg) if r["id"] == ref["id"])
        self.assertIsNone(row["model_size_bytes"])
        self.assertEqual(row["pin_status"], "unavailable")

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
