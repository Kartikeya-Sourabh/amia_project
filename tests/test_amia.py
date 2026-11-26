import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from datetime import date
from http.server import ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from amia.dates import find_dates  # noqa: E402
from amia.pipeline import analyze  # noqa: E402
from amia.server import make_handler  # noqa: E402
from amia.store import Store, ValidationError  # noqa: E402
from amia.transcript import parse  # noqa: E402
from amia.verifier import locate, verify  # noqa: E402
import evaluate  # noqa: E402

REF = date(2026, 11, 17)  # a Tuesday
SAMPLE = open(os.path.join(os.path.dirname(__file__), "..", "samples", "sample_meeting.txt"), encoding="utf-8").read()


def iso(text):
    return [(d["iso"], d["precise"]) for d in find_dates(text, REF)]


class Dates(unittest.TestCase):
    def test_explicit(self):
        self.assertEqual(iso("by 18 November"), [("2026-11-18", True)])
        self.assertEqual(iso("on November 3rd"), [("2026-11-03", True)])
        self.assertEqual(iso("2026-12-01"), [("2026-12-01", True)])

    def test_year_rollover(self):
        self.assertEqual(find_dates("5 January", date(2026, 12, 20))[0]["iso"], "2027-01-05")

    def test_weekdays(self):
        self.assertEqual(iso("by Friday"), [("2026-11-20", True)])
        self.assertEqual(iso("next Friday"), [("2026-11-27", True)])
        self.assertEqual(iso("by Tuesday")[0][1], False)  # same weekday -> ambiguous

    def test_vague_never_guessed(self):
        for w in ("next week", "soon", "ASAP", "at some point"):
            self.assertEqual(iso(w), [(None, False)], w)

    def test_numeric(self):
        self.assertEqual(iso("by 25/12"), [("2026-12-25", True)])
        self.assertEqual(iso("by 03/04")[0], (None, False))  # ambiguous order
        self.assertEqual(iso("by 31/02")[0][0], None)        # invalid date

    def test_eod(self):
        self.assertEqual(iso("by EOD"), [("2026-11-17", True)])


class Parsing(unittest.TestCase):
    def test_formats(self):
        ls = parse("[00:10] Ravi: hi\nPriya (00:12): yo\n\n00:20 Sam Lee: ok\nAction item: Ravi to ship")
        self.assertEqual([(l.n, l.speaker) for l in ls], [(1, "Ravi"), (2, "Priya"), (4, "Sam Lee"), (5, None)])


class Verifier(unittest.TestCase):
    def setUp(self):
        self.lines = parse(SAMPLE)

    def test_fabricated_item_is_unsupported(self):
        p = {"type": "action", "summary": "x", "owner": "Priya", "due_raw": "Friday",
             "quote": "Priya will approve the budget by Friday", "line": None}
        self.assertEqual(verify(p, self.lines, REF)["status"], "unsupported")

    def test_guessed_owner_is_flagged(self):
        p = {"type": "action", "summary": "x", "owner": "Sam", "due_raw": "18 November",
             "quote": "I'll finish the API integration by 18 November.", "line": 4}
        r = verify(p, self.lines, REF)
        self.assertEqual(r["status"], "needs_review")
        self.assertIsNone(r["owner"])
        self.assertTrue(any("not supported" in f for f in r["flags"]))

    def test_invented_date_is_dropped(self):
        p = {"type": "action", "summary": "x", "owner": "Priya", "due_raw": "30 November",
             "quote": "Sam to schedule the security review kickoff next week.", "line": 20}
        r = verify(p, self.lines, REF)
        self.assertNotEqual(r["due"]["raw"], "30 November")
        self.assertEqual(r["status"], "needs_review")

    def test_suggestion_is_not_decision(self):
        p = {"type": "decision", "summary": "x", "quote": "Maybe we should rewrite the notification service at some point.", "line": 15}
        self.assertEqual(verify(p, self.lines, REF)["status"], "needs_review")

    def test_approximate_quote_flagged_and_paraphrase_rejected(self):
        near = verify({"type": "risk", "summary": "x", "quote": "I'm worried the vendor sandbox might go down again today", "line": 7}, self.lines, REF)
        self.assertEqual(near["status"], "needs_review")
        self.assertEqual(near["evidence"][0]["line"], 7)
        idx, _, _ = locate("The vendor sandbox could crash and delay the testing phase badly", self.lines)
        self.assertEqual(idx, [])

    def test_evidence_text_is_verbatim(self):
        for it in analyze(SAMPLE, "2026-11-17", "rules")["items"]:
            for e in it["evidence"]:
                self.assertIn(e["text"], SAMPLE)


class Pipeline(unittest.TestCase):
    def test_gold_all_sets(self):
        cases, _ = evaluate.evaluate_all()
        self.assertGreaterEqual(len(cases), 5)
        for c in cases:
            self.assertEqual((c["missed"], c["extra"], c["field_errors"], c["forbidden_hits"]), ([], [], [], []), c)

    def test_fake_llm_hallucinations_are_caught(self):
        class Fake:
            name = "fake"

            def extract(self, lines, ref):
                return [{"type": "action", "summary": "s", "owner": "Zed", "due_raw": "1 Dec",
                         "quote": "Zed will deploy to production on 1 Dec", "line": None, "source": "fake"},
                        {"type": "decision", "summary": "s", "owner": None, "due_raw": None,
                         "quote": "We decided to use PostgreSQL 15 for the reporting service.", "line": 10, "source": "fake"}]
        r = analyze(SAMPLE, "2026-11-17", extractor=Fake())
        self.assertEqual(sorted(i["status"] for i in r["items"]), ["unsupported", "verified"])
        self.assertEqual(r["stats"]["unsupported"], 1)

    def test_empty_and_bad_engine(self):
        with self.assertRaises(ValueError):
            analyze("   \n ", None, "rules")
        with self.assertRaises(ValueError):
            analyze("A: hi", None, "magic")

    def test_unusual_input_does_not_crash(self):
        analyze("no speakers just text. Maybe? We decided nothing!\n\n\u2603 \u2603: ???", None, "rules")


SAMPLES = os.path.join(os.path.dirname(__file__), "..", "samples")


def all_texts():
    out = {}
    for f in sorted(os.listdir(SAMPLES)):
        if f.endswith((".txt", ".vtt")):
            with open(os.path.join(SAMPLES, f), encoding="utf-8") as fh:
                out[f] = fh.read()
    return out


def keyset(rep):
    return {(i["type"], i["evidence"][0]["line"], i["status"]) for i in rep["items"] if i["evidence"]}


class Formats(unittest.TestCase):
    def test_vtt_and_teams(self):
        v = parse(all_texts()["hard_vtt_meeting.vtt"])
        self.assertEqual((v[0].speaker, v[0].n), ("Hari", 5))
        tm = parse(all_texts()["hard_teams_meeting.txt"])
        self.assertEqual((tm[0].speaker, tm[1].speaker, tm[1].n), ("Priya Nair", "Sam Wilson", 5))

    def test_srt_without_speakers(self):
        ls = parse("1\n00:00:01,000 --> 00:00:03,000\nI'll send the deck by Friday.\n")
        self.assertEqual((len(ls), ls[0].speaker, ls[0].n), (1, None, 3))


class Refinements(unittest.TestCase):
    def run_text(self, text, date="2026-11-17"):
        return analyze(text, date, "rules")["items"]

    def types(self, text):
        return [(i["type"], i["status"]) for i in self.run_text(text)]

    def test_past_release_is_not_a_milestone(self):
        self.assertNotIn("milestone", [t for t, _ in self.types("A: The last release went out on 3 November.")])
        self.assertNotIn("milestone", [t for t, _ in self.types("A: The release notes are due Friday.")])
        self.assertIn(("milestone", "verified"), self.types("A: The release is scheduled for 2 December."))

    def test_fillers_and_missing_punctuation(self):
        it = self.run_text("Ravi: um I will, you know, finish the api by friday")[0]
        self.assertEqual((it["type"], it["owner"], it["due"]["iso"], it["status"]), ("action", "Ravi", "2026-11-20", "verified"))

    def test_reversal_flags_earlier_action(self):
        items = self.run_text("A: Divya can you update the release notes by Thursday?\nDivya: Sure.\n"
                              "A: Actually scratch that, the release notes are due Friday.")
        act = next(i for i in items if i["type"] == "action")
        self.assertEqual(act["status"], "needs_review")
        self.assertTrue(any("revised or cancelled" in f for f in act["flags"]))

    def test_moved_milestone_flags_the_old_date(self):
        items = self.run_text("A: The cutover is scheduled for 30 November.\nB: Let's move the cutover to 2 December.\nA: Agreed.")
        ms = sorted((i for i in items if i["type"] == "milestone"), key=lambda i: i["evidence"][0]["line"])
        self.assertEqual((ms[0]["due"]["iso"], ms[0]["status"]), ("2026-11-30", "needs_review"))
        self.assertEqual((ms[1]["due"]["iso"], ms[1]["status"]), ("2026-12-02", "verified"))

    def test_open_question_vs_answered(self):
        self.assertIn(("question", "verified"), self.types("A: Who approves the budget?\nB: No idea."))
        self.assertEqual(self.types("A: Who approves the budget?\nB: Priya approves it."), [])   # answered -> not open
        self.assertEqual(self.types("A: Who will own the wiki?\nB: I'll take it.")[0][0], "action")

    def test_group_pronoun_owner_is_flagged_not_guessed(self):
        it = self.run_text("A: We need to finalize the checklist by Friday.")[0]
        self.assertEqual((it["owner"], it["status"]), (None, "needs_review"))


class Invariants(unittest.TestCase):
    """The trust guarantees must hold for ANY input, including distorted ones."""
    VARIANTS = {
        "original": lambda s: s,
        "crlf": lambda s: s.replace("\n", "\r\n"),
        "curly": lambda s: s.replace("'", "\u2019"),
        "lower": lambda s: s.lower(),
        "nopunct": lambda s: "".join(c for c in s if c not in ".,?!;"),
        "upper": lambda s: s.upper(),
    }

    def test_invariants_everywhere(self):
        for name, text in all_texts().items():
            for vname, f in self.VARIANTS.items():
                src = f(text)
                rep = analyze(src, "2026-11-17", "rules")
                flat = src.replace("\r\n", "\n")
                for it in rep["items"]:
                    for e in it["evidence"]:
                        self.assertIn(e["text"], flat, (name, vname))          # evidence is verbatim
                    if it["status"] == "verified":
                        self.assertEqual(it["flags"], [], (name, vname, it["summary"]))
                        self.assertTrue(it["evidence"])
                        if it["type"] == "action":
                            self.assertTrue(it["owner"] and it["due"]["iso"], (name, vname, it["summary"]))
                        if it["type"] == "milestone":
                            self.assertTrue(it["due"]["iso"], (name, vname, it["summary"]))
                    if it["status"] == "unsupported":
                        self.assertEqual(it["evidence"], [])

    def test_line_ending_and_apostrophe_variants_do_not_change_results(self):
        for name, text in all_texts().items():
            base = keyset(analyze(text, "2026-11-17", "rules"))
            for v in ("crlf", "curly"):
                self.assertEqual(base, keyset(analyze(self.VARIANTS[v](text), "2026-11-17", "rules")), (name, v))

    def test_garbage_input_never_crashes(self):
        for junk in ("\x00\x01 ::: ???", "A:" * 500, "\n".join("X: " + "word " * 300 for _ in range(30)),
                     "[00:00] : : :", "WEBVTT\n\n-->", "Name   0:01\nName   0:02\n", "\u2603: \U0001F600 will do by tomorrow"):
            try:
                analyze(junk, None, "rules")
            except ValueError as e:          # only the clean "nothing to analyse" error is acceptable
                self.assertIn("empty", str(e))


class FakeOllama(unittest.TestCase):
    """Plumbing test: a fake Ollama server proves model selection reaches the extractor and output is verified."""
    def test_model_selection_and_verification(self):
        from http.server import BaseHTTPRequestHandler
        seen = {}

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a): pass

            def do_GET(self):
                b = json.dumps({"models": [{"name": "fake:1b"}, {"name": "other:3b"}]}).encode()
                self.send_response(200); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)

            def do_POST(self):
                req = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                seen["model"] = req["model"]
                items = {"items": [{"type": "decision", "summary": "PG15", "owner": None, "due": None, "line": 10,
                                    "quote": "We decided to use PostgreSQL 15 for the reporting service."},
                                   {"type": "action", "summary": "made up", "owner": "Zed", "due": "1 Dec", "line": 3,
                                    "quote": "Zed will deploy to production on 1 Dec"}]}
                b = json.dumps({"message": {"content": json.dumps(items)}}).encode()
                self.send_response(200); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
        fake = ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=fake.serve_forever, daemon=True).start()
        os.environ["AMIA_OLLAMA_HOST"] = f"http://127.0.0.1:{fake.server_address[1]}"
        try:
            r = analyze(SAMPLE, "2026-11-17", "ollama", model="other:3b")
            self.assertEqual((r["engine_used"], r["model"], seen["model"]), ("ollama", "other:3b", "other:3b"))
            self.assertEqual(sorted(i["status"] for i in r["items"]), ["unsupported", "verified"])
            with self.assertRaises(Exception):
                analyze(SAMPLE, "2026-11-17", "ollama", model="not-installed:9b")
        finally:
            os.environ.pop("AMIA_OLLAMA_HOST", None)
            fake.shutdown(); fake.server_close()


class StoreAndApi(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(os.path.join(self.tmp.name, "t.db"))
        self.run = self.store.create_run(analyze(SAMPLE, "2026-11-17", "rules"))

    def tearDown(self):
        self.tmp.cleanup()

    def item(self, run, line, t="action"):
        return next(i for i in run["items"] if i["type"] == t and i["evidence"][0]["line"] == line)

    def test_correction_keeps_original(self):
        it = self.item(self.run, 20)
        r = self.store.add_correction(self.run["id"], it["id"], {"action": "edit", "owner": "Sam", "due": "2026-11-24",
                                                                 "reviewer": "Anita", "note": "said in call"})
        it2 = self.item(r, 20)
        self.assertEqual(it2["current"]["due"], "2026-11-24")
        self.assertEqual(it2["current"]["review"], "corrected")
        self.assertIsNone(it2["due"]["iso"])                 # original untouched
        self.assertEqual(it2["history"][0]["before"]["due"], "next week")
        self.assertEqual(it2["history"][0]["reviewer"], "Anita")

    def test_validation(self):
        it = self.item(self.run, 20)
        for bad in ({"action": "nope"}, {"action": "edit"}, {"action": "edit", "due": "whenever"},
                    {"action": "edit", "type": "banana"}, {"action": "edit", "summary": ""}):
            with self.assertRaises(ValidationError):
                self.store.add_correction(self.run["id"], it["id"], bad)
        with self.assertRaises(KeyError):
            self.store.add_correction(self.run["id"], "i999", {"action": "confirm"})

    def test_http_api(self):
        srv = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(self.store))
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{srv.server_address[1]}"

        def call(path, body=None):
            req = urllib.request.Request(base + path, json.dumps(body).encode() if body is not None else None,
                                         {"Content-Type": "application/json"})
            try:
                with urllib.request.urlopen(req) as r:
                    return r.status, r.read().decode()
            except urllib.error.HTTPError as e:
                return e.code, e.read().decode()
        try:
            self.assertEqual(call("/")[0], 200)
            self.assertEqual(call("/api/analyze", {"transcript": ""})[0], 400)
            self.assertEqual(call("/api/analyze", {"transcript": "A: hi", "meeting_date": "17/11/2026"})[0], 400)
            self.assertEqual(call("/api/analyze", {"transcript": "A: hi", "engine": "x"})[0], 400)
            code, body = call("/api/analyze", {"transcript": SAMPLE, "meeting_date": "2026-11-17", "engine": "rules"})
            self.assertEqual(code, 200)
            rid = json.loads(body)["id"]
            self.assertEqual(call(f"/api/runs/{rid}/items/i2/correct", {"action": "confirm", "reviewer": "T"})[0], 200)
            code, md = call(f"/api/runs/{rid}/export?format=md")
            self.assertIn("evidence L4 [Ravi]", md)
            self.assertEqual(call("/api/runs/ffffffff")[0], 404)
            self.assertEqual(call("/api/runs/" + rid + "/items/i1/correct", {"action": "bad"})[0], 400)
        finally:
            srv.shutdown()


if __name__ == "__main__":
    unittest.main()
