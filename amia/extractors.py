"""Stage 1 - PROPOSE. Extractors only *suggest* items. Nothing here is trusted; the verifier checks everything.

A proposal is a dict: type, summary, owner, due_raw, quote (verbatim text from the transcript),
confirm_quote (optional second line that supports it), line (optional hint), note (optional uncertainty)."""
import json
import os
import re
import urllib.request
from datetime import date, timedelta

from . import patterns as P
from .dates import find_dates
from .patterns import clean
from .transcript import split_sentences


def _prop(type_, summary, quote, line, owner=None, due_raw=None, confirm_quote=None, note=None, source="rules"):
    return {"type": type_, "summary": summary, "owner": owner, "due_raw": due_raw, "quote": quote,
            "confirm_quote": confirm_quote, "line": line, "note": note, "source": source}


def _first_sentence(text):
    s = split_sentences(text)
    return s[0] if s else text


class RuleExtractor:
    """Offline, deterministic, no model needed. Also the fallback when no local LLM is running.
    Classification order per sentence: suggestion+agreement -> question/request -> open issue -> decision ->
    action -> milestone -> risk -> context. The first match wins; decisions may also yield a milestone."""
    name = "rules"

    def extract(self, lines, ref):
        self.lines, self.ref = lines, ref
        self.participants = set()
        for l in lines:
            if l.speaker:
                self.participants.add(l.speaker)
                self.participants.add(l.speaker.split()[0])
        self.by_lower = {p.lower(): p for p in self.participants}
        out = []
        for idx, ln in enumerate(lines):
            sents = split_sentences(ln.text)
            for k, sent in enumerate(sents):
                out.extend(self._sentence(idx, ln, sent, sents[k + 1:]))
        return out

    # ---------- small helpers
    def _cap_name(self, s):
        m = re.match(r"([A-Za-z]+)(.*)", s)
        if m and m[1][0].islower() and m[1].lower() in self.by_lower:
            return self.by_lower[m[1].lower()] + m[2]
        return s

    def _due(self, s):
        d = find_dates(s, self.ref)
        return d[0]["raw"] if d else None

    def _reply(self, idx, ln):
        for j in range(idx + 1, min(idx + 4, len(self.lines))):
            nxt = self.lines[j]
            if not nxt.speaker or not ln.speaker or nxt.speaker != ln.speaker:
                return nxt
        return None

    def _prev_text(self, idx, ln):
        for j in (idx - 1, idx - 2):
            if j >= 0 and (not self.lines[j].speaker or self.lines[j].speaker != ln.speaker):
                t = self.lines[j].text
                return t if len(t) <= 240 else _first_sentence(t)
        return None

    def _agreement(self, idx, ln):
        for j in range(idx + 1, min(idx + 3, len(self.lines))):
            nxt = self.lines[j]
            if nxt.speaker and ln.speaker and nxt.speaker == ln.speaker:
                continue
            if P.AGREE_RE.match(clean(nxt.text)) and not P.FIRST_PERSON_RE.search(clean(nxt.text)):
                return _first_sentence(nxt.text)
            return None
        return None

    def _looks_answered(self, q, reply):
        r = clean(reply)
        first = _first_sentence(r)
        if len(first.split()) <= 4 and not first.endswith("?"):
            return True
        return bool(P.ANSWER_START_RE.match(r) or P.FIRST_PERSON_RE.search(r)
                    or (P.toks(q) & P.toks(r)))

    # ---------- main classifier
    def _sentence(self, idx, ln, sent, rest):
        orig = sent.strip()
        s = self._cap_name(clean(orig))
        if len(s.split()) < 3:
            return []
        explicit = bool(P.EXPLICIT_RE.match(s))
        body = P.EXPLICIT_RE.sub("", s) if explicit else s
        t = P.LEAD_IN_RE.sub("", body).strip()

        if P.SUGGEST_RE.search(s) and len(s.split()) >= 6 and not P.SMALLTALK_RE.match(s):
            conf = self._agreement(idx, ln)
            if conf:
                return [_prop("decision", orig, orig, ln.n, confirm_quote=conf)] + \
                    self._milestone(s, orig, ln, conf, relaxed=True)
        if (s.endswith("?") or (P.INTERROG_RE.match(t) and len(t.split()) >= 4 and not P.DECISION_RE.search(t))
                or P.REQUEST_RE.search(t)):
            return self._question(idx, ln, orig, t, rest)
        if P.OPEN_RE.search(s):
            return [_prop("question", orig, orig, ln.n)]
        dm = P.DECISION_RE.search(s)
        if dm and not P.DEC_HEDGE_RE.search(s) and not (
                dm.group(0).lower() in ("approved", "signed off") and P.PASTTIME_RE.search(s)):
            return [_prop("decision", orig, orig, ln.n)] + self._milestone(s, orig, ln, relaxed=True)
        act = self._action(idx, ln, orig, s, t, explicit)
        if act:
            return act
        ms = self._milestone(s, orig, ln)
        if ms:
            return ms
        if P.RISK_RE.search(s):
            return [_prop("risk", orig, orig, ln.n)]
        if P.CONTEXT_RE.search(s) and not P.AFFIRM_RE.match(s):
            return [_prop("context", orig, orig, ln.n)]
        return []

    def _question(self, idx, ln, orig, t, rest):
        if P.SMALLTALK_RE.match(t):
            return []
        if rest:
            nxt = clean(rest[0])
            if not nxt.endswith("?") and not P.UNSURE_RE.search(nxt):
                return []                       # answered in the same breath
        reply = self._reply(idx, ln)
        req = P.REQUEST_RE.search(t)
        if req and reply and P.AFFIRM_RE.match(clean(reply.text)):
            owner = reply.speaker or req["addr"]
            what = req["what"].rstrip("?").strip()
            return [_prop("action", f"{owner or 'Someone'}: {what}", orig, ln.n, owner=owner,
                          due_raw=self._due(t), confirm_quote=_first_sentence(reply.text))]
        if reply is None:
            return [_prop("question", orig, orig, ln.n)]
        if P.UNSURE_RE.search(clean(reply.text)):
            return [_prop("question", orig, orig, ln.n, confirm_quote=_first_sentence(reply.text))]
        if not self._looks_answered(t, reply.text):
            return [_prop("question", orig, orig, ln.n, confirm_quote=_first_sentence(reply.text),
                          note="The next reply does not clearly answer this question")]
        return []

    def _action(self, idx, ln, orig, s, t, explicit):
        m = P.IMPERATIVE_RE.match(t)
        if m and m["addr"] in self.participants:
            return [_prop("action", orig, orig, ln.n, owner=m["addr"], due_raw=self._due(s))]
        m = P.LETME_RE.match(t)
        if m and not m["what"].lower().startswith(("know", "me")):
            ref = P.REFERENTIAL_RE.match(m["what"])
            return [_prop("action", orig, orig, ln.n, owner=ln.speaker, due_raw=self._due(s),
                          confirm_quote=self._prev_text(idx, ln) if ref else None)]
        pron = True
        m = P.ACTION_PRON_RE.match(t)
        if not m:
            pron = False
            m = P.ACTION_NAME_RE.match(t)
            if m and re.split(r"[,\s]+", m["who"])[0] in P.STOP_WHO:
                m = None
        if not m:
            return []
        who, verb, what = m["who"], m["verb"].strip(), m["what"]
        if what.lower().startswith(("be ", "also be ")):
            return []
        names = [n.strip() for n in re.split(r",\s*and\s+|,\s*|\s+and\s+", who)]
        if pron and verb == "to":
            return []
        if verb.startswith("own") and (pron or not (find_dates(s, self.ref) or re.search(r"\bwill\b|'ll", s))):
            return []                           # 'X owns Y' only counts when a commitment/date comes with it
        if not pron:
            if any(" " in n for n in names) and not any(p in self.participants for n in names for p in n.split()):
                return []                       # e.g. "Project Falcon will ..." is not a person
            if verb in ("to", "should") and not explicit and not any(n in self.participants for n in names):
                return []
        referential = bool(P.REFERENTIAL_RE.match(what))
        if pron and who.lower() == "we" and referential:
            return []                           # "we'll get that done" just confirms an earlier assignment
        owner = ln.speaker if (pron and who.lower() == "i") else (None if pron else who)
        return [_prop("action", orig, orig, ln.n, owner=owner, due_raw=self._due(s),
                      confirm_quote=self._prev_text(idx, ln) if referential else None)]

    def _milestone(self, s, orig, ln, confirm=None, relaxed=False):
        if not (P.MS_NOUN_RE.search(s) or P.SHIP_RE.search(s)):
            return []
        dates = find_dates(s, self.ref)
        if not dates and "milestone" not in s.lower():
            return []
        moved = P.MOVE_RE.search(s)
        dated = relaxed and any(re.search(r"\b(?:on|by|for|until|to|before)\s+(?:the\s+)?$", s[:d["start"]])
                                for d in dates)
        if not (P.MS_FRAME_RE.search(s) or moved or P.SHIP_RE.search(s) or dated):
            return []
        if P.PAST_RE.search(s) and not moved:
            return []
        first = dates[0]["iso"] if dates else None
        if first and not moved and "milestone" not in s.lower() and \
                date.fromisoformat(first) < self.ref - timedelta(days=7):
            return []                           # a date that is already in the past is history, not a target
        due = (dates[-1] if moved else dates[0])["raw"] if dates else None
        return [_prop("milestone", orig, orig, ln.n, due_raw=due, confirm_quote=confirm)]


class ExtractorError(Exception):
    pass


class OllamaExtractor:
    """Optional local LLM via Ollama (http://127.0.0.1:11434). Runs on your machine; no cloud calls."""
    name = "ollama"
    SYSTEM = ("You extract structured items from meeting transcripts. Output ONLY JSON: "
              '{"items":[{"type":"action|decision|question|risk|milestone|context","summary":"short",'
              '"owner":"person name or null","due":"date wording exactly as spoken or null",'
              '"quote":"EXACT words copied from ONE transcript line","line":<line number>}]}. '
              "Rules: never invent owners or dates; use null when not stated. 'decision' only when something was "
              "actually decided, not merely suggested. 'question' only when it was left unanswered. "
              "'action' needs a clear commitment. 'quote' must be copied verbatim.")

    def __init__(self, host=None, model=None, timeout=None):
        self.host = (host or os.environ.get("AMIA_OLLAMA_HOST", "http://127.0.0.1:11434")).rstrip("/")
        self.model = model or os.environ.get("AMIA_MODEL", "qwen2.5:7b")
        self.timeout = timeout or int(os.environ.get("AMIA_TIMEOUT", "300"))

    def installed(self):
        """Names of models installed in Ollama, or None if Ollama is not reachable."""
        try:
            with urllib.request.urlopen(self.host + "/api/tags", timeout=1.5) as r:
                return [m.get("name", "") for m in json.load(r).get("models", [])]
        except Exception:
            return None

    def available(self):
        names = self.installed()
        if names is None:
            return False, f"Ollama not reachable at {self.host}"
        if not any(n == self.model or (":" not in self.model and n.split(":")[0] == self.model) for n in names):
            return False, f"Model '{self.model}' not pulled (run: ollama pull {self.model})"
        return True, "ok"

    def _chat(self, text):
        body = json.dumps({"model": self.model, "stream": False, "format": "json", "options": {"temperature": 0},
                           "messages": [{"role": "system", "content": self.SYSTEM},
                                        {"role": "user", "content": text}]}).encode()
        req = urllib.request.Request(self.host + "/api/chat", body, {"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                return json.load(r)["message"]["content"]
        except Exception as e:
            raise ExtractorError(f"Ollama request failed: {e}")

    def extract(self, lines, ref, chunk=None, overlap=10):
        chunk = chunk or int(os.environ.get("AMIA_CHUNK", "100"))
        out, start = [], 0
        while start < len(lines):
            part = lines[start:start + chunk]
            text = "\n".join(f"L{l.n} [{l.speaker or '?'}]: {l.text}" for l in part)
            try:
                data = json.loads(self._chat(f"Meeting date: {ref.isoformat()}\nTranscript:\n{text}"))
            except json.JSONDecodeError:
                raise ExtractorError("Model returned invalid JSON")
            for it in data.get("items", []) if isinstance(data, dict) else []:
                if not isinstance(it, dict) or not it.get("quote"):
                    continue
                ln = it.get("line")
                out.append({"type": str(it.get("type", "")).lower(), "summary": str(it.get("summary") or it["quote"]),
                            "owner": it.get("owner") or None, "due_raw": it.get("due") or None,
                            "quote": str(it["quote"]), "confirm_quote": None,
                            "line": ln if isinstance(ln, int) else None, "source": "ollama"})
            if start + chunk >= len(lines):
                break
            start += chunk - overlap
        return out
