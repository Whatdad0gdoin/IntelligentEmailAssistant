"""Voice intent classification (FR-05, spec section 6.3).

Two jobs, split because they have different failure modes.

The model decides *what* the user wants -- summarise, read, draft, or unknown.
That is a judgement about language, which is what a model is for. `unknown` is
a first-class answer: the interface responds by showing the transcript back and
asking the user to choose (section 6.3), which is a good outcome. A confidently
wrong action is not.

The backend decides *which email* they meant. That is resolve_target() below,
and it is deterministic string matching against the candidate list the caller
supplies. Email ids are parsed data, and rule 5 keeps parsed data away from the
model: a model asked for an id will eventually produce a plausible one that
does not exist, and the cost of that is dispatching an action to the wrong
message. Here, an unresolvable reference returns null and the UI asks.

Ambiguity resolves to null, never to a guess.
"""

import difflib
import logging
import re

from backend.orchestrator import prompts
from backend.orchestrator.client import get_client
from backend.orchestrator.grounding import normalise
from backend.orchestrator.schemas import INTENT_SCHEMA, INTENTS

log = logging.getLogger(__name__)

UNKNOWN = "unknown"

# Titles are not identifying: "Dr" matches every academic in the inbox.
_TITLES = frozenset({"dr", "mr", "mrs", "ms", "miss", "prof", "professor", "sir", "madam"})

# Words too common in a subject line to identify anything.
_SUBJECT_STOPWORDS = frozenset("""
about again alert all and any are back been before being but can come could
did does email emails for from get going has have here how info into
just like made make more much need new news not now off one only open our out
over please read really request required see send sent should some soon still
take team than that the their them then there these they this those time
today update updated very want was way week were what when where which will
with would you your
""".split())

# "the last email" in a newest-first list means the one that arrived last.
_RECENCY = re.compile(
    r"(?i)\b(?:latest|most recent|newest|last|first|top|the one at the top)\b"
)

_MIN_NAME_TOKEN = 3
_MIN_SUBJECT_TOKEN = 4

# Speech recognition mis-hears names constantly: "sarah" comes back as "sara",
# "sarra", "sahara". An exact-match-only resolver then finds nothing and the UI
# has to ask, which makes the feature feel broken even though the user spoke
# clearly. A near match on a name is accepted at a lower score than an exact
# one, so an exact match on a different email still wins.
# 0.78 is measured, not guessed. Against the inbox's sender names:
#   sara -> sarah    0.89     tara    -> sarah  0.67
#   sarra -> sarah   0.80     gitlab  -> github 0.67
#   robins -> robinson 0.86   sarcasm -> sarah  0.67
#   amelie -> amelia 0.83
# Genuine mis-hearings land at 0.80+, unrelated words at 0.67, so the threshold
# sits in the gap with room on both sides. Raising it to 0.82 loses "sarra";
# lowering it to 0.70 starts accepting "tara" as "Sarah", which is precisely
# the confidently-wrong dispatch this resolver exists to avoid.
_FUZZY_NAME_RATIO = 0.78

# Recognisers also split one written token into several spoken ones: "GitHub"
# comes back as "git hub", "Robinson" as "robin son", "FIT3164" as "fit 3164"
# or "fit three one six four". Fuzzy matching cannot rescue these, because each
# piece is compared on its own and "git" is nothing like "github". So the
# resolver also tries adjacent spoken words joined together, digits said one at
# a time glued into one number, and letters spelled one at a time glued into
# one word -- see _spoken_forms().
#
# A joined form only ever counts as an EXACT match. Fuzzy-matching the joins was
# tried and rejected: "read the one from the deals team" joins to "thedeals",
# 0.82 similar to "techdeals", and an unrelated request went to TechDeals.
#
# And it counts in full for sender names, but for a subject word only when
# that word contains a digit. Commands are made of everyday two-word phrases,
# and many of those are one-word compounds in subject lines: "read me" joins
# to "readme", "check out" to "checkout", "set up" to "setup". Allowed to match
# subjects, those joins sent "read me the latest email" to a GitHub "Update
# README.md" notification instead of the newest email. Sender names are proper
# nouns -- the words recognisers actually split -- and no everyday phrase joins
# into a unit code like "fit3164".
#
# Measured offline on 27 spoken references to an 8-email inbox
# (tests/test_voice_resolver.py): 15 resolved before, 20 after, none to the
# wrong email either way, and 16 references to nothing in the inbox resolve no
# more often than before.

# Digits said one at a time, so "three one six four" can meet the "3164" in a
# unit code. "oh" is how most people say a zero inside a code.
_SPOKEN_DIGITS = {
    "zero": "0", "oh": "0", "one": "1", "two": "2", "three": "3", "four": "4",
    "five": "5", "six": "6", "seven": "7", "eight": "8", "nine": "9",
}

# Two catches "git hub"; three catches "c s 1001". Runs of digits and spelled
# letters are glued before joining, so a long code does not need a longer join.
_MAX_JOINED_WORDS = 3


def _glue(tokens, belongs):
    """Merge each run of adjacent tokens that `belongs` accepts into one."""
    glued = []
    run = ""
    for token in tokens:
        if belongs(token):
            run += token
            continue
        if run:
            glued.append(run)
            run = ""
        glued.append(token)
    if run:
        glued.append(run)
    return glued


def _is_spelled_letter(token):
    return len(token) == 1 and token.isalpha()


def _has_digit(token):
    return any(ch.isdigit() for ch in token)


def _spoken_forms(words):
    """Every token one utterance's words could stand for. EXACT matching only.

    The words as heard; the same words with spoken digits as digits and each
    run of digits glued ("three one six four" -> "3164"); that again with each
    run of spelled letters glued ("c s" -> "cs"); and, for all three, every two
    or three adjacent words joined ("git hub" -> "github", "c s 1001" ->
    "cs1001").

    The plain words are kept alongside the digit forms rather than replaced by
    them, so "one drive" still joins to "onedrive" and a subject word like
    "three" still matches as itself.
    """
    numbered = _glue([_SPOKEN_DIGITS.get(word, word) for word in words], str.isdigit)
    spelled = _glue(numbered, _is_spelled_letter)
    forms = set()
    for sequence in (words, numbered, spelled):
        forms.update(sequence)
        for size in range(2, _MAX_JOINED_WORDS + 1):
            for start in range(len(sequence) - size + 1):
                forms.add("".join(sequence[start:start + size]))
    return forms


def _fuzzy_hit(haystack_words, token):
    """True when some spoken word is a near miss for `token`."""
    if len(token) < 4:
        # Short names cannot be fuzzy-matched safely: "ann" and "and" are one
        # edit apart and mean entirely different things.
        return False
    for word in haystack_words:
        if abs(len(word) - len(token)) > 3:
            continue
        if difflib.SequenceMatcher(None, word, token).ratio() >= _FUZZY_NAME_RATIO:
            return True
    return False


def _words(text):
    return [w for w in re.split(r"[^a-z0-9]+", normalise(text)) if w]


def _contains_word(haystack_words, word):
    return word in haystack_words


def resolve_target(reference, transcript, candidates, alternatives=None):
    """Pick which email the user meant, or None. No model involved.

    Sender names outrank subject words: people refer to mail by who sent it far
    more often than by what it says, and a name is a much less ambiguous token
    than a subject word.

    `alternatives` are the recogniser's other hypotheses for the same utterance.
    They are pooled into the search text: if the top hypothesis dropped the name
    but the third one caught it, that is still the user's own speech, and using
    it beats asking them to repeat themselves.

    A word the recogniser split ("git hub") is matched by joining the pieces
    back together. That is an exact match, scored like one, and it never takes
    part in fuzzy matching (see the note above _SPOKEN_DIGITS).
    """
    if not candidates:
        return None

    segments = [reference or "", transcript or ""] + list(alternatives or [])
    spoken = " ".join([transcript or ""] + list(alternatives or []))
    haystack = _words(f"{reference or ''} {spoken}")
    if not haystack:
        return None
    haystack_set = set(haystack)

    # Joined within each utterance, never across two: the last word of one
    # hypothesis and the first word of the next were not said together.
    joined = set()
    for segment in segments:
        joined |= _spoken_forms(_words(segment))

    scores = {}
    for candidate in candidates:
        email_id = candidate.get("id")
        if not email_id:
            continue
        score = 0

        for token in _words(candidate.get("sender_name") or ""):
            if len(token) >= _MIN_NAME_TOKEN and token not in _TITLES:
                if _contains_word(haystack_set, token) or token in joined:
                    score += 3
                elif _fuzzy_hit(haystack_set, token):
                    # Worth less than an exact match, so a clean hit on another
                    # email still beats a near miss on this one. Only the words
                    # as heard are fuzzy-matched, never the joined forms.
                    score += 2

        for token in set(_words(candidate.get("subject") or "")):
            if len(token) >= _MIN_SUBJECT_TOKEN and token not in _SUBJECT_STOPWORDS:
                # A joined form counts here only for a code with a digit in it:
                # "read me" must not reach a subject about a README.
                if _contains_word(haystack_set, token) or (
                    token in joined and _has_digit(token)
                ):
                    score += 1

        if score:
            scores[email_id] = score

    if scores:
        best = max(scores.values())
        winners = [email_id for email_id, score in scores.items() if score == best]
        if len(winners) == 1:
            return winners[0]
        # Two emails match equally well. The user has to say which, because
        # picking one at random is how a summary of the wrong email happens.
        log.info("voice: reference matched %d emails equally, returning null", len(winners))
        return None

    if _RECENCY.search(f"{reference or ''} {spoken}"):
        # Candidates arrive newest first. The frontend sends them in that order,
        # and POST /api/voice/intent re-sorts them whenever the caller says when
        # each one arrived, so this is the newest email in the mailbox -- not the
        # newest of whichever category happened to be listed first.
        return candidates[0].get("id")

    return None


def classify_intent(transcript, config, session_key=None, candidates=None, alternatives=None):
    """Map a transcript onto an action. Returns the /api/voice/intent body."""
    transcript = (transcript or "").strip()
    if not transcript:
        # Silence is not a command, and it is not worth an API call either.
        return {"intent": UNKNOWN, "target_email_id": None, "confidence": 0.0}

    payload = get_client(config).complete_json(
        system=prompts.INTENT_SYSTEM,
        user=prompts.intent_user(transcript),
        schema_name="voice_intent",
        schema=INTENT_SCHEMA,
        purpose="voice intent",
        session_key=session_key,
    )

    intent = payload.get("intent")
    if intent not in INTENTS:
        # The enum should prevent this; unknown is the safe reading if it fails.
        log.warning("voice: intent outside the enum, treating as unknown")
        intent = UNKNOWN

    try:
        confidence = max(0.0, min(1.0, float(payload.get("confidence", 0.0))))
    except (TypeError, ValueError):
        confidence = 0.0

    target = None
    if intent != UNKNOWN:
        target = resolve_target(
            payload.get("target_reference"), transcript, candidates or [], alternatives
        )

    log.info("voice: intent=%s confidence=%.2f target=%s", intent, confidence, bool(target))
    return {
        "intent": intent,
        "target_email_id": target,
        "confidence": round(confidence, 3),
    }
