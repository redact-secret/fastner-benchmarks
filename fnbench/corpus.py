"""Product-owned corpora: build, validate, isolate (issue #7).

Source of truth: corpora/<kind>/<kind>.src.jsonl, text with `[[surface]]` marking a PERSON span.
Generated: corpora/<kind>/<kind>.jsonl with UTF-8 byte offsets, derived and never hand-edited.
"""
import argparse
import json
import re
import unicodedata

from .util import ROOT, canonical_json, sha256_bytes, write_text

CORPORA = {
    "fastner-regression": {"dir": "corpora/regression", "stem": "regression", "prefix": "fnb-reg-"},
    "fastner-adversarial": {"dir": "corpora/adversarial", "stem": "adversarial", "prefix": "fnb-adv-"},
    "candidate-specific": {"dir": "corpora/candidate/fastner-b-linear-crf", "stem": "candidate", "prefix": "fnb-cand-b-"},
}
SLICE_KEYS = ["language", "script", "entity", "difficulty", "shape", "collision", "seen"]
ORIGINS = {"seed-taxonomy", "bakeoff-failure", "production-bug"}
SPAN_RE = re.compile(r"\[\[(.+?)\]\]", re.S)
# Safe-publication screen: nothing that looks like real contact data.
UNSAFE = [re.compile(p) for p in (r"[\w.+-]+@[\w-]+\.[\w.]+", r"https?://", r"\d{7,}", r"\+\d[\d\s-]{6,}")]


class CorpusError(ValueError):
    pass


def parse_markup(text):
    """Return (plain_text, [(start_byte, end_byte, surface)])."""
    plain, spans, last, nbytes = [], [], 0, 0
    for m in SPAN_RE.finditer(text):
        before = text[last:m.start()]
        plain.append(before)
        nbytes += len(before.encode("utf-8"))
        surface = m.group(1)
        b = len(surface.encode("utf-8"))
        spans.append((nbytes, nbytes + b, surface))
        plain.append(surface)
        nbytes += b
        last = m.end()
    plain.append(text[last:])
    return "".join(plain), spans


def build_case(src, corpus_id):
    plain, spans = parse_markup(src["text"])
    return {
        "id": src["id"], "corpus": corpus_id, "category": src["category"], "origin": src["origin"],
        "text": plain, "negative": not spans,
        "entities": [{"start": s, "end": e, "type": "PERSON", "surface": sf} for s, e, sf in spans],
        "slices": src["slices"], "rationale": src["rationale"],
        **{k: src[k] for k in ("seen_basis", "contested", "lineage") if k in src},
    }


def load_src(corpus_id, root=ROOT):
    c = CORPORA[corpus_id]
    path = root / c["dir"] / f"{c['stem']}.src.jsonl"
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def build(corpus_id, root=ROOT):
    rows = [build_case(s, corpus_id) for s in load_src(corpus_id, root)]
    validate_cases(corpus_id, rows)
    return "".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in rows)


def validate_cases(corpus_id, rows):
    prefix = CORPORA[corpus_id]["prefix"]
    errs, ids = [], set()
    for r in rows:
        i = r["id"]
        if not i.startswith(prefix):
            errs.append(f"{i}: id must start with {prefix} (corpus isolation from ner-evidence/other corpora)")
        if i in ids:
            errs.append(f"{i}: duplicate id")
        ids.add(i)
        if r["origin"] not in ORIGINS:
            errs.append(f"{i}: bad origin")
        if r["origin"] != "seed-taxonomy" and not r.get("lineage"):
            errs.append(f"{i}: non-seed origin needs lineage (run id / bug ref)")
        if not r.get("rationale"):
            errs.append(f"{i}: rationale required")
        if set(r["slices"]) != set(SLICE_KEYS):
            errs.append(f"{i}: slices must be exactly {SLICE_KEYS}")
        if r["slices"].get("seen") == "false" and not r.get("seen_basis"):
            errs.append(f"{i}: seen=false requires seen_basis")
        raw = r["text"].encode("utf-8")
        prev = 0
        for e in r["entities"]:
            if not (prev <= e["start"] < e["end"] <= len(raw)):
                errs.append(f"{i}: bad/overlapping span {e['start']}-{e['end']}")
                continue
            try:
                if raw[e["start"]:e["end"]].decode("utf-8") != e["surface"]:
                    errs.append(f"{i}: span surface mismatch")
            except UnicodeDecodeError:
                errs.append(f"{i}: span not on UTF-8 boundary")
            prev = e["end"]
        if r["negative"] == bool(r["entities"]):
            errs.append(f"{i}: negative flag inconsistent")
        for pat in UNSAFE:
            if pat.search(r["text"]):
                errs.append(f"{i}: text matches unsafe-publication pattern {pat.pattern!r}")
        if r["category"] == "unicode-homoglyph" and not any(ord(c) > 0x24f and c.isalpha() for c in r["text"]):
            errs.append(f"{i}: homoglyph case contains no non-Latin letter")
        if r["category"] == "unicode-normalization" and unicodedata.is_normalized("NFC", r["text"]) and not any("\uff00" <= ch <= "\uffef" for ch in r["text"]):
            errs.append(f"{i}: normalization case is already NFC")
    if errs:
        raise CorpusError("; ".join(errs))


def read_built(corpus_id, root=ROOT):
    c = CORPORA[corpus_id]
    path = root / c["dir"] / f"{c['stem']}.jsonl"
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def describe(corpus_id, root=ROOT):
    c = CORPORA[corpus_id]
    path = root / c["dir"] / f"{c['stem']}.jsonl"
    rows = read_built(corpus_id, root)
    origins = {}
    cats = {}
    for r in rows:
        origins[r["origin"]] = origins.get(r["origin"], 0) + 1
        cats[r["category"]] = cats.get(r["category"], 0) + 1
    return {"case_count": len(rows), "content_digest": sha256_bytes(path.read_bytes()),
            "origins": dict(sorted(origins.items())), "categories": dict(sorted(cats.items())),
            "negatives": sum(r["negative"] for r in rows)}


def main(argv):
    ap = argparse.ArgumentParser(prog="fnbench corpus")
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args(argv)
    bad = 0
    for cid, c in CORPORA.items():
        text = build(cid)
        path = ROOT / c["dir"] / f"{c['stem']}.jsonl"
        if a.check:
            if not path.exists() or path.read_text(encoding="utf-8") != text:
                print(f"{cid}: stale, run `python -m fnbench corpus`")
                bad += 1
            else:
                print(f"{cid}: ok ({text.count(chr(10))} cases)")
        else:
            write_text(path, text)
            print(f"{cid}: wrote {text.count(chr(10))} cases")
    return 1 if bad else 0
