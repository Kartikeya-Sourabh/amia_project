"""Orchestration: parse -> propose (rules or local LLM) -> verify (code) -> report."""
from datetime import date

from . import patterns as P
from .dates import parse_one
from .extractors import ExtractorError, OllamaExtractor, RuleExtractor
from .transcript import parse
from .verifier import norm, verify

ENGINES = ("auto", "rules", "ollama")


def _ms_key(summary):
    m = P.MS_NOUN_RE.search(summary) or P.SHIP_RE.search(summary)
    return norm(m.group(0)).replace(" ", "") if m else None


def _flag(it, msg):
    it["flags"].append(msg)
    if it["status"] == "verified":
        it["status"] = "needs_review"


def _cross_checks(items, lines):
    """Look *across* lines: did a later line revise/cancel this item, supersede its date, or answer it?
    These never delete anything - they only add a human-review flag with the later line number."""
    pos = {l.n: i for i, l in enumerate(lines)}
    for it in items:
        if not it["evidence"] or it["status"] == "unsupported":
            continue
        last = max(pos[e["line"]] for e in it["evidence"])
        later = lines[last + 1:last + 13]
        t = it["type"]
        if t in ("action", "decision", "milestone"):
            st = P.toks(it["summary"])
            for l in later:
                if P.REVERSAL_RE.search(l.text) and len(st & P.toks(l.text)) >= 2:
                    _flag(it, f'May have been revised or cancelled later (L{l.n}: "{l.text[:80]}")')
                    break
        if t == "milestone":
            key = _ms_key(it["summary"])
            for o in items:
                if (key and o is not it and o["type"] == "milestone" and o["evidence"]
                        and o["evidence"][0]["line"] > it["evidence"][0]["line"] and _ms_key(o["summary"]) == key
                        and o["due"]["iso"] and it["due"]["iso"] and o["due"]["iso"] != it["due"]["iso"]):
                    _flag(it, f"A later line (L{o['evidence'][0]['line']}) gives a different date "
                              f"({o['due']['iso']}) for the same milestone - this one may be superseded")
                    break
        if t == "question":
            qt = P.toks(it["summary"])
            for l in later:
                if "?" not in l.text and len(qt & P.toks(l.text)) >= 2 and P.ANSWERISH_RE.search(l.text):
                    _flag(it, f"Possibly answered later at L{l.n} - please check")
                    break


def analyze(text, meeting_date=None, engine="auto", title="", extractor=None, model=None):
    lines = parse(text)
    if not lines:
        raise ValueError("Transcript is empty")
    ref = date.fromisoformat(parse_one(meeting_date) or date.today().isoformat()) if meeting_date else date.today()
    warnings, used = [], None
    if extractor is None:
        if engine not in ENGINES:
            raise ValueError(f"engine must be one of {ENGINES}")
        if engine == "rules":
            extractor = RuleExtractor()
        else:
            oll = OllamaExtractor(model=model)
            ok, msg = oll.available()
            if ok:
                extractor = oll
            elif engine == "ollama":
                raise ExtractorError(msg)
            else:
                warnings.append(f"{msg}. Using the built-in rule engine instead.")
                extractor = RuleExtractor()
    used = extractor.name
    model_used = getattr(extractor, "model", None)
    try:
        proposals = extractor.extract(lines, ref)
    except ExtractorError as e:
        if engine == "ollama":
            raise
        warnings.append(f"{e}. Fell back to the rule engine.")
        extractor, used, model_used = RuleExtractor(), "rules", None
        proposals = extractor.extract(lines, ref)

    items, seen = [], set()
    for p in proposals:
        it = verify(p, lines, ref)
        key = (it["type"], norm(p.get("quote", "")), it["evidence"][0]["line"] if it["evidence"] else None)
        if key in seen:
            continue
        seen.add(key)
        items.append(it)
    _cross_checks(items, lines)
    order = {t: i for i, t in enumerate(P.TYPES)}
    items.sort(key=lambda i: (i["evidence"][0]["line"] if i["evidence"] else 10 ** 9, order.get(i["type"], 9)))
    for n, it in enumerate(items, start=1):
        it["id"] = f"i{n}"

    stats = {"total": len(items), "verified": 0, "needs_review": 0, "unsupported": 0, "by_type": {}}
    for it in items:
        stats[it["status"]] += 1
        bt = stats["by_type"].setdefault(it["type"], {"total": 0, "verified": 0, "needs_review": 0, "unsupported": 0})
        bt["total"] += 1
        bt[it["status"]] += 1
    return {"title": title or "Untitled meeting", "meeting_date": ref.isoformat(), "engine_requested": engine,
            "engine_used": used, "model": model_used, "warnings": warnings,
            "participants": sorted({l.speaker for l in lines if l.speaker}),
            "lines": [l.to_dict() for l in lines], "items": items, "stats": stats}
