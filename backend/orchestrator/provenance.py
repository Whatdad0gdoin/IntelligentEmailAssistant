"""Provenance: locate the source text behind each generated sentence.

The grounding layer (section 4.4) already answers "is this claim present in the
source?" -- it normalises the text, looks for the claim, and keeps a boolean.
It throws away the one thing a reader actually wants: *where*.

This module keeps the position. For each summary sentence it returns character
offsets into the preprocessed source, so the UI can highlight the passage a
sentence came from. Verification says "trust this"; provenance shows why.

WHY OFFSETS ARE SAFE TO SHIP
Both /api/summarise and GET /api/inbox/<id> call preprocess() with the same
raw body and the same token budget, so both produce byte-identical text. The
offsets computed here therefore index exactly the string the browser renders.
If that ever stops being true, highlights will drift -- tests/test_provenance.py
pins it.

WHY NOT ASK THE MODEL
Rule 5: if a value can be computed, compute it. Asking the model to quote its
own sources invites it to fabricate a quotation, which is the failure mode the
grounding layer exists to catch. Matching is done here, deterministically, over
text the model never sees again.
"""

import re

from backend.orchestrator.grounding import extract_typed_claims, normalise

# Sentence boundaries, keeping offsets. Split on terminal punctuation followed
# by whitespace; newline-separated lines count as their own units so bullet
# lists and headers are locatable too.
_BOUNDARY = re.compile(r"(?<=[.!?])\s+|\n+")

_WORD = re.compile(r"[A-Za-z0-9']+")

# Words too common to carry evidence. Overlap on "the" means nothing; overlap
# on "quarterly" means a great deal.
_STOPWORDS = frozenset("""
a about after all also am an and any are as at be been before being but by can
could did do does doing for from further had has have having he her here hers
him his how i if in into is it its itself just me more most my no nor not of
off on once only or other our out over own same she should so some such than
that the their them then there these they this those through to too under
until up very was we were what when where which while who whom why will with
would you your
""".split())

# A single shared content word is coincidence. Two is a signal.
MIN_SHARED_WORDS = 2

# A shared number or date is worth more than a shared word: "2pm" appearing in
# both the summary and one source sentence is close to conclusive.
TYPED_CLAIM_WEIGHT = 3.0

MIN_SCORE = 2.0

# At most this many source passages per summary sentence. A sentence that
# "matches" half the email is not evidence of anything.
MAX_SPANS = 2


def _content_words(text):
    return {w for w in (m.group(0).lower() for m in _WORD.finditer(text)) if w not in _STOPWORDS and len(w) > 2}


def split_with_offsets(text):
    """Return [(start, end, sentence)] covering `text`."""
    if not text:
        return []
    units = []
    cursor = 0
    for match in _BOUNDARY.finditer(text):
        end = match.start()
        if end > cursor:
            units.append((cursor, end, text[cursor:end]))
        cursor = match.end()
    if cursor < len(text):
        units.append((cursor, len(text), text[cursor:]))
    return [(s, e, chunk) for s, e, chunk in units if chunk.strip()]


def _typed_values(text):
    """Normalised typed claims (numbers, times, dates) present in `text`."""
    return {normalise(span) for _kind, span in extract_typed_claims(text) if span}


def locate(generated_sentences, source):
    """Map each generated sentence onto supporting spans in `source`.

    Returns a list, one entry per generated sentence:

        {"sentence": 0, "spans": [{"start": 12, "end": 98, "score": 5.0}]}

    `spans` is empty when nothing in the source scores above threshold. That is
    a real and useful answer -- an unsupported sentence should highlight
    nothing rather than highlight something arbitrary.
    """
    units = split_with_offsets(source or "")
    if not units:
        return [{"sentence": i, "spans": []} for i, _ in enumerate(generated_sentences or [])]

    prepared = [(start, end, _content_words(chunk), _typed_values(chunk)) for start, end, chunk in units]

    results = []
    for index, sentence in enumerate(generated_sentences or []):
        sentence_words = _content_words(sentence)
        sentence_typed = _typed_values(sentence)

        scored = []
        for start, end, words, typed in prepared:
            shared_words = sentence_words & words
            shared_typed = sentence_typed & typed
            if len(shared_words) < MIN_SHARED_WORDS and not shared_typed:
                continue
            score = len(shared_words) + TYPED_CLAIM_WEIGHT * len(shared_typed)
            if score >= MIN_SCORE:
                scored.append({"start": start, "end": end, "score": round(score, 2)})

        scored.sort(key=lambda s: (-s["score"], s["start"]))
        top = sorted(scored[:MAX_SPANS], key=lambda s: s["start"])
        results.append({"sentence": index, "spans": top})

    return results
