"""Score the rule engine against every hand-labelled case:  python evaluate.py [rules|ollama|auto]"""
import glob
import json
import os
import sys

from amia.pipeline import analyze

HERE = os.path.dirname(os.path.abspath(__file__))


def evaluate_case(gold_path, engine="rules", model=None):
    with open(gold_path, encoding="utf-8") as f:
        gold = json.load(f)
    with open(os.path.join(HERE, "samples", gold["transcript"]), encoding="utf-8") as f:
        rep = analyze(f.read(), gold["meeting_date"], engine, model=model)
    got = {}
    for i in rep["items"]:
        if i["evidence"]:
            got[(i["type"], i["evidence"][0]["line"])] = i
    exp = {(e["type"], e["line"]): e for e in gold["expected"]}
    errors = []
    for k in set(got) & set(exp):
        g, e = got[k], exp[k]
        for f, v in (("owner", g["owner"]), ("status", g["status"]), ("due", g["due"]["iso"])):
            if f in e and e[f] != v:
                errors.append(f"{gold['transcript']} {k}: {f} expected {e[f]!r} got {v!r}")
    forbidden = [f for f in gold.get("must_not_extract", [])
                 if any(l == f["line"] and ("type" not in f or t == f["type"]) for (t, l) in got)]
    return {"name": gold["transcript"], "tp": sorted(set(got) & set(exp)), "missed": sorted(set(exp) - set(got)),
            "extra": sorted(set(got) - set(exp)), "field_errors": errors, "forbidden_hits": forbidden}


def evaluate_all(engine="rules", model=None):
    cases = [evaluate_case(p, engine, model) for p in sorted(glob.glob(os.path.join(HERE, "samples", "*_gold.json")))]
    per = {}
    for c in cases:
        for t, _ in c["tp"]:
            per.setdefault(t, [0, 0, 0])[0] += 1
        for t, _ in c["extra"]:
            per.setdefault(t, [0, 0, 0])[1] += 1
        for t, _ in c["missed"]:
            per.setdefault(t, [0, 0, 0])[2] += 1
    return cases, per


def clean(cases):
    return all(not (c["missed"] or c["extra"] or c["field_errors"] or c["forbidden_hits"]) for c in cases)


if __name__ == "__main__":
    cases, per = evaluate_all(sys.argv[1] if len(sys.argv) > 1 else "rules")
    for c in cases:
        print(f"\n{c['name']}: correct={len(c['tp'])} missed={len(c['missed'])} extra={len(c['extra'])} "
              f"field_errors={len(c['field_errors'])} forbidden={len(c['forbidden_hits'])}")
        for k in ("missed", "extra", "field_errors", "forbidden_hits"):
            for x in c[k]:
                print(f"   {k}: {x}")
    print("\n type        precision  recall   (tp/fp/fn)")
    T = [0, 0, 0]
    for t, (tp, fp, fn) in sorted(per.items()):
        T = [T[0] + tp, T[1] + fp, T[2] + fn]
        print(f" {t:<11} {tp / max(tp + fp, 1):>8.0%} {tp / max(tp + fn, 1):>8.0%}   ({tp}/{fp}/{fn})")
    print(f" {'ALL':<11} {T[0] / max(T[0] + T[1], 1):>8.0%} {T[0] / max(T[0] + T[2], 1):>8.0%}   ({T[0]}/{T[1]}/{T[2]})")
    sys.exit(0 if clean(cases) else 1)
