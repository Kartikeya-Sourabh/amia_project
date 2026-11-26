"""All wording patterns in one place, shared by the rule extractor, verifier and pipeline."""
import re

TYPES = ("action", "decision", "question", "risk", "milestone", "context")
I = re.I

# ---------- text helpers
FILLER_RE = re.compile(r"(?:,\s*)?\b(?:um+|uh+|er+m?|hmm+|you know|i mean|sort of|kind of|basically|literally|"
                       r"honestly)\b(?:\s*,)?", I)
STOPW = set("the a an and or to of in on for with is are was were be will we i you it that this at by as from not do "
            "does did can could should would have has had so if then than but about our your their who what when "
            "where how which there here just also please let lets thats im ive ill okay yes yeah".split())


def clean(s):
    """For matching only (never for quoting): fix apostrophes and drop spoken fillers ('um', 'you know')."""
    return re.sub(r"\s+", " ", FILLER_RE.sub(" ", s.replace("\u2019", "'"))).strip()


def norm(s):
    s = s.lower().replace("\u2019", "").replace("'", "")
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", s)).strip()


def toks(s):
    return {w for w in norm(s).split() if len(w) > 2 and w not in STOPW}


# ---------- hedging
HEDGE_RE = re.compile(r"\b(maybe|perhaps|might|possibly|probably|i think|i guess|what if|should we|not sure|"
                      r"tentatively|we could|could(?!\s+you\b)|should|try(?:ing)? to|hope to|hopefully|aim(?:ing)? to)\b", I)
DEC_HEDGE_RE = re.compile(r"\b(maybe|perhaps|might|possibly|probably|i think|i guess|what if|not sure|tentatively)\b", I)

# ---------- decisions
DECISION_RE = re.compile(
    r"\b(?:we(?:'ve| have)? (?:decided|agreed|resolved|settled on|chosen)|decision (?:is|was)|"
    r"final (?:decision|call|answer)|(?:it'?s|that'?s|this is) (?:decided|settled|agreed|final)|let'?s go with|"
    r"we(?:'ll| will|'re| are) go(?:ing)? with|we(?:'re| are) going to use|(?:has|have) been (?:approved|decided|agreed)|"
    r"approved|signed off|going forward,? we(?:'ll| will)|"
    r"we(?:'ll| will) (?:also |now |just |then )?(?:use|proceed|stick with|switch to|skip|drop|postpone|defer|cancel)|"
    r"we(?:'re| are) (?:also |now |just |then )?(?:moving forward with|proceeding with|sticking with|switching to|dropping|skipping|postponing|deferring)|"
    r"we(?:'re| are) not going to|we(?:'ll| will) not (?:do|use|support|build|ship|include|implement|migrate)|"
    r"we won'?t (?:do|use|support|build|ship|include|implement|migrate)|decided against|"
    r"no longer (?:going to|doing|using|supporting)|descop(?:e|ed|ing)|scrap(?:ped|ping)? (?:the|that|this))\b", I)
PASTTIME_RE = re.compile(r"\b(?:last (?:week|month|sprint|quarter)|yesterday|earlier|previously|already|(?:days?|weeks?|months?) ago)\b", I)
SUGGEST_RE = re.compile(r"\b(i suggest|we could|maybe we|how about|what about|why don'?t we|i propose|should we|"
                        r"can we|could we|shall we|we should|let'?s (?:move|push|delay|postpone|reschedule|shift|bring|"
                        r"pull|keep|park|switch|drop|skip|make))\b", I)
AGREE_RE = re.compile(r"^\s*(agreed|sounds good|sounds right|yes|yeah|yep|sure|works for me|(?:that )?works|makes sense|"
                      r"let'?s do (?:it|that)|i agree|approved|ok(?:ay)?[, ]+(?:let'?s|do it|go ahead|sounds good)|"
                      r"go ahead|go for it|fine by me|good (?:idea|call|plan)|no objections?|"
                      r"i'?m (?:good|fine|ok|okay) with (?:that|it)|perfect|do it)\b", I)

# ---------- questions
OPEN_RE = re.compile(
    r"\b(?:open question|tbd|to be (?:decided|determined)|"
    r"(?:haven'?t|have not|hasn'?t|not yet|yet to) (?:been )?(?:decided|determined|finalized|agreed|confirmed)|"
    r"still (?:need|have) to (?:decide|figure out|determine)|need to (?:figure out|decide|determine)|"
    r"(?:unclear|not clear) (?:who|what|when|how|whether)|we don'?t (?:yet )?know (?:who|what|when|how|whether|if)|"
    r"(?:nobody|no one) (?:has )?(?:confirmed|decided|assigned|picked|signed|knows|owns)|"
    r"(?:is|are) still (?:open|pending|undecided|unresolved))\b", I)
_NAME = r"[A-Z][\w.'-]*"
INTERROG_RE = re.compile(
    r"^(?:(?:who|what|when|where|why|how|which)\s+(?:is|are|was|were|will|would|do|does|did|can|could|should|has|have)\b|"
    r"(?:do|does|did|can|could|should|will|would|have|has)\s+(?:we|you|anyone|anybody|someone|somebody|they|the|there)\b|"
    r"(?:is|are|was|were)\s+(?:we|you|there|it|the|this|that|anyone|someone)\b|any\s+idea\b|anyone\s+know\b)", I)
REQUEST_RE = re.compile(r"(?:(?P<addr>[A-Z][a-z]+),?\s+)?(?i:can|could|would|will) you (?:please )?(?P<what>.+?)\??$")
SMALLTALK_RE = re.compile(r"^(how are|can (?:you|everyone|all) (?:hear|see)|is everyone|are we (?:all )?(?:good|ready|set)|"
                          r"any (?:other )?(?:questions|thoughts)|does that make sense|right\?|ok(?:ay)?\?|"
                          r"shall we (?:start|begin)|can we start|ready\?)", I)
AFFIRM_RE = re.compile(r"^\s*(sure|yes|yeah|yep|ok|okay|will do|of course|no problem|got it|absolutely|on it|done)\b", I)
UNSURE_RE = re.compile(
    r"\b(not sure|don'?t know|do not know|no idea|tbd|haven'?t (?:decided|heard|checked)|unclear|"
    r"let me (?:check|find out)|(?:will|'ll|need to|have to) (?:check|find out|ask)|we'?ll see|"
    r"(?:come|get) back to (?:that|this|you)|take (?:that|this) offline|parking lot|good question|who knows|"
    r"not that i know(?: of)?|i haven'?t (?:heard|spoken|talked|checked)|nobody|no one|not yet)\b", I)
ANSWER_START_RE = re.compile(r"^\s*(yes|no|yeah|yep|nope|sure|correct|right|exactly|definitely|absolutely|of course|"
                             r"it'?s|it is|we (?:do|don'?t|have|haven'?t|are|aren'?t|will)|they|he|she|i think|probably)\b", I)
ANSWERISH_RE = re.compile(r"\b(will|'ll|own|owns|owner|responsible|decided|agreed|approved|confirmed|assigned|taking|"
                          r"handle|signs? off)\b", I)

# ---------- risks / context
RISK_RE = re.compile(
    r"\b(risk|risky|blockers?|blocked|concerned|concern|worried|worry|at risk|dependency|dependent on|behind schedule|"
    r"bottleneck|slip(?:s|ped|ping|page)?|delays?|delayed|waiting (?:on|for)|depends? on|depending on|"
    r"(?:might|could|may) (?:fail|break|block|go down|not)|(?:can'?t|cannot|unable to|not able to|couldn'?t) (?:handle|support|scale|meet|deliver|finish|keep up|cope|process|sustain)|won'?t (?:make|be able)|can'?t (?:make|meet|commit)|"
    r"not enough|too (?:little|few|late)|outage|regression|critical bug|security issue|escalat\w+|vulnerabilit(?:y|ies)|"
    r"(?:not sure|unsure|doubt)\b.*\b(?:ready|in time|on time|enough|make it|finish|complete))\b", I)
CONTEXT_RE = re.compile(
    r"\b(for context|background|fyi|as a reminder|currently|so far|last (?:week|sprint|month)|"
    r"we(?:'ve| have)? (?:already )?(?:completed|finished|shipped|deployed)|"
    r"(?:has|have|had) (?:already )?(?:completed|finished|shipped|deployed|merged|fixed|resolved|closed)|"
    r"(?:is|are|was|were) (?:now )?(?:done|complete|completed|finished|live|deployed|merged|resolved|fixed)|"
    r"\d{1,3}\s?(?:%|percent)|status)", I)

# ---------- milestones
_NOT_MS = r"(?!\s+(?:notes|branch|process|checklist|plan|pipeline|tag|manager|testers?|users?|group|flags?|team|strategy|schedule|review|criteria|docs?|documentation))"
MS_NOUN_RE = re.compile(r"\b(?:milestone|go[- ]?live|launch|release|code freeze|(?:schema |feature |scope )?freeze|"
                        r"deadline|target date|beta|cut[- ]?over|roll[- ]?out|demo day|demo|due date|handover|"
                        r"kick[- ]?off|sign[- ]?off|delivery|submission|deployment|migration)\b" + _NOT_MS, I)
SHIP_RE = re.compile(r"\b(?:we(?:'ll| will)?|to|will)\s+(?:ship|launch|release|go live|cut ?over|deploy)\b", I)
MS_FRAME_RE = re.compile(r"\b(?:scheduled|planned|targeted|targeting|slated|due|expected|booked|locked|fixed|committed|"
                         r"aimed|set (?:for|to|on)|starts?|begins?|ends?|lands?|kicks? off|happens?)\b|"
                         r"\b(?:is|are|will be|be)\s+(?:on|by|for)\b|\b(?:target date|deadline|milestone)\b|"
                         r"\b(?:goes|go|going|ships?|launch(?:es)?|rolls? out|releases?)\b[^.]{0,40}\b(?:on|by)\b", I)
MOVE_RE = re.compile(r"\b(?:mov(?:e|es|ed|ing)|push(?:ed|ing)?|slip(?:s|ped)?|shift(?:ed|ing)?|reschedul\w+|postpon\w+|"
                     r"delay(?:ed)?|bring(?:ing)? forward|pull(?:ed|ing)? in)\b.{0,60}\b(?:to|until|from|by)\b", I)
PAST_RE = re.compile(r"\b(?:went (?:out|live)|was|were|shipped|launched|released|deployed|completed|finished|happened|"
                     r"last (?:release|launch|sprint|week|month))\b", I)
REVERSAL_RE = re.compile(r"\b(actually|scratch that|scrap that|never ?mind|change of plan|on second thought|correction|"
                         r"instead|rather than|no longer|not anymore|forget (?:that|what)|disregard|let'?s not|"
                         r"that'?s off|called off|cancel(?:led)?|postponed|rescheduled)\b", I)

# ---------- actions
EXPLICIT_RE = re.compile(r"^\s*(?:action(?: item)?s?|todo|to-do|ai)\s*[:\-\u2013]\s*", I)
FIRST_PERSON_RE = re.compile(r"\b(i'?ll|i will|i can|i am going to|i'?m going to|i'?m gonna|let me|i'?m taking|"
                             r"i am taking|i can take)\b", I)
LEAD_IN_RE = re.compile(r"^(?:(?:ok|okay|so|right|great|sure|yes|yeah|alright|and|but|then|also|well|oh|anyway)\b[,.]?\s+)+", I)
_N1 = r"[A-Z][a-z]{1,}(?:\s[A-Z][a-z]{1,})?"
NAMES = rf"{_N1}(?:(?:,\s*and\s+|,\s*|\s+and\s+){_N1})*"
VERBS = (r"(?:'ll|\s+will(?:\s+be\s+(?:handling|owning|taking|doing|working on))?|\s+to|\s+is going to|\s+are going to|"
         r"\s+has to|\s+have to|\s+needs? to|\s+must|\s+owns?|\s+agreed to|\s+volunteered to|\s+offered to|\s+committed to|"
         r"\s+should|'m going to|\s+am going to|\s+is gonna|'m gonna|\s+gonna|'m taking|\s+am taking|"
         r"\s+can(?=\s+(?:take|handle|own|pick up|look into|follow up)\b))")
ACTION_NAME_RE = re.compile(rf"^(?P<who>{NAMES})(?P<verb>{VERBS})\s*(?P<what>[a-z].*)$")
ACTION_PRON_RE = re.compile(rf"^(?P<who>I|we|he|she|they|you)(?P<verb>{VERBS})\s*(?P<what>[a-z].*)$", I)
IMPERATIVE_RE = re.compile(r"^(?P<addr>[A-Z][a-z]+),?\s+please\s+(?P<what>[a-z].*)$")
LETME_RE = re.compile(r"^let me (?P<what>[a-z].*)$", I)
REFERENTIAL_RE = re.compile(r"^(?:do|take|handle|get|own|pick up|follow up on|look into|sort out|take care of)\s+"
                            r"(?:that|it|this|those|them)\b", I)
STOP_WHO = {"That", "This", "It", "There", "What", "Which", "Who", "When", "Where", "How", "The", "Then", "But",
            "And", "So", "Also", "Next", "Let", "Do", "Does", "Did", "If", "Because", "Maybe", "Perhaps", "Thanks",
            "Thank", "Okay", "Ok", "Yes", "No", "Sure", "Nice", "Good", "Great", "Happy", "Time", "Need", "Want",
            "Glad", "Here", "Now", "Today", "Everything", "Everyone", "Nothing", "Something", "Not", "Although",
            "Though", "While", "Agreed", "Actually", "Alright", "Anyway", "Quick", "Two", "Three", "Both"}
GENERIC_OWNERS = {"", "i", "me", "we", "us", "team", "someone", "somebody", "unknown", "tbd", "none", "n/a",
                  "they", "he", "she", "you", "everyone", "unassigned", "null"}
