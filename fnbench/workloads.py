"""Reproducible performance workloads (issue #7).

Documents are generated from (spec, seed) with a self-contained PRNG, so every machine
produces identical bytes. Only specs and content digests are committed, not text.
"""
import argparse
import json

from .util import ROOT, canonical_json, sha256_bytes, write_text

SRC = ROOT / "corpora" / "performance" / "workloads.src.json"
OUT = ROOT / "corpora" / "performance" / "workloads.json"

EN_NAMES = ["Corwin Aldous", "Bryony Haldane", "Orla Pennywhistle", "Idris Valcourt", "Tamsin Vargholt", "Zephyrine Lindqvist", "Quillon Marsh", "Mireille Tavernier"]
KO_NAMES = ["김민수", "이서연", "박지훈", "최유진", "강도윤", "윤서아", "한지우", "정하늘"]
EN_FILL = ["The report was reviewed on Monday.", "Please send the summary before noon.", "We walked through Central Park after lunch.", "The schedule changed again this week.", "Funding was approved by the committee.", "Young people prefer short videos."]
KO_FILL = ["보고서는 월요일에 검토되었다.", "점심 전에 요약본을 보내 주세요.", "도시가 빠르게 커졌다.", "이번 주 일정이 또 바뀌었다.", "위원회에서 예산을 승인했다.", "강아지가 마당에서 짖었다."]
EN_NAME_T = ["{n} approved the plan.", "I asked {n} about it.", "Thanks, {n}!"]
KO_NAME_T = ["{n}가 회의에 참석했다.", "{n}에게 전달되었다.", "{n}의 보고서가 늦었다."]


class Rng:
    """xorshift64*: deterministic, no dependency on the Python random implementation."""

    def __init__(self, seed):
        self.s = (seed * 0x9E3779B97F4A7C15 + 1) & 0xFFFFFFFFFFFFFFFF or 1

    def next(self):
        x = self.s
        x ^= x >> 12
        x ^= (x << 25) & 0xFFFFFFFFFFFFFFFF
        x ^= x >> 27
        self.s = x
        return (x * 0x2545F4914F6CDD1D) & 0xFFFFFFFFFFFFFFFF

    def below(self, n):
        return (self.next() >> 11) % n

    def between(self, lo, hi):
        return lo + self.below(hi - lo + 1)

    def chance(self, p):
        return (self.next() >> 11) / float(1 << 53) < p


def generate(spec):
    rng = Rng(spec["seed"])
    docs = []
    for _ in range(spec["doc_count"]):
        if spec["language"] == "pathological":
            docs.append("x" * spec["token_chars"])
            continue
        sents = []
        for _ in range(rng.between(*spec["sentences"])):
            lang = spec["language"] if spec["language"] != "mixed" else ("en", "ko")[rng.below(2)]
            names, fill, tmpl = (EN_NAMES, EN_FILL, EN_NAME_T) if lang == "en" else (KO_NAMES, KO_FILL, KO_NAME_T)
            if rng.chance(spec["name_rate"]):
                sents.append(tmpl[rng.below(len(tmpl))].format(n=names[rng.below(len(names))]))
            else:
                sents.append(fill[rng.below(len(fill))])
        docs.append(" ".join(sents))
    return docs


def digest(docs):
    return sha256_bytes("\n".join(docs).encode("utf-8"))


def build():
    src = json.loads(SRC.read_text(encoding="utf-8"))
    out = {"schema": "fastner-benchmarks.workloads/1", "workload_set_version": src["workload_set_version"],
           "generator": src["generator"], "workloads": []}
    for w in src["workloads"]:
        docs = generate(w)
        out["workloads"].append({**w, "total_chars": sum(len(d) for d in docs), "total_bytes": sum(len(d.encode()) for d in docs),
                                 "content_digest": digest(docs)})
    return canonical_json(out)


def main(argv):
    ap = argparse.ArgumentParser(prog="fnbench workloads")
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args(argv)
    text = build()
    if a.check:
        ok = OUT.exists() and OUT.read_text(encoding="utf-8") == text
        print("workloads up to date" if ok else "workloads stale: run `python -m fnbench workloads`")
        return 0 if ok else 1
    write_text(OUT, text)
    print(f"wrote {OUT}")
    return 0
