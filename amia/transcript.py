"""Transcript parsing. Every non-empty text row keeps its 1-based line number in the ORIGINAL file.
Supports: 'Name: text', '[00:10] Name: text', WebVTT/SRT (incl. <v Name>), and Teams/Zoom-style blocks
(a 'Name  0:05' header line followed by text lines)."""
import re
from dataclasses import dataclass, asdict

TS = r"\d{1,2}:\d{2}(?::\d{2})?"
_NAME = r"[A-Z][\w.'-]*(?: [A-Z][\w.'-]*){0,3}"
LINE_RE = re.compile(
    rf"^\s*(?:[\[(]?(?P<ts>{TS})[\])]?\s*[-\u2013]?\s*)?"
    rf"(?P<sp>[A-Z][\w.'-]*(?: [A-Z][\w.'-]*){{0,2}})\s*(?:[\[(](?P<ts2>{TS})[\])])?\s*:\s*(?P<text>\S.*)$")
HEADER_RE = re.compile(rf"^\s*(?:(?P<sp>{_NAME})\s+[\[(]?(?P<ts>{TS})[\])]?|[\[(]?(?P<ts2>{TS})[\])]?\s+(?P<sp2>{_NAME}))\s*$")
CUE_RE = re.compile(rf"^\s*(?P<ts>{TS})[.,]\d{{1,3}}\s*-->")
VOICE_RE = re.compile(r"^<v(?:\.[\w.]+)?\s+([^>]+)>(.*?)(?:</v>)?\s*$")
TAG_RE = re.compile(r"</?[^>]+>")
NOT_SPEAKERS = {"action", "decision", "note", "todo", "risk", "question", "agenda", "fyi", "context",
                "milestone", "summary", "decisions", "actions", "risks", "questions", "notes"}


@dataclass
class Line:
    n: int
    speaker: object
    ts: object
    text: str

    def to_dict(self):
        return asdict(self)


def parse(raw):
    rows = raw.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    if any(CUE_RE.match(r) for r in rows):
        return _cues(rows)
    if sum(1 for r in rows if HEADER_RE.match(r)) >= 2:
        return _blocks(rows)
    return _plain(rows)


def _split_speaker(text):
    m = LINE_RE.match(text)
    if m and m["sp"].lower() not in NOT_SPEAKERS:
        return m["sp"], (m["ts"] or m["ts2"]), m["text"].strip()
    return None, None, text.strip()


def _plain(rows):
    out = []
    for i, row in enumerate(rows, start=1):
        if row.strip():
            sp, ts, text = _split_speaker(row)
            out.append(Line(i, sp, ts, text))
    return out


def _cues(rows):
    out, ts = [], None
    for i, row in enumerate(rows, start=1):
        r = row.strip()
        c = CUE_RE.match(r)
        if c:
            ts = c["ts"]
            continue
        if not r or r.isdigit() or r.upper().startswith(("WEBVTT", "NOTE", "STYLE", "REGION")):
            continue
        v = VOICE_RE.match(r)
        if v:
            sp, text = v[1].strip(), TAG_RE.sub("", v[2]).strip()
        else:
            sp, _, text = _split_speaker(TAG_RE.sub("", r))
        if text:
            out.append(Line(i, sp, ts, text))
    return out


def _blocks(rows):
    out, sp, ts = [], None, None
    for i, row in enumerate(rows, start=1):
        if not row.strip():
            continue
        h = HEADER_RE.match(row)
        if h:
            sp, ts = h["sp"] or h["sp2"], h["ts"] or h["ts2"]
            continue
        out.append(Line(i, sp, ts, row.strip()))
    return out


def split_sentences(text):
    parts = re.split(r'(?<=[.!?])\s+(?=[A-Z"\'(\[])', text.strip())
    return [p.strip() for p in parts if p.strip()]
