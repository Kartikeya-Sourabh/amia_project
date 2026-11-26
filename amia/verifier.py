"""Stage 2 - VERIFY. Plain code, no AI. Every proposal must be found in the transcript, and every owner/date
must be supported by the evidence text, otherwise the item is flagged or marked unsupported."""
import re
from difflib import SequenceMatcher

from . import patterns as P
from .dates import find_dates
from .patterns import clean, norm  # noqa: F401  (norm is re-exported for the pipeline)

_fix = clean


def locate(quote, lines, hint=None):
    """Find which transcript line(s) contain the quote. Returns (list_of_line_indexes, score, ambiguous)."""
    nq = norm(quote)
    if not nq:
        return [], 0.0, False
    exact = [(1.0, [i]) for i, l in enumerate(lines) if f" {nq} " in f" {norm(l.text)} "]
    if not exact:
        exact = [(1.0, [i, i + 1]) for i in range(len(lines) - 1)
                 if f" {nq} " in f" {norm(lines[i].text + ' ' + lines[i + 1].text)} "]
    cands = exact
    if not cands:
        qt = nq.split()
        for i, l in enumerate(lines):
            lt = norm(l.text).split()
            if not lt:
                continue
            sm = SequenceMatcher(None, qt, lt, autojunk=False)
            matched = sum(b.size for b in sm.get_matching_blocks()) / len(qt)
            longest = sm.find_longest_match(0, len(qt), 0, len(lt)).size / len(qt)
            if matched >= 0.85 and longest >= 0.6:
                cands.append((round(min(matched, 0.99), 2), [i]))
    if not cands:
        return [], 0.0, False
    best = max(c[0] for c in cands)
    top = [c for c in cands if c[0] == best]
    pick = next((c for c in top if hint is not None and lines[c[1][0]].n == hint), top[0])
    return pick[1], pick[0], len(top) > 1 and not any(lines[c[1][0]].n == hint for c in top)


def _ev(lines, idxs, role, score):
    return [{"line": lines[i].n, "speaker": lines[i].speaker, "ts": lines[i].ts, "text": lines[i].text,
             "role": role, "match": score} for i in idxs]


def _check_owner(owner, primary, confirm):
    text = _fix(" ".join(l.text for l in primary))
    for part in [p.strip() for p in re.split(r",| and |&", owner) if p.strip()]:
        named = re.search(rf"\b{re.escape(part)}\b", text, re.I)
        first_person = any((l.speaker or "").lower() == part.lower() and P.FIRST_PERSON_RE.search(_fix(l.text))
                           for l in primary)
        confirmed = any((l.speaker or "").lower() == part.lower() for l in confirm)
        if not (named or first_person or confirmed):
            return False
    return True


def _check_due(p, ev_text, ref, required, label, flags, fallback=""):
    found = find_dates(ev_text, ref)
    if not found and fallback:
        found, ev_text = find_dates(fallback, ref), fallback
    raw = p.get("due_raw")
    due = {"raw": None, "iso": None, "precise": False}
    chosen = None
    if raw:
        cands = [d for d in found if norm(raw) in norm(d["raw"]) or norm(d["raw"]) in norm(raw)]
        if cands:
            chosen = cands[0]
        elif norm(raw) in norm(ev_text):
            due["raw"] = raw
            flags.append(f"{label} '{raw}' could not be resolved to a calendar date")
            return due
        else:
            flags.append(f"Proposed {label.lower()} '{raw}' does not appear in the evidence line - ignored")
    if chosen is None and found:
        chosen = found[0]
        if len(found) > 1:
            flags.append("Evidence contains several dates; first one used - please confirm")
    if chosen:
        due = {"raw": chosen["raw"], "iso": chosen["iso"], "precise": chosen["precise"]}
        if not chosen["precise"]:
            flags.append(f"{label} '{chosen['raw']}' is vague or ambiguous ({chosen['note'] or 'not a fixed date'})")
    elif required:
        flags.append(f"No {label.lower()} stated in the evidence")
    return due


def verify(p, lines, ref):
    flags = []
    t = p.get("type")
    base = {"type": t, "summary": p.get("summary") or p.get("quote", ""), "owner": None,
            "due": {"raw": None, "iso": None, "precise": False}, "evidence": [], "flags": flags,
            "engine": p.get("source", "?"), "proposed_owner": p.get("owner"), "proposed_due": p.get("due_raw")}
    if t not in P.TYPES:
        flags.append(f"Unknown item type '{t}'")
        return {**base, "status": "unsupported"}
    idxs, score, ambiguous = locate(p.get("quote", ""), lines, p.get("line"))
    if not idxs:
        flags.append("No transcript line contains this evidence - the claim is not backed by the source")
        return {**base, "status": "unsupported"}
    ev = _ev(lines, idxs, "primary", score)
    primary = [lines[i] for i in idxs]
    confirm = []
    if p.get("confirm_quote"):
        cidx, cscore, _ = locate(p["confirm_quote"], lines, None)
        near = [i for i in cidx if min(abs(i - j) for j in idxs) <= 4]
        if near:
            confirm = [lines[i] for i in near]
            ev += _ev(lines, near, "supporting", cscore)
        else:
            flags.append("Supporting line (answer/agreement) not found near the evidence")
    if p.get("note"):
        flags.append(p["note"])
    if score < 1:
        flags.append(f"Evidence matched only approximately ({int(score * 100)}%)")
    if ambiguous:
        flags.append("Quote appears on several lines; the first match was used")

    text = _fix(" ".join(l.text for l in primary))
    allt = _fix(" ".join(l.text for l in primary + confirm))
    owner = p.get("owner")
    if t == "action":
        if not owner or str(owner).strip().lower() in P.GENERIC_OWNERS:
            flags.append("No named owner in the transcript (assigned to 'we' / nobody)")
            owner = None
        elif not _check_owner(str(owner).strip(), primary, confirm):
            flags.append(f"Owner '{owner}' is not supported by the evidence line - possible guess")
            base["owner"] = None
            owner = None
        if P.HEDGE_RE.search(text):
            flags.append("Tentative wording (should/maybe/could/try to) - may not be a firm commitment")
        base["due"] = _check_due(p, text, ref, True, "Deadline", flags,
                                 fallback=_fix(" ".join(l.text for l in confirm)))
        base["owner"] = str(owner).strip() if owner else None
    elif t == "decision":
        if not (P.DECISION_RE.search(allt) or any(P.AGREE_RE.match(l.text) for l in confirm)):
            flags.append("No decision wording (decided/agreed/go with) - may be only a suggestion")
        if P.DEC_HEDGE_RE.search(text) and not confirm:
            flags.append("Hedged wording - may be a suggestion rather than a decision")
    elif t == "question":
        if "?" not in text and not P.OPEN_RE.search(text) and not P.INTERROG_RE.match(text):
            flags.append("Evidence is not phrased as a question or open issue")
    elif t == "risk":
        if not P.RISK_RE.search(text):
            flags.append("No risk wording (risk/blocker/worried/dependency) in the evidence")
    elif t == "milestone":
        base["due"] = _check_due(p, text, ref, True, "Target date", flags)
    return {**base, "evidence": ev, "status": "needs_review" if flags else "verified"}
