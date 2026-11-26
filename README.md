# AMIA - Autonomous Meeting Intelligence Agent

Turns a meeting transcript into **Actions, Decisions, Open questions, Risks, Milestones and Context**.
Every item points to the exact transcript line it came from. Anything unsure is labelled *Needs human review*.
Runs 100% on your computer: the server binds to `127.0.0.1`, the only optional network call is to your own local Ollama.

## Run it (no installation, Python 3.8+ only)
```
python3 run.py        # Windows: run.bat      then open http://127.0.0.1:8765
```
Click **Load sample**, then **Analyze**. Run the checks with `python3 -m unittest discover -s tests` and `python3 evaluate.py`.

## Optional: smarter extraction with a local LLM
```
ollama pull qwen2.5:7b          # any Ollama model works: AMIA_MODEL=llama3.1:8b python3 run.py
```
With *Engine = Auto*, AMIA uses the LLM when Ollama is running, otherwise the built-in rule engine.
Either way the output passes through the same verifier.

## How "evidence before intelligence" works
1. **Propose** (`amia/extractors.py`) - the rule engine or the LLM only *suggests* items, each with a verbatim quote.
2. **Verify** (`amia/verifier.py`, plain code, no AI):
   - the quote must be found in the transcript (exact, spanning 2 lines, or >=85% fuzzy -> flagged "approximate"); otherwise the item is **Unsupported** and shown separately, never as fact;
   - the **owner** must be named in the evidence line, be the speaker saying "I'll...", or be the person who agreed; otherwise the owner is removed and flagged (guess);
   - **dates** are re-parsed from the evidence by `amia/dates.py`; invented dates are dropped; "next week/soon/same weekday/03/04" are flagged as vague/ambiguous, never guessed;
   - actions without owner/deadline, hedged wording (maybe/should/could), decisions that look like suggestions -> flagged.
3. **Review** (`amia/store.py`) - Confirm / Edit / Reject in the UI. The machine's original is never overwritten; each correction stores before, after, reviewer, note and timestamp (SQLite at `data/amia.db`).
4. **Export** Markdown or JSON; every claim carries `evidence L<line> [speaker]: "text"`.

## Rule engine v1.1 - what it now understands (offline, no model)
- **Formats:** `Name: text`, `[00:10] Name: text`, WebVTT/SRT (incl. `<v Name>`), Teams/Zoom blocks (`Name  0:05` + text lines).
- **Speech-to-text noise:** no punctuation, lowercase names, fillers ("um", "you know").
- **Actions:** "X will / X to / I'll / I'm going to / let me / X owns ... and will", "Name, please ...", "Can you ...?" + "Sure", and
  "I'll take that" (the earlier line is attached as supporting evidence). "We'll..." stays *unassigned* - never guessed.
- **Decisions:** explicit wording, negative decisions ("dropping", "not going to support"), and suggestion + agreement. Past-tense
  status ("Legal approved it last week") is context, not a decision.
- **Milestones:** only forward-looking target dates with a milestone word *and* a date framing; past releases, "release notes",
  "beta testers" are ignored. A decision that moves a date also yields the milestone (the *new* date is used).
- **Open questions:** also without "?" (ASR); answered ones are dropped; unclear replies are kept but flagged.
- **Cross-line checks (flags only, nothing is deleted):** later "actually / scratch that / correction" lines, a later different date
  for the same milestone, and questions possibly answered later.
- **Dates:** "the 25th", "next Wednesday", "day after tomorrow", "Q4"/"mid-December" (flagged vague), dd/mm ambiguity flagged.

## Measured accuracy (run `python3 evaluate.py`)
Labelled cases: 5 transcripts, 76 expected items. Before this refinement the same cases scored **84% precision / 62% recall**.
A transcript written *after* the patterns (held-out, never tuned) scored **16 of 22 items found** on first pass; its gaps were then fixed
as general rules. Treat the current 100% on these files as a regression baseline, **not** a promise for unseen meetings - expect
roughly the held-out level (about 70-90%) on new phrasing, with doubtful items flagged for review. Add your own transcript + gold file
to `samples/` (see `samples/*_gold.json`) to measure and tune on your meetings.

## Layout
`amia/` patterns, dates, transcript, extractors, verifier, pipeline, store, report, server - `static/index.html` UI -
`tests/` 32 tests (incl. trust invariants under distorted input) - `samples/` sample transcript + hand-labelled gold - `evaluate.py` precision/recall.

## Honest limits
The rule engine is English-only and pattern based: it will miss unusual phrasing, pronoun-heavy or multi-turn commitments
(use the LLM for those) but it cannot invent facts. "Open question" detection looks at the next 3 lines for an answer. Dates default to day-first (dd/mm).
Set the meeting date so "by Friday" resolves correctly. To tune wording, edit `amia/patterns.py`.
