"""Markdown export - every claim carries its transcript line."""
from . import patterns as P

LABEL = {"action": "Actions", "decision": "Decisions", "question": "Open questions", "risk": "Risks",
         "milestone": "Milestones", "context": "Context"}


def to_markdown(r):
    out = [f"# {r['title']}", f"*Meeting date: {r['meeting_date']} - engine: {r['engine_used']}"
           f"{' (' + r['model'] + ')' if r.get('model') else ''} - participants: {', '.join(r['participants']) or 'n/a'}*", ""]
    s = r["stats"]
    out += [f"**{s['verified']} verified, {s['needs_review']} need human review, "
            f"{s['unsupported']} rejected as unsupported.**", ""]
    for w in r.get("warnings", []):
        out.append(f"> Note: {w}")
    for t in P.TYPES:
        items = [i for i in r["items"] if i["current"]["type"] == t and i["current"]["review"] != "rejected"
                 and i["status"] != "unsupported"]
        if not items:
            continue
        out += ["", f"## {LABEL[t]}"]
        for i in items:
            c = i["current"]
            tag = {"confirmed": "CONFIRMED BY HUMAN", "corrected": "CORRECTED BY HUMAN"}.get(
                c["review"], "VERIFIED" if i["status"] == "verified" else "NEEDS REVIEW")
            bits = [f"[{tag}]", c["summary"]]
            if t == "action":
                bits.append(f"- owner: {c['owner'] or 'UNASSIGNED'}")
            if t in ("action", "milestone"):
                bits.append(f"- due: {c['due'] or 'NOT STATED'}")
            out.append("- " + " ".join(bits))
            for e in i["evidence"]:
                out.append(f"    - evidence L{e['line']} [{e['speaker'] or '?'}]: \"{e['text']}\"")
            if c["review"] != "confirmed":
                for f in i["flags"]:
                    out.append(f"    - flag: {f}")
            for h in i["history"]:
                out.append(f"    - {h['action']} by {h['reviewer']} at {h['at']}: before={h['before']} -> after={h['after']}"
                           f"{' - ' + h['note'] if h['note'] else ''}")
    rej = [i for i in r["items"] if i["status"] == "unsupported"]
    if rej:
        out += ["", "## Rejected by verifier (not backed by the transcript)"]
        out += [f"- {i['summary']} ({'; '.join(i['flags'])})" for i in rej]
    return "\n".join(out) + "\n"
