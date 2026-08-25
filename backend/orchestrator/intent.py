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


def _words(text):
    return [w for w in re.split(r"[^a-z0-9]+", normalise(text)) if w]


def _contains_word(haystack_words, word):
    return word in haystack_words


def resolve_target(reference, transcript, candidates):
    """Pick which email the user meant, or None. No model involved.

    Sender names outrank subject words: people refer to mail by who sent it far
    more often than by what it says, and a name is a much less ambiguous token
    than a subject word.
    """
    if not candidates:
        return None

    haystack = _words(f"{reference or ''} {transcript or ''}")
    if not haystack:
        return None
    haystack_set = set(haystack)

    scores = {}
    for candidate in candidates:
        email_id = candidate.get("id")
        if not email_id:
            continue
        score = 0

        for token in _words(candidate.get("sender_name") or ""):
            if len(token) >= _MIN_NAME_TOKEN and token not in _TITLES:
                if _contains_word(haystack_set, token):
                    score += 3

        for token in set(_words(candidate.get("subject") or "")):
            if len(token) >= _MIN_SUBJECT_TOKEN and token not in _SUBJECT_STOPWORDS:
                if _contains_word(haystack_set, token):
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

    if _RECENCY.search(f"{reference or ''} {transcript or ''}"):
        # Candidates arrive newest first (the adapter sorts them).
        return candidates[0].get("id")

    return None


def classify_intent(transcript, config, session_key=None, candidates=None):
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
        target = resolve_target(payload.get("target_reference"), transcript, candidates or [])

    log.info("voice: intent=%s confidence=%.2f target=%s", intent, confidence, bool(target))
    return {
        "intent": intent,
        "target_email_id": target,
        "confidence": round(confidence, 3),
    }
