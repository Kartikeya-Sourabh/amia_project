"""Deterministic date finder. Resolves wording like '18 November' or 'by Friday' against the meeting date.
Vague wording ('next week', 'soon') is reported as NOT precise so it can be flagged, never guessed."""
import re
from datetime import date, timedelta

MONTHS = {"january": 1, "jan": 1, "february": 2, "feb": 2, "march": 3, "mar": 3, "april": 4, "apr": 4, "may": 5,
          "june": 6, "jun": 6, "july": 7, "jul": 7, "august": 8, "aug": 8, "september": 9, "sept": 9, "sep": 9,
          "october": 10, "oct": 10, "november": 11, "nov": 11, "december": 12, "dec": 12}
WEEKDAYS = {"monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3, "friday": 4, "saturday": 5, "sunday": 6}
_M = "|".join(sorted(MONTHS, key=len, reverse=True))
_W = "|".join(WEEKDAYS)
I = re.I
P_ISO = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
P_DMY = re.compile(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?[\s-]+(?:of\s+)?({_M})\b(?:,?\s+(\d{{4}}))?", I)
P_ORD = re.compile(r"\b(?:by|on|before|until|till|due|from|to)\s+(?:the\s+)?(?P<n>(\d{1,2})(?:st|nd|rd|th))\b", I)
P_DAT = re.compile(r"\b(?:the )?day after tomorrow\b", I)
P_MDY = re.compile(rf"\b({_M})\b\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?\b(?:,?\s+(\d{{4}}))?", I)
P_NUM = re.compile(r"\b(?:by|on|before|until|till|due|from)\s+(?P<n>(\d{1,2})[/-](\d{1,2})(?:[/-](\d{2,4}))?)\b", I)
P_NEXTWD = re.compile(rf"\bnext\s+({_W})\b", I)
P_WD = re.compile(rf"\b(?:(this|coming)\s+)?({_W})\b", I)
P_REL = re.compile(r"\b(today|tomorrow|tonight)\b", I)
P_END = re.compile(r"\b(eod|cob|end of (?:the )?day|eow|end of (?:the )?week|eom|end of (?:the )?month)\b", I)
P_IN = re.compile(r"\bin (\d{1,2}) (day|days|week|weeks)\b", I)
P_VAGUE = re.compile(r"\b(next week|this week|next month|this month|next quarter|end of (?:the )?quarter|end of (?:the )?year|"
                     r"next year|asap|soon|shortly|at some point|eventually|sometime|in a few days|in a couple of days|"
                     r"next sprint|this sprint|later this (?:week|month|year)|q[1-4]|"
                     rf"mid[- ](?:{_M}|month|year|quarter|week))\b", I)


def _mk(y, m, d):
    try:
        return date(y, m, d)
    except ValueError:
        return None


def _infer_year(m, d, ref):
    c = _mk(ref.year, m, d)
    if c and c < ref - timedelta(days=60):
        c = _mk(ref.year + 1, m, d)
    return c


def find_dates(text, ref):
    """Return [{raw, iso, precise, note, start, end}] in text order."""
    found, used = [], []

    def free(s, e):
        return all(e <= a or s >= b for a, b in used)

    def add(s, e, d, precise=True, note=""):
        if not free(s, e):
            return
        used.append((s, e))
        found.append({"raw": text[s:e], "iso": d.isoformat() if (d and precise) else None,
                      "precise": bool(d and precise), "note": note, "start": s, "end": e, "_d": d})

    for m in P_ISO.finditer(text):
        add(m.start(), m.end(), _mk(int(m[1]), int(m[2]), int(m[3])))
    for m in P_DMY.finditer(text):
        mon, day = MONTHS[m[2].lower()], int(m[1])
        d = _mk(int(m[3]), mon, day) if m[3] else _infer_year(mon, day, ref)
        add(m.start(), m.end(), d, note="" if d else "invalid date")
    for m in P_MDY.finditer(text):
        mon, day = MONTHS[m[1].lower()], int(m[2])
        d = _mk(int(m[3]), mon, day) if m[3] else _infer_year(mon, day, ref)
        add(m.start(), m.end(), d, note="" if d else "invalid date")
    for m in P_ORD.finditer(text):
        day = int(m[2])
        prev = [f for f in found if f["end"] <= m.start() and f["_d"]]
        if prev:
            d, note = _mk(prev[-1]["_d"].year, prev[-1]["_d"].month, day), "month taken from the earlier date"
        else:
            d, note = _mk(ref.year, ref.month, day), "month inferred from the meeting date"
            if d is None or d < ref:
                d = _mk(ref.year + (ref.month == 12), ref.month % 12 + 1, day)
        add(m.start("n"), m.end("n"), d, note="" if d else "invalid date")
    for m in P_DAT.finditer(text):
        add(m.start(), m.end(), ref + timedelta(days=2))
    for m in P_NUM.finditer(text):
        a, b = int(m[2]), int(m[3])
        yr = m[4]
        year = (2000 + int(yr) if len(yr) == 2 else int(yr)) if yr else None
        day, mon = a, b                     # day-first by default (dd/mm)
        ambiguous = a <= 12 and b <= 12 and a != b
        if b > 12 and a <= 12:              # clearly mm/dd
            day, mon, ambiguous = b, a, False
        d = _mk(year, mon, day) if year else _infer_year(mon, day, ref)
        add(m.start("n"), m.end("n"), d, precise=not ambiguous,
            note="ambiguous day/month order" if ambiguous else "")
    for m in P_NEXTWD.finditer(text):
        next_monday = ref - timedelta(days=ref.weekday()) + timedelta(days=7)
        add(m.start(), m.end(), next_monday + timedelta(days=WEEKDAYS[m[1].lower()]))
    for m in P_IN.finditer(text):
        n = int(m[1]) * (7 if m[2].lower().startswith("week") else 1)
        add(m.start(), m.end(), ref + timedelta(days=n))
    for m in P_VAGUE.finditer(text):
        add(m.start(), m.end(), None, note="vague timeframe")
    for m in P_WD.finditer(text):
        delta = (WEEKDAYS[m[2].lower()] - ref.weekday()) % 7
        add(m.start(), m.end(), ref + timedelta(days=delta), precise=delta != 0,
            note="same weekday as the meeting; unclear whether today or next week" if delta == 0 else "")
    for m in P_REL.finditer(text):
        add(m.start(), m.end(), ref + timedelta(days=1 if m[1].lower() == "tomorrow" else 0))
    for m in P_END.finditer(text):
        k = m[1].lower()
        if k in ("eod", "cob") or "day" in k:
            d = ref
        elif k == "eow" or "week" in k:
            d = ref + timedelta(days=(4 - ref.weekday()) % 7)
        else:
            d = _mk(ref.year + (ref.month == 12), ref.month % 12 + 1, 1) - timedelta(days=1)
        add(m.start(), m.end(), d)
    for f in found:
        f.pop("_d", None)
    return sorted(found, key=lambda x: x["start"])


def parse_one(s, ref=None):
    """Parse a user-supplied single date (meeting date or a correction). Returns ISO string or None."""
    if not s:
        return None
    ref = ref or date.today()
    for d in find_dates(s.strip(), ref):
        if d["precise"]:
            return d["iso"]
    return None
