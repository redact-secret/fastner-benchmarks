import copy
import json
import tempfile
import unittest
from pathlib import Path

from fnbench import ingest as I
from fnbench.artifacts import load_bakeoff
from fnbench.corpus import describe
from fnbench.pins import load_candidates
from fnbench.populations import load_populations
from fnbench.util import ROOT

CFG = load_candidates()
REG = load_populations()
BASE = ROOT / "artifacts" / "bakeoff" / CFG["bakeoff_id"]
SOURCE = ROOT.parent / "ner-eval"
FORBIDDEN_KEYS = {"text", "surface", "diagnostics", "records", "pred", "gold", "fixture_id"}


def walk(o):
    if isinstance(o, dict):
        for k, v in o.items():
            yield k
            yield from walk(v)
    elif isinstance(o, list):
        for v in o:
            yield from walk(v)


class CommittedArtifactTests(unittest.TestCase):
    def setUp(self):
        self.q, self.p = load_bakeoff(CFG["bakeoff_id"])
        self.pub = [a for a in self.q if a["corpus"]["id"] == "ner-evidence-public"]

    def test_every_resolved_pin_has_public_quality_and_perf_artifact(self):
        resolved = {e["id"] for e in CFG["candidates"] if e["pin_status"] == "resolved"}
        self.assertEqual({a["model"]["id"] for a in self.pub}, resolved)
        self.assertEqual({a["model"]["id"] for a in self.p}, resolved)
        self.assertNotIn("ref-gliner-multi", {a["model"]["id"] for a in self.q})

    def test_product_corpora_measured_for_crf_and_controls_only(self):
        for pop in ("fastner-regression", "fastner-adversarial"):
            models = {a["model"]["id"] for a in self.q if a["corpus"]["id"] == pop}
            self.assertEqual(models, {"fastner-b-linear-crf", "control-null", "control-capitalized-run"})

    def test_artifact_digests_equal_pin_digests(self):
        pins = {e["id"]: e["model"]["artifact_digest"] for e in CFG["candidates"]}
        for a in self.q + self.p:
            self.assertEqual(a["model"]["artifact_digest"], pins[a["model"]["id"]])

    def test_corpus_identity_per_population_and_one_environment(self):
        snap = next(p for p in REG["populations"] if p["id"] == "ner-evidence-public")["identity"]
        for a in self.pub:
            self.assertEqual((a["corpus"]["digest"], a["corpus"]["case_count"]), (snap["snapshot_digest"], snap["case_count"]))
        for pop in ("fastner-regression", "fastner-adversarial"):
            d = describe(pop)
            for a in (x for x in self.q if x["corpus"]["id"] == pop):
                self.assertEqual((a["corpus"]["digest"], a["corpus"]["case_count"]), (d["content_digest"], d["case_count"]))
        self.assertEqual(len({a["environment"]["id"] for a in self.p}), 1)
        self.assertEqual({a["source"]["ner_eval_run_id"] for a in self.q + self.p}, {r["run_id"] for r in CFG["source_runs"]})

    def test_runtime_commits_are_pinned_or_explicitly_also_measured(self):
        crf = next(e for e in CFG["candidates"] if e["id"] == "fastner-b-linear-crf")
        allowed = {crf["runtime"]["commit"]} | {x["commit"] for x in crf["runtime"]["also_measured_at"]}
        for a in self.q:
            if a["model"]["id"] == "fastner-b-linear-crf":
                self.assertIn(a["runtime_commit"], allowed)
        by_pop = {a["corpus"]["id"]: a["runtime_commit"] for a in self.q if a["model"]["id"] == "fastner-b-linear-crf"}
        self.assertNotEqual(by_pop["ner-evidence-public"], by_pop["fastner-regression"])  # two commits, same model digest

    def test_no_case_text_or_diagnostic_content_in_committed_artifacts(self):
        for f in BASE.rglob("*.json"):
            bad = set(walk(json.loads(f.read_text(encoding="utf-8")))) & FORBIDDEN_KEYS
            self.assertFalse(bad, f"{f.name}: {bad}")

    def test_failures_are_ids_and_outcomes_only(self):
        for pop in ("fastner-regression", "fastner-adversarial"):
            art = json.loads((BASE / "quality" / pop / "fastner-b-linear-crf.json").read_text())
            for f in art["failures"]:
                self.assertEqual(set(f), {"case_id", "outcome", "region"})
            self.assertEqual(len({f["case_id"] for f in art["failures"]}) > 0, True)
        pub = json.loads((BASE / "quality" / "ner-evidence-public" / "fastner-b-linear-crf.json").read_text())
        self.assertNotIn("failures", pub)  # internal-only snapshot: no per-case records

    def test_committed_source_hashes_present(self):
        man = json.loads((BASE / "ingest-manifest.json").read_text())
        self.assertEqual(len(man["source_artifact_file_sha256"]), len(self.q) + len(self.p))
        self.assertEqual([r["run_id"] for r in man["runs"]], [r["run_id"] for r in CFG["source_runs"]])

    def test_headline_numbers_match_ner_eval_reports(self):
        """Values documented in ner-eval's committed READMEs (strict P/R/F1, lenient F1)."""
        q = {a["model"]["id"]: a["metrics"]["overall"] for a in self.pub}
        crf = q["fastner-b-linear-crf"]
        self.assertEqual([round(crf["strict"][k], 3) for k in ("precision", "recall", "f1")], [0.733, 0.658, 0.694])
        self.assertEqual(round(crf["lenient"]["f1"], 3), 0.766)
        best = max((m for m in q if m.startswith("fastner-")), key=lambda m: q[m]["strict"]["f1"])
        self.assertEqual(best, "fastner-b-linear-crf")
        self.assertIsNone(q["control-null"]["strict"]["f1"])  # undefined stays None, never 0.0
        reg = next(a for a in self.q if a["corpus"]["id"] == "fastner-regression" and a["model"]["id"] == "fastner-b-linear-crf")
        adv = next(a for a in self.q if a["corpus"]["id"] == "fastner-adversarial" and a["model"]["id"] == "fastner-b-linear-crf")
        self.assertEqual(round(reg["metrics"]["overall"]["strict"]["f1"], 3), 0.857)
        self.assertEqual(round(adv["metrics"]["overall"]["strict"]["f1"], 3), 0.702)
        self.assertEqual((len(reg["failures"]), len(adv["failures"])), (10, 13))

    def test_sizes_and_wasm_come_from_role_tagged_artifacts(self):
        perf = {a["model"]["id"]: a["sizes"] for a in self.p}
        self.assertEqual(perf["fastner-b-linear-crf"], {"model_bytes": 590684, "binary_bytes": 563936, "wasm_bytes": 71680})
        self.assertIsNone(perf["ref-spacy-en"]["wasm_bytes"])  # references declare none: n/a, not zero
        self.assertEqual(len({perf[m]["binary_bytes"] for m in perf if m.startswith("fastner-")}), 1)  # shared shim

    @unittest.skipUnless(SOURCE.exists(), "sibling ner-eval checkout not available")
    def test_ingest_is_reproducible_from_source(self):
        files, _ = I.ingest(SOURCE)
        self.assertEqual(set(files), {str(p.relative_to(BASE)) for p in BASE.rglob("*.json")})
        for rel, text in files.items():
            self.assertEqual((BASE / rel).read_text(encoding="utf-8"), text, rel)


# ---- ingest failure modes on a miniature synthetic ner-eval run ----
D = "sha256:"
PIN = next(e for e in CFG["candidates"] if e["id"] == "fastner-b-linear-crf")
SNAP = next(p for p in REG["populations"] if p["id"] == "ner-evidence-public")["identity"]
RUN = CFG["source_runs"][0]["run_id"]


def metrics(f):
    m = {"precision": f, "recall": f, "f1": f}
    return {"strict": m, "boundary_lenient": m, "type_agnostic_exact": m}


def mini_run(root, mut=None):
    root = Path(root)
    (root / "quality").mkdir(parents=True)
    (root / "performance").mkdir()
    corpus = {"snapshot_id": SNAP["snapshot_id"], "content_digest": SNAP["snapshot_digest"], "case_count": SNAP["case_count"], "redistribution": "internal-only"}
    ad = {"adapter_id": "fastner-crf", "transport": "external-process", "tags": {"runtime_commit": PIN["runtime"]["commit"]},
          "artifacts": [{"role": "model", "size_bytes": PIN["model"]["size_bytes"]}, {"role": "binary", "size_bytes": 10}, {"role": "wasm", "size_bytes": 5}],
          "identity": {"adapter_version": "1", "model": {"digest": PIN["model"]["artifact_digest"], "size_bytes": PIN["model"]["size_bytes"], "version": PIN["model"]["version"], "revision": None}}}
    q = {"adapter": copy.deepcopy(ad), "corpus": corpus, "digest": D + "q1", "evaluator": {"version": "0.1.0"},
         "protocols": {"measurement": "m1", "slice_spec": "s1"}, "failure": None,
         "results": {"cases": 545, "diagnostics": {"records": [{"case_id": "SECRET-1", "pred": "SECRET TEXT"}]},
                     "overall": {"counts": {"exact": 1}, "metrics": metrics(0.5)},
                     "slices": {"slices": [{"id": "person/language=en", "cases": 244, "counts": {}, "metrics": metrics(0.6)}]}}}
    cell = lambda b, t: {"batch_size": b, "requested_threads": t, "effective_threads": 1, "failure": None,
                         "throughput": {"cases_per_sec": 1000.0}, "warm": {"per_case": {"p50_us": 10, "p95_us": 20}},
                         "memory": {"peak_rss_bytes": 1048576, "scope": "adapter-process"}, "cold": [{"startup_us": 1000, "first_batch_us": 5}]}
    p = {"adapter": copy.deepcopy(ad), "protocol": "pp1", "parameters": {}, "digest": D + "p1", "measurement_notes": ["n"],
         "environment": {"hardware_class": "hw1", "os": {"name": "os", "version": "1"}, "arch": "a", "cpu": {"model": "c", "logical_cores": 1},
                         "evaluator": {"rustc": "r", "version": "0.1.0", "profile": "release"}},
         "cells": [cell(1, 1), cell(16, 1)], "failure": None}
    man = {"run": {"run_id": RUN}, "corpus": corpus, "digest": D + "m1", "protocols": {"measurement": "m1", "performance": "pp1"},
           "quality_artifacts": [{"adapter_id": "fastner-crf", "digest": D + "q1", "path": "quality/a.json", "status": "ok"}]}
    pidx = {"run": {"run_id": RUN}, "environment_hardware_class": "hw1", "artifacts": [{"path": "performance/a.json", "status": "ok"}]}
    docs = {"q": q, "p": p, "man": man, "pidx": pidx}
    if mut:
        mut(docs)
    (root / "quality/a.json").write_text(json.dumps(docs["q"]))
    (root / "performance/a.json").write_text(json.dumps(docs["p"]))
    (root / "run-manifest.json").write_text(json.dumps(docs["man"]))
    (root / "performance-index.json").write_text(json.dumps(docs["pidx"]))
    small = copy.deepcopy(CFG)
    small["candidates"] = [e for e in small["candidates"] if e["id"] == "fastner-b-linear-crf"]
    small["source_runs"] = [{"run_id": RUN, "path": ".", "kind": "snapshot-with-performance", "population": "ner-evidence-public"}]
    return root, small


class IngestTests(unittest.TestCase):
    def run_ingest(self, mut=None):
        with tempfile.TemporaryDirectory() as d:
            root, small = mini_run(d, mut)
            return I.ingest(root, small, REG)

    def test_happy_path_normalizes_and_drops_diagnostics(self):
        files, man = self.run_ingest()
        q = json.loads(files["quality/ner-evidence-public/fastner-b-linear-crf.json"])
        self.assertEqual(q["corpus"]["id"], "ner-evidence-public")
        self.assertEqual(q["metrics"]["slices"]["language=en"]["strict"]["f1"], 0.6)
        self.assertNotIn("SECRET", json.dumps(files))
        self.assertFalse(set(walk(q)) & FORBIDDEN_KEYS)
        p = json.loads(files["perf/fastner-b-linear-crf.json"])
        self.assertEqual(p["sizes"], {"model_bytes": PIN["model"]["size_bytes"], "binary_bytes": 10, "wasm_bytes": 5})
        self.assertEqual(man["runs"][0]["run_id"], RUN)

    def test_deterministic(self):
        self.assertEqual(self.run_ingest()[0], self.run_ingest()[0])

    def reject(self, mut, fragment):
        with self.assertRaises(I.IngestError) as cm:
            self.run_ingest(mut)
        self.assertIn(fragment, str(cm.exception))

    def test_model_digest_mismatch_rejected(self):
        def m(d):
            for k in ("q", "p"):
                d[k]["adapter"]["identity"]["model"]["digest"] = D + "0" * 64
        self.reject(m, "model digest differs from pin")

    def test_runtime_commit_mismatch_rejected(self):
        self.reject(lambda d: d["q"]["adapter"]["tags"].update(runtime_commit="0" * 40), "runtime commit differs from pin")

    def test_model_size_and_version_mismatch_rejected(self):
        self.reject(lambda d: d["q"]["adapter"]["identity"]["model"].update(size_bytes=1), "model size differs from pin")
        self.reject(lambda d: d["q"]["adapter"]["identity"]["model"].update(version="other"), "model version differs from pin")

    def test_unknown_corpus_digest_or_case_count_rejected(self):
        def m(d):
            d["man"]["corpus"]["content_digest"] = D + "f" * 64
            d["q"]["corpus"]["content_digest"] = D + "f" * 64
        self.reject(m, "digest differs from pinned population")
        def n(d):
            d["man"]["corpus"]["case_count"] = 544
        self.reject(n, "case_count differs")

    def test_wrong_run_id_rejected(self):
        self.reject(lambda d: d["man"]["run"].update(run_id="run-other"), "not the pinned source run")

    def test_artifact_not_matching_manifest_entry_rejected(self):
        self.reject(lambda d: d["q"].update(digest=D + "tampered"), "does not match run-manifest entry")

    def test_unpinned_adapter_rejected(self):
        def m(d):
            d["q"]["adapter"]["adapter_id"] = "mystery"
            d["man"]["quality_artifacts"][0]["adapter_id"] = "mystery"
        self.reject(m, "no pin")

    def test_perf_hardware_class_mismatch_rejected(self):
        self.reject(lambda d: d["p"]["environment"].update(hardware_class="hw2"), "hardware class differs")

    def test_unavailable_adapter_is_unavailable_not_zero(self):
        def m(d):
            d["man"]["quality_artifacts"][0]["status"] = "unavailable"
            d["q"]["failure"] = {"kind": "pin-mismatch"}
            d["pidx"]["artifacts"][0]["status"] = "unavailable"
            d["p"]["failure"] = {"kind": "pin-mismatch"}
        files, _ = self.run_ingest(m)
        q = json.loads(files["quality/ner-evidence-public/fastner-b-linear-crf.json"])
        self.assertEqual(q["status"], "unavailable")
        self.assertIn("pin-mismatch", q["reason"])
        self.assertNotIn("metrics", q)

    def test_resolved_pin_without_artifact_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root, small = mini_run(d)
            full = copy.deepcopy(CFG)
            full["source_runs"] = small["source_runs"]
            with self.assertRaises(I.IngestError) as cm:
                I.ingest(root, full, REG)
            self.assertIn("resolved pins with no artifact", str(cm.exception))


def mini_product_run(root, mut=None, population="fastner-regression"):
    """A miniature ner-eval product-corpora run for the committed regression corpus."""
    from fnbench.corpus import describe as desc
    d = desc(population)
    root = Path(root)
    (root / "quality").mkdir(parents=True)
    corpus = {"snapshot_id": population, "content_digest": d["content_digest"], "case_count": d["case_count"], "redistribution": None}
    commit = "89c4134d67f1d7d0033dba040ed9bc533d05c214"
    ad = {"adapter_id": "fastner-crf", "transport": "external-process", "tags": {"runtime_commit": commit}, "artifacts": [],
          "identity": {"adapter_version": "1", "model": {"digest": PIN["model"]["artifact_digest"], "size_bytes": PIN["model"]["size_bytes"], "version": PIN["model"]["version"], "revision": None}}}
    q = {"adapter": ad, "corpus": corpus, "digest": D + "pq", "evaluator": {"version": "0.1.0"}, "protocols": {"measurement": "m1", "slice_spec": "s1"}, "failure": None,
         "results": {"cases": d["case_count"], "diagnostics": {"truncated": False, "records": [{"case_id": "fnb-reg-003", "outcome": "false-positive", "region": "asserted-negative", "pred": {"start": 1, "end": 2}}]},
                     "overall": {"counts": {}, "metrics": metrics(0.8)}, "slices": {"slices": [{"id": "person/language=en", "cases": 34, "counts": {}, "metrics": metrics(0.8)}]}}}
    man = {"run": {"run_id": "run-prod"}, "corpus": corpus, "digest": D + "pm", "protocols": {"measurement": "m1", "performance": "pp1"},
           "quality_artifacts": [{"adapter_id": "fastner-crf", "digest": D + "pq", "path": "quality/a.json", "status": "ok"}]}
    docs = {"q": q, "man": man}
    if mut:
        mut(docs)
    (root / "quality/a.json").write_text(json.dumps(docs["q"]))
    (root / "run-manifest.json").write_text(json.dumps(docs["man"]))
    small = copy.deepcopy(CFG)
    small["candidates"] = [e for e in small["candidates"] if e["id"] == "fastner-b-linear-crf"]
    for e in small["candidates"]:
        e["runtime"]["also_measured_at"][0]["runs"] = ["run-prod"]
    run = {"run_id": "run-prod", "path": ".", "kind": "product-quality", "population": population}
    return root, small, run


class ProductRunIngestTests(unittest.TestCase):
    def go(self, mut=None, population="fastner-regression"):
        with tempfile.TemporaryDirectory() as d:
            root, small, run = mini_product_run(d, mut, population)
            return I.ingest_run(root, small, REG, run)

    def test_happy_path_keeps_failure_ids_not_text(self):
        files, _, info = self.go()
        a = json.loads(files["quality/fastner-regression/fastner-b-linear-crf.json"])
        self.assertEqual(a["failures"], [{"case_id": "fnb-reg-003", "outcome": "false-positive", "region": "asserted-negative"}])
        self.assertEqual(a["runtime_commit"], "89c4134d67f1d7d0033dba040ed9bc533d05c214")
        self.assertEqual(info["population"], "fastner-regression")
        self.assertNotIn("\"pred\":", json.dumps(files))
        self.assertFalse([k for k in files if k.startswith("perf/")])  # product runs carry no performance

    def reject(self, mut, fragment, population="fastner-regression"):
        with self.assertRaises(I.IngestError) as cm:
            self.go(mut, population)
        self.assertIn(fragment, str(cm.exception))

    def test_corpus_version_drift_rejected(self):
        def m(d):
            d["man"]["corpus"]["content_digest"] = D + "e" * 64
            d["q"]["corpus"]["content_digest"] = D + "e" * 64
        self.reject(m, "different corpus version")

    def test_case_count_drift_rejected(self):
        def m(d):
            d["man"]["corpus"]["case_count"] += 1
        self.reject(m, "case_count differs")

    def test_run_measured_wrong_population_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root, small, run = mini_product_run(d)
            run["population"] = "fastner-adversarial"
            with self.assertRaises(I.IngestError):
                I.ingest_run(root, small, REG, run)

    def test_unlisted_runtime_commit_rejected(self):
        self.reject(lambda d: d["q"]["adapter"]["tags"].update(runtime_commit="1" * 40), "runtime commit differs from pin")

    def test_truncated_diagnostics_rejected(self):
        self.reject(lambda d: d["q"]["results"]["diagnostics"].update(truncated=True), "diagnostics truncated")

    def test_account_artifact_rejects_stale_corpus_version(self):
        from fnbench.populations import PopulationError, account_artifact
        d = describe("fastner-regression")
        ok = {"corpus": {"id": "fastner-regression", "case_count": d["case_count"], "digest": d["content_digest"]}}
        self.assertEqual(account_artifact(REG, ok), "fastner-regression")
        ok["corpus"]["digest"] = D + "0" * 64
        with self.assertRaises(PopulationError):
            account_artifact(REG, ok)


if __name__ == "__main__":
    unittest.main()
