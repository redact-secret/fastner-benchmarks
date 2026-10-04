import copy
import json
import tempfile
import unittest
from pathlib import Path

from fnbench import ingest as I
from fnbench.artifacts import load_bakeoff
from fnbench.pins import load_candidates
from fnbench.populations import load_populations
from fnbench.util import ROOT

CFG = load_candidates()
REG = load_populations()
BASE = ROOT / "artifacts" / "bakeoff" / CFG["bakeoff_id"]
SOURCE = ROOT.parent / "ner-eval" / "results" / "alpha1-full"
FORBIDDEN_KEYS = {"text", "surface", "diagnostics", "records", "pred", "gold", "case_id", "fixture_id"}


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

    def test_every_resolved_pin_has_quality_and_perf_artifact(self):
        resolved = {e["id"] for e in CFG["candidates"] if e["pin_status"] == "resolved"}
        self.assertEqual({a["model"]["id"] for a in self.q}, resolved)
        self.assertEqual({a["model"]["id"] for a in self.p}, resolved)
        self.assertNotIn("ref-gliner-multi", {a["model"]["id"] for a in self.q})

    def test_artifact_digests_equal_pin_digests(self):
        pins = {e["id"]: e["model"]["artifact_digest"] for e in CFG["candidates"]}
        for a in self.q + self.p:
            self.assertEqual(a["model"]["artifact_digest"], pins[a["model"]["id"]])

    def test_single_corpus_single_run_single_environment(self):
        self.assertEqual({a["corpus"]["id"] for a in self.q}, {"ner-evidence-public"})
        self.assertEqual({a["source"]["ner_eval_run_id"] for a in self.q + self.p}, {CFG["source_run"]["ner_eval_run_id"]})
        self.assertEqual(len({a["environment"]["id"] for a in self.p}), 1)
        snap = next(p for p in REG["populations"] if p["id"] == "ner-evidence-public")["identity"]
        for a in self.q:
            self.assertEqual((a["corpus"]["digest"], a["corpus"]["case_count"]), (snap["snapshot_digest"], snap["case_count"]))

    def test_no_case_text_or_diagnostics_in_committed_artifacts(self):
        for f in BASE.rglob("*.json"):
            bad = set(walk(json.loads(f.read_text(encoding="utf-8")))) & FORBIDDEN_KEYS
            self.assertFalse(bad, f"{f.name}: {bad}")

    def test_committed_source_hashes_present(self):
        man = json.loads((BASE / "ingest-manifest.json").read_text())
        self.assertEqual(len(man["source_artifact_file_sha256"]), len(self.q) + len(self.p))
        self.assertEqual(man["ner_eval_run_id"], CFG["source_run"]["ner_eval_run_id"])

    def test_headline_numbers_match_ner_eval_report(self):
        """Values documented in ner-eval's committed README for this run (strict P/R/F1, lenient F1)."""
        q = {a["model"]["id"]: a["metrics"]["overall"] for a in self.q}
        crf = q["fastner-b-linear-crf"]
        self.assertEqual([round(crf["strict"][k], 3) for k in ("precision", "recall", "f1")], [0.733, 0.658, 0.694])
        self.assertEqual(round(crf["lenient"]["f1"], 3), 0.766)
        best = max((m for m in q if m.startswith("fastner-")), key=lambda m: q[m]["strict"]["f1"])
        self.assertEqual(best, "fastner-b-linear-crf")
        self.assertIsNone(q["control-null"]["strict"]["f1"])  # undefined stays None, never 0.0

    def test_sizes_and_wasm_come_from_role_tagged_artifacts(self):
        perf = {a["model"]["id"]: a["sizes"] for a in self.p}
        self.assertEqual(perf["fastner-b-linear-crf"], {"model_bytes": 590684, "binary_bytes": 563936, "wasm_bytes": 71680})
        self.assertIsNone(perf["ref-spacy-en"]["wasm_bytes"])  # references declare none: n/a, not zero
        self.assertEqual(len({perf[m]["binary_bytes"] for m in perf if m.startswith("fastner-")}), 1)  # shared shim

    @unittest.skipUnless(SOURCE.exists(), "sibling ner-eval checkout not available")
    def test_ingest_is_reproducible_from_source(self):
        files, _ = I.ingest(SOURCE)
        for rel, text in files.items():
            self.assertEqual((BASE / rel).read_text(encoding="utf-8"), text, rel)


# ---- ingest failure modes on a miniature synthetic ner-eval run ----
D = "sha256:"
PIN = next(e for e in CFG["candidates"] if e["id"] == "fastner-b-linear-crf")
SNAP = next(p for p in REG["populations"] if p["id"] == "ner-evidence-public")["identity"]
RUN = CFG["source_run"]["ner_eval_run_id"]


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
    return root, small


class IngestTests(unittest.TestCase):
    def run_ingest(self, mut=None):
        with tempfile.TemporaryDirectory() as d:
            root, small = mini_run(d, mut)
            return I.ingest(root, small, REG)

    def test_happy_path_normalizes_and_drops_diagnostics(self):
        files, man = self.run_ingest()
        q = json.loads(files["quality/fastner-b-linear-crf.json"])
        self.assertEqual(q["corpus"]["id"], "ner-evidence-public")
        self.assertEqual(q["metrics"]["slices"]["language=en"]["strict"]["f1"], 0.6)
        self.assertNotIn("SECRET", json.dumps(files))
        self.assertFalse(set(walk(q)) & FORBIDDEN_KEYS)
        p = json.loads(files["perf/fastner-b-linear-crf.json"])
        self.assertEqual(p["sizes"], {"model_bytes": PIN["model"]["size_bytes"], "binary_bytes": 10, "wasm_bytes": 5})
        self.assertEqual(man["ner_eval_run_id"], RUN)

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
        q = json.loads(files["quality/fastner-b-linear-crf.json"])
        self.assertEqual(q["status"], "unavailable")
        self.assertIn("pin-mismatch", q["reason"])
        self.assertNotIn("metrics", q)

    def test_resolved_pin_without_artifact_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root, small = mini_run(d)
            full = copy.deepcopy(CFG)
            with self.assertRaises(I.IngestError) as cm:
                I.ingest(root, full, REG)
            self.assertIn("resolved pins with no artifact", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
