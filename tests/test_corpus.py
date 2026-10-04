import copy
import json
import unicodedata
import unittest

from fnbench import corpus as C
from fnbench import workloads as W
from fnbench.populations import load_populations
from fnbench.util import ROOT


class CorpusTests(unittest.TestCase):
    def test_markup_byte_offsets_multibyte(self):
        plain, spans = C.parse_markup("🎉[[김민수]]가 왔다")
        self.assertEqual(plain, "🎉김민수가 왔다")
        s, e, sf = spans[0]
        self.assertEqual(plain.encode()[s:e].decode(), "김민수")
        self.assertEqual((s, e), (4, 13))

    def test_generated_files_are_current(self):
        for cid, c in C.CORPORA.items():
            built = C.build(cid)
            self.assertEqual((ROOT / c["dir"] / f"{c['stem']}.jsonl").read_text(encoding="utf-8"), built, cid)

    def test_all_spans_valid_and_unicode_cases_nontrivial(self):
        for cid in C.CORPORA:
            for r in C.read_built(cid):
                raw = r["text"].encode()
                for e in r["entities"]:
                    self.assertEqual(raw[e["start"]:e["end"]].decode(), e["surface"])
        nfd = [r for r in C.read_built("fastner-adversarial") if r["category"] == "unicode-normalization" and r["id"].endswith("008")]
        self.assertFalse(unicodedata.is_normalized("NFC", nfd[0]["text"]))

    def test_issue_categories_covered(self):
        cats = set()
        for cid in C.CORPORA:
            cats |= {r["category"] for r in C.read_built(cid)}
        for need in ("ambiguity-false-positive", "unseen-name", "en-tokenization", "ko-tokenization", "ko-particle",
                     "ko-particle-false-positive", "mixed-script", "unicode-invisible", "unicode-normalization", "boundary"):
            self.assertIn(need, cats)

    def test_corpora_have_positives_and_negatives_in_en_and_ko(self):
        rows = C.read_built("fastner-regression")
        for lang in ("en", "ko"):
            sub = [r for r in rows if r["slices"]["language"] == lang]
            self.assertTrue(any(r["negative"] for r in sub))
            self.assertTrue(any(not r["negative"] for r in sub))

    def test_honest_origin_labels(self):
        # No bakeoff has run: nothing may claim bakeoff-failure origin without lineage.
        for cid in C.CORPORA:
            for r in C.read_built(cid):
                self.assertEqual(r["origin"], "seed-taxonomy")

    # ---- isolation ----
    def test_ids_disjoint_and_prefixed(self):
        a = {r["id"] for r in C.read_built("fastner-regression")}
        b = {r["id"] for r in C.read_built("fastner-adversarial")}
        self.assertFalse(a & b)
        self.assertTrue(all(i.startswith("fnb-reg-") for i in a))
        self.assertTrue(all(i.startswith("fnb-adv-") for i in b))

    def test_foreign_prefix_and_duplicates_rejected(self):
        rows = C.read_built("fastner-regression")
        bad = copy.deepcopy(rows)
        bad[0]["id"] = "ne-0001"
        with self.assertRaises(C.CorpusError):
            C.validate_cases("fastner-regression", bad)
        dup = copy.deepcopy(rows)
        dup[1]["id"] = dup[0]["id"]
        with self.assertRaises(C.CorpusError):
            C.validate_cases("fastner-regression", dup)

    def test_corpus_does_not_reach_into_other_repos(self):
        for path in (ROOT / "corpora").rglob("*"):
            if path.is_file():
                self.assertNotIn("ner-evidence/", path.read_text(encoding="utf-8"), str(path))
        reg = load_populations()
        for p in reg["populations"]:
            if p["owner"] == "fastner-benchmarks":
                self.assertTrue(p["artifact"]["path"].startswith("corpora/"))

    def test_unsafe_text_rejected(self):
        rows = copy.deepcopy(C.read_built("fastner-regression"))
        rows[0]["text"] = "write to someone@example.org"
        with self.assertRaises(C.CorpusError):
            C.validate_cases("fastner-regression", rows)

    def test_non_seed_origin_needs_lineage_and_seen_false_needs_basis(self):
        rows = copy.deepcopy(C.read_built("fastner-regression"))
        rows[0]["origin"] = "bakeoff-failure"
        with self.assertRaises(C.CorpusError):
            C.validate_cases("fastner-regression", rows)
        rows = copy.deepcopy(C.read_built("fastner-regression"))
        t = next(r for r in rows if r["slices"]["seen"] == "false")
        del t["seen_basis"]
        with self.assertRaises(C.CorpusError):
            C.validate_cases("fastner-regression", rows)

    def test_reports_contain_no_case_text(self):
        # Public artifacts carry ids/counts/digests only (ARCHITECTURE §10).
        blob = "".join(p.read_text(encoding="utf-8") for p in (ROOT / "reports").rglob("*") if p.is_file())
        for cid in C.CORPORA:
            for r in C.read_built(cid):
                for e in r["entities"]:
                    self.assertNotIn(e["surface"], blob)

    def test_companions_never_counted(self):
        reg = load_populations()
        self.assertTrue(reg["companions"])
        self.assertTrue(all(not c["counts_in_denominator"] for c in reg["companions"]))
        contracts = json.loads((ROOT / "corpora/regression/runtime-contracts.json").read_text())
        self.assertGreaterEqual(len(contracts["contracts"]), 10)
        self.assertEqual({c["category"] for c in contracts["contracts"]}, {"model-format", "runtime"})


class WorkloadTests(unittest.TestCase):
    def test_generated_file_current(self):
        self.assertEqual(OUT_TEXT(), W.build())

    def test_deterministic_and_seed_sensitive(self):
        spec = {"seed": 7, "doc_count": 20, "language": "mixed", "sentences": [2, 4], "name_rate": 0.5}
        self.assertEqual(W.generate(spec), W.generate(spec))
        self.assertNotEqual(W.generate(spec), W.generate({**spec, "seed": 8}))

    def test_workload_kinds_present(self):
        ids = {w["id"] for w in json.loads(OUT_TEXT())["workloads"]}
        for need in ("perf-short-chat-en", "perf-short-chat-ko", "perf-long-document-en", "perf-name-dense-en", "perf-name-free-ko", "perf-pathological-long-token"):
            self.assertIn(need, ids)

    def test_name_free_has_no_names(self):
        spec = {"seed": 1, "doc_count": 50, "language": "ko", "sentences": [3, 6], "name_rate": 0.0}
        for d in W.generate(spec):
            self.assertFalse(any(n in d for n in W.KO_NAMES))


def OUT_TEXT():
    return W.OUT.read_text(encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
