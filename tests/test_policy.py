import copy
import unittest

from fnbench.pareto import dominates, frontier
from fnbench.policy import PolicyError, dimension_map, load_policy, validate_policy


class PolicyTests(unittest.TestCase):
    def setUp(self):
        self.policy = load_policy()

    def test_loads_and_is_versioned(self):
        self.assertEqual(self.policy["policy_version"], "0.2.0")
        self.assertEqual(self.policy["quality_match_mode"], "strict")
        self.assertTrue(self.policy["no_single_score"])

    def test_dimension_coverage_matches_issue(self):
        ids = set(dimension_map(self.policy))
        for need in ("ambiguous_name_precision", "unseen_name_recall", "en_f1", "ko_f1",
                     "latency_p95_ms", "throughput_docs_per_s", "startup_ms", "peak_memory_mb",
                     "model_size_bytes", "runtime_binary_size_bytes", "wasm_size_bytes"):
            self.assertIn(need, ids)

    def test_rejects_single_score_flag_off(self):
        p = copy.deepcopy(self.policy)
        p["no_single_score"] = False
        with self.assertRaises(PolicyError):
            validate_policy(p)

    def test_rejects_composite_dimension_and_weights(self):
        p = copy.deepcopy(self.policy)
        p["dimensions"].append({"id": "overall_score", "group": "x", "title": "x", "direction": "max",
                                "unit": "x", "source": {"artifact": "quality"}})
        with self.assertRaises(PolicyError):
            validate_policy(p)
        p = copy.deepcopy(self.policy)
        p["dimensions"][0]["weight"] = 0.5
        with self.assertRaises(PolicyError):
            validate_policy(p)

    def test_rejects_lenient_substitution_and_missing_perf_summary(self):
        p = copy.deepcopy(self.policy)
        p["quality_match_mode"] = "boundary_lenient"
        with self.assertRaises(PolicyError):
            validate_policy(p)
        p = copy.deepcopy(self.policy)
        del p["perf_summary"]
        with self.assertRaises(PolicyError):
            validate_policy(p)
        p = copy.deepcopy(self.policy)
        p["dimensions"][0]["source"]["match"] = "boundary_lenient"
        with self.assertRaises(PolicyError):
            validate_policy(p)

    def test_rejects_missing_dimension(self):
        p = copy.deepcopy(self.policy)
        p["dimensions"] = [d for d in p["dimensions"] if d["id"] != "wasm_size_bytes"]
        with self.assertRaises(PolicyError):
            validate_policy(p)


class ParetoTests(unittest.TestCase):
    DIMS = [{"id": "f1", "direction": "max"}, {"id": "size", "direction": "min"}]

    def test_small_but_worse_and_big_but_better_both_survive(self):
        c = {"small": {"f1": 0.80, "size": 1}, "big": {"f1": 0.95, "size": 100}}
        front, dom, inc = frontier(c, self.DIMS)
        self.assertEqual(front, ["big", "small"])
        self.assertEqual(dom, {})

    def test_dominated_candidate_removed(self):
        c = {"a": {"f1": 0.9, "size": 10}, "b": {"f1": 0.8, "size": 20}}
        front, dom, _ = frontier(c, self.DIMS)
        self.assertEqual(front, ["a"])
        self.assertEqual(dom, {"b": ["a"]})

    def test_missing_value_is_not_zero(self):
        c = {"a": {"f1": 0.9, "size": 10}, "b": {"f1": None, "size": 1}}
        front, dom, inc = frontier(c, self.DIMS)
        self.assertEqual(inc, {"b": ["f1"]})
        self.assertEqual(front, ["a"])
        self.assertFalse(dominates({"f1": 0.9, "size": 10}, {"f1": None, "size": 20}, self.DIMS))

    def test_equal_vectors_do_not_dominate(self):
        v = {"f1": 0.9, "size": 10}
        self.assertFalse(dominates(v, dict(v), self.DIMS))


if __name__ == "__main__":
    unittest.main()
