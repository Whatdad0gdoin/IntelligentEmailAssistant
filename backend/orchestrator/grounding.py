"""Verification layer (spec sections 4.3, 4.4, 4.5, 4.6).

The premise: a model asked to summarise will sometimes produce a fluent,
well-formed summary containing a number, a date or a name that is not in the
source email. Fluency is no signal at all here -- a fabricated summary reads
exactly as well as a correct one, which is precisely why ROUGE cannot catch
this and why this module exists.

So nothing the model says about facts is taken on trust. Two checks:

  verify_evidence()  -- section 4.3. The classifier must quote a verbatim span
                        that justifies its label. If that span is not actually
                        in the email, the label is discarded and the email is
                        routed to Review.

  check_grounding()  -- sections 4.4/4.5. Every number, amount, time, date and
                        proper noun in a generated summary or draft must appear
                        in the source. Anything that does not is flagged, and
                        the output is returned marked unverified rather than
                        silently dropped or silently shipped as clean.

Both are deterministic. This module never calls a model -- a verifier that
could itself hallucinate would be worthless.

Precision note: these checks are tuned to under-flag rather than over-flag on
paraphrase, but they are string checks, not semantic ones. A flag means "this
token is not in the source", which is evidence of a problem, not proof of one;
no flags means "nothing detectable is missing", not "the summary is true".
Section 10 of the report should say so.
"""

import logging
import re
import unicodedata
from dataclasses import dataclass, field

log = logging.getLogger(__name__)


# --- Text normalisation ----------------------------------------------------

_QUOTES = {
    "‘": "'", "’": "'", "‚": "'", "‛": "'",
    "“": '"', "”": '"', "„": '"',
    "–": "-", "—": "-", "−": "-",
    " ": " ",
}


def normalise(text):
    """Lowercase, unify quotes and dashes, collapse whitespace.

    Applied to both sides of every comparison so that a curly apostrophe in the
    source and a straight one in the model output do not read as a fabrication.
    """
    text = text or ""
    for src, dst in _QUOTES.items():
        text = text.replace(src, dst)
    text = unicodedata.normalize("NFKC", text).lower()
    return re.sub(r"\s+", " ", text).strip()


# --- Evidence verification (section 4.3) -----------------------------------

# Below this length a span is not evidence of anything -- "a" appears in every
# email ever written, so a model could satisfy the check without quoting.
MIN_EVIDENCE_CHARS = 8


_PUNCTUATION = re.compile(r"[^\w\s]+")


def _depunctuate(text):
    """Normalised text with punctuation removed and spaces collapsed."""
    return re.sub(r"\s+", " ", _PUNCTUATION.sub(" ", normalise(text))).strip()


def verify_evidence(evidence, source):
    """True when `evidence` really is a verbatim span of `source`.

    Compared with punctuation removed from both sides. Measured on a 480-email
    run: the commonest failure was not fabrication but the model tidying its
    quote -- appending a full stop, or converting a nested quote to a different
    quote character. Those spans were word-for-word correct and were being
    thrown away, sending correctly classified emails to Review.

    This is a narrow relaxation, not a loose match. Every word must still be
    present, in the same order, contiguously. A stitched span joining two
    distant parts of the email still fails, because the words between them are
    missing from the candidate. What it stops punishing is typography.
    """
    span = normalise(evidence)
    if len(span) < MIN_EVIDENCE_CHARS:
        return False
    if span in normalise(source):
        return True
    stripped = _depunctuate(evidence)
    if len(stripped) < MIN_EVIDENCE_CHARS:
        return False
    return stripped in _depunctuate(source)


# --- Claim extraction (sections 4.4, 4.5) ----------------------------------

_MONTHS = (
    r"jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|"
    r"aug(?:ust)?|sep(?:t|tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?"
)

# Ordered by specificity. Earlier patterns claim their characters first, so
# "2pm" is checked as a time and never re-flagged as the bare number 2.
_TYPED_PATTERNS = (
    ("currency", re.compile(r"(?i)(?:aud|usd|nzd|gbp|eur)?\s?[$£€]\s?\d[\d,]*(?:\.\d+)?")),
    ("percent", re.compile(r"\d[\d,]*(?:\.\d+)?\s?%")),
    # The am/pm alternatives are spelled out longest-first so "3pm." yields the
    # claim "3pm" rather than dragging the sentence-ending full stop along.
    ("time", re.compile(
        r"(?i)\b\d{1,2}(?::\d{2})?\s?(?:a\.m\.|p\.m\.|(?:am|pm)\b)|\b\d{1,2}:\d{2}\b")),
    ("date", re.compile(r"\b\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?\b")),
    ("date", re.compile(r"(?i)\b(?:" + _MONTHS + r")\.?\s+\d{1,2}(?:st|nd|rd|th)?\b")),
    ("date", re.compile(r"(?i)\b\d{1,2}(?:st|nd|rd|th)?\s+(?:" + _MONTHS + r")\b")),
    ("weekday", re.compile(
        r"(?i)\b(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday|"
        r"tomorrow|yesterday)\b")),
    ("number", re.compile(r"(?<![\w.])\d[\d,]*(?:\.\d+)?(?![\w])")),
)

_NUMERIC_CORE = re.compile(r"\d[\d,]*(?:\.\d+)?")
_TIME_PARTS = re.compile(r"(?i)(\d{1,2})(?::(\d{2}))?\s?(a\.?m\.?|p\.?m\.?)?")


def _numeric_cores(text):
    """Every number in `text`, normalised so 5,000 and 5000.00 compare equal."""
    cores = set()
    for match in _NUMERIC_CORE.finditer(text or ""):
        raw = match.group(0).replace(",", "")
        if "." in raw:
            raw = raw.rstrip("0").rstrip(".")
        cores.add(raw or "0")
    return cores


def _minutes(token):
    """Clock time as minutes since midnight, or None.

    Lets 2pm, 2:00pm and 14:00 compare equal instead of reading as three
    different claims.
    """
    match = _TIME_PARTS.search(token or "")
    if not match:
        return None
    hour = int(match.group(1))
    minute = int(match.group(2) or 0)
    meridiem = (match.group(3) or "").replace(".", "").lower()
    if meridiem == "pm" and hour != 12:
        hour += 12
    elif meridiem == "am" and hour == 12:
        hour = 0
    if hour > 23 or minute > 59:
        return None
    return hour * 60 + minute


def _source_times(text):
    """Every clock time in `text`, as minutes since midnight."""
    times = set()
    for kind, pattern in _TYPED_PATTERNS:
        if kind != "time":
            continue
        for match in pattern.finditer(text or ""):
            value = _minutes(match.group(0))
            if value is not None:
                times.add(value)
    return times


# --- Dates, weekdays and years by meaning, not spelling -------------------------
#
# Measured on 2026-10-06: most of Gemini 3.8 Flash's summary flags on a 60-email
# sample were the model writing out a date the email abbreviated -- "July 14"
# for an airline's "14JUL", "January 17th" for "Jan 17", "Thursday" for
# "Thurs", "1999" for the "99" in "6/1/99". Each was reported to the user as an
# unverified claim although the fact was in the email. These helpers compare
# what a date MEANS, so reformatting stops reading as invention, while a date,
# day or year that is genuinely absent is still flagged.

_MONTH_NUMBERS = {name: number for number, names in enumerate((
    ("jan", "january"), ("feb", "february"), ("mar", "march"), ("apr", "april"),
    ("may",), ("jun", "june"), ("jul", "july"), ("aug", "august"),
    ("sep", "sept", "september"), ("oct", "october"), ("nov", "november"),
    ("dec", "december"),
), start=1) for name in names}

_MONTH_WORD = r"(?:" + _MONTHS + r")"
_MONTH_DAY = re.compile(r"(?i)\b(" + _MONTH_WORD + r")\.?\s*(\d{1,2})(?:st|nd|rd|th)?\b")
_DAY_MONTH = re.compile(r"(?i)\b(\d{1,2})(?:st|nd|rd|th)?\s*(" + _MONTH_WORD + r")\b")
# A numeric date in the source needs its year. Without one, "24/7", "1/2 of the
# total", "3-5 business days" and "Mon-Fri 9-5" all read as dates, and each
# vouched for a date the email never gave. So "14/7" alone is not read as one
# -- a false flag on a real date, the cheaper of the two mistakes.
_NUMERIC_DATE = re.compile(r"\b(\d{1,2})([/-])(\d{1,2})\2(?:\d{2}|\d{4})\b")
_ISO_DATE = re.compile(r"\b\d{4}-(\d{1,2})-(\d{1,2})\b")

_WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
# Abbreviations count only when written as one (capitalised or upper case),
# because lower-case "sat", "sun", "wed" and "mon" are ordinary words.
_WEEKDAY_ABBREVIATIONS = {
    "Mon": "monday", "Tue": "tuesday", "Tues": "tuesday", "Wed": "wednesday",
    "Thu": "thursday", "Thur": "thursday", "Thurs": "thursday", "Fri": "friday",
    "Sat": "saturday", "Sun": "sunday",
}
# These three are words even when capitalised -- "The Sun reported", "Your SAT
# score", "Wed in June" -- so they count only beside a date or a time ("Sat 5
# Oct", "SAT 14JUL", "Sun 10am") or in a range of days ("Mon-Sat", "Sat & Sun").
_AMBIGUOUS_ABBREVIATIONS = ("sat", "sun", "wed")
_ANY_DAY = r"(?:mon|tue|tues|wed|thu|thur|thurs|fri|sat|sun)(?:day|nesday|sday|rsday|urday)?"
_DATE_AFTER = re.compile(r"\.?,?\s*(?:\d|(?:" + _MONTHS + r")\b)", re.I)
_RANGE_AFTER = re.compile(r"\.?\s*(?:[-–—/&,]|to\b|and\b)\s*" + _ANY_DAY + r"\b", re.I)
_RANGE_BEFORE = re.compile(r"\b" + _ANY_DAY + r"\.?\s*(?:[-–—/&,]|to|and)\s*$", re.I)
_WORD = re.compile(r"[A-Za-z]+")

# A two-digit year only counts as one inside a numeric date ("6/1/99") or after
# an apostrophe that starts a word ("'99") -- never as a bare number, or "99
# bottles" would vouch for the year 1999, and never after a digit, or a height
# of 6'10" would vouch for 2010.
_TWO_DIGIT_YEAR = re.compile(r"(?:\b\d{1,2}[/-]\d{1,2}[/-]|(?<!\w)['’])(\d{2})\b")


def _month_days(text, source):
    """Every (month, day) a text names.

    A numeric date in the SOURCE is read both ways, because "3/4/26" is 3 April
    in Australia and March 4 in the United States, and the verifier's job is to
    ask whether the email supports the claim -- not to guess which convention a
    sender used. A numeric date in a CLAIM is matched literally elsewhere.

    In the source, "may" is a month only when written as one: "Step 2 may take
    a minute" names no date.
    """
    found = set()
    for month, day in _MONTH_DAY.findall(text or ""):
        if not (source and month == "may"):
            found.add((_MONTH_NUMBERS.get(month.lower()), int(day)))
    for day, month in _DAY_MONTH.findall(text or ""):
        if not (source and month == "may"):
            found.add((_MONTH_NUMBERS.get(month.lower()), int(day)))
    if source:
        for first, _separator, second in _NUMERIC_DATE.findall(text or ""):
            a, b = int(first), int(second)
            found.add((a, b))
            found.add((b, a))
        for month, day in _ISO_DATE.findall(text or ""):
            found.add((int(month), int(day)))
    return {(m, d) for m, d in found if m and 1 <= m <= 12 and 1 <= d <= 31}


def _source_weekdays(text):
    text = text or ""
    days = set()
    lowered = text.lower()
    for day in _WEEKDAYS:
        if re.search(r"\b" + day + r"\b", lowered):
            days.add(day)
    for match in _WORD.finditer(text):
        word = match.group(0)
        canonical = _WEEKDAY_ABBREVIATIONS.get(word) or _WEEKDAY_ABBREVIATIONS.get(word.title()
                                                                                if word.isupper() else "")
        if not canonical:
            continue
        if word.lower() in _AMBIGUOUS_ABBREVIATIONS and not (
                _DATE_AFTER.match(text, match.end())
                or _RANGE_AFTER.match(text, match.end())
                or _RANGE_BEFORE.search(text[max(0, match.start() - 16):match.start()])):
            continue
        days.add(canonical)
    return days


def _source_years(text):
    years = set()
    for two in _TWO_DIGIT_YEAR.findall(text or ""):
        value = int(two)
        years.add(str(1900 + value if value >= 50 else 2000 + value))
    return years


def extract_typed_claims(text):
    """Return [(kind, span)] for numerics, times, dates and weekdays."""
    claims = []
    taken = []

    def overlaps(start, end):
        return any(start < t_end and end > t_start for t_start, t_end in taken)

    for kind, pattern in _TYPED_PATTERNS:
        for match in pattern.finditer(text or ""):
            start, end = match.span()
            if overlaps(start, end):
                continue
            taken.append((start, end))
            claims.append((kind, match.group(0).strip()))
    return claims


# --- Proper nouns ----------------------------------------------------------

# Words that are capitalised for reasons other than being a name. Flagging
# these would bury the real signal in noise.
_NOT_NAMES = frozenset("""
a an and are as at be but by for from he her here his i if in is it its me my
of on or our she that the their them then there they this to us we what when
where which who will with you your yours
hi hello dear thanks thank regards best sincerely cheers please note re fwd
monday tuesday wednesday thursday friday saturday sunday today tomorrow
yesterday morning afternoon evening tonight week weekend month year
january february march april may june july august september october november
december
email inbox subject sender draft summary reply
""".split())

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")
_CAPITALISED = re.compile(r"^[A-Z][\w.'-]*$")
_ALL_CAPS = re.compile(r"^[A-Z]{2,}$")

# spaCy entity labels worth checking. DATE/TIME/MONEY/CARDINAL/PERCENT are
# excluded because the regexes above already handle them, more precisely.
_SPACY_LABELS = frozenset({
    "PERSON", "ORG", "GPE", "LOC", "FAC", "PRODUCT", "EVENT", "WORK_OF_ART", "NORP", "LAW",
})

_nlp = None
_nlp_loaded = False
ENTITY_BACKEND = "unloaded"


def _load_spacy():
    """Load spaCy once, or fall back.

    spaCy plus en_core_web_sm is a large install and the model is a separate
    download, so it cannot be assumed present. When it is missing the
    capitalisation heuristic below runs instead. That is genuinely weaker on
    lowercase names and stronger on nothing, so which backend ran is recorded
    in ENTITY_BACKEND and logged at first use -- an evaluation run must be able
    to say which one produced its numbers.
    """
    global _nlp, _nlp_loaded, ENTITY_BACKEND
    if _nlp_loaded:
        return _nlp
    _nlp_loaded = True
    try:
        import spacy

        _nlp = spacy.load("en_core_web_sm", disable=["lemmatizer", "textcat"])
        ENTITY_BACKEND = "spacy"
    except Exception as exc:
        _nlp = None
        ENTITY_BACKEND = "heuristic"
        log.info(
            "spaCy NER unavailable (%s); entity grounding uses the "
            "capitalisation heuristic. Install with: pip install spacy && "
            "python -m spacy download en_core_web_sm",
            type(exc).__name__,
        )
    return _nlp


def _heuristic_proper_nouns(text):
    """Capitalised runs that are not sentence-initial single words."""
    found = []
    for sentence in _SENTENCE_SPLIT.split(text or ""):
        tokens = sentence.split()
        run = []
        for index, token in enumerate(tokens):
            bare = token.strip(",;:()[]{}\"'!?.")
            is_name_shaped = bool(
                bare and (_CAPITALISED.match(bare) or _ALL_CAPS.match(bare))
            ) and bare.lower() not in _NOT_NAMES
            # A single capitalised word at the very start of a sentence is
            # usually just a sentence start, so it needs a neighbour to count.
            if is_name_shaped and not (index == 0 and len(tokens) > 1 and
                                       not _CAPITALISED.match(
                                           tokens[1].strip(",;:()[]{}\"'!?.") or "x")):
                run.append(bare)
                continue
            if run:
                found.append(" ".join(run))
                run = []
        if run:
            found.append(" ".join(run))
    return found


def extract_proper_nouns(text):
    """Names of people, organisations and places in `text`."""
    nlp = _load_spacy()
    if nlp is not None:
        try:
            return [
                ent.text.strip()
                for ent in nlp(text or "").ents
                if ent.label_ in _SPACY_LABELS and ent.text.strip()
            ]
        except Exception as exc:  # pragma: no cover - defensive
            log.warning("spaCy NER failed (%s); falling back to heuristic", type(exc).__name__)
    return _heuristic_proper_nouns(text)


# --- The check itself ------------------------------------------------------

_REASONS = {
    "currency": "amount does not appear in the source email",
    "percent": "percentage does not appear in the source email",
    "number": "number does not appear in the source email",
    "time": "time does not appear in the source email",
    "date": "date does not appear in the source email",
    "weekday": "day does not appear in the source email",
    "name": "name does not appear in the source email",
}


# Articles and salutations that an NER span can swallow. spaCy returns
# "Dear Student Services" as one ORG while handling "Hi Sarah" correctly, so a
# draft opening "Dear Student Services," was reported as an invented name even
# though the sender is called exactly that. Measured on 38 drafts: 7 of 8 flags
# were this one span shape.
_LEADING_FILLER = re.compile(r"^(?:the|a|an|dear|hi|hello|greetings|attn|to)\s+")
_TRAILING_POSSESSIVE = re.compile(r"['’]s?$")


def _name_in_source(name, source_normalised, source_depunctuated):
    """Is this proper noun supported by the source?

    Three forms are tried, because an NER span is not a quotation and the two
    differ in ways that say nothing about truthfulness. Measured over a 57
    summary run, 4 of 10 flags were one of the first two cases below -- the
    name was in the email, spelled exactly, and was reported as unsupported:

      as written           "Marc Deer"
      without a filler word "the Trust Agreement" / "Dear Student Services"
      without a possessive "Robert Parker's"      -> source has "Robert Parker"

    A flag is shown to the user as an unverified claim (section 5.3), so a
    false one costs real trust in the warning. None of these relaxations lets
    an invented name through: the name itself must still appear.
    """
    candidate = normalise(name)
    if not candidate:
        return True
    if candidate in source_normalised:
        return True

    stripped = _TRAILING_POSSESSIVE.sub("", _LEADING_FILLER.sub("", candidate)).strip()
    if stripped and stripped in source_normalised:
        return True

    # Punctuation inside a span ("Controller/CFO") is typography, not content.
    depunctuated = _depunctuate(stripped or candidate)
    return bool(depunctuated) and depunctuated in source_depunctuated


@dataclass(frozen=True)
class Flag:
    claim: str
    reason: str

    def as_dict(self):
        return {"claim": self.claim, "reason": self.reason}


@dataclass(frozen=True)
class GroundingResult:
    grounded: bool
    flags: list = field(default_factory=list)

    def as_api_flags(self):
        return [flag.as_dict() for flag in self.flags]


def check_grounding(generated, source):
    """Check every checkable claim in `generated` against `source`.

    `source` should be the preprocessed email plus any deterministic context
    the model was legitimately given -- subject, sender name, and for a draft
    the user instruction. A claim drawn from context the model was handed is
    not a fabrication, so that context has to be part of the haystack.
    """
    generated = generated or ""
    source = source or ""

    source_normalised = normalise(source)
    source_depunctuated = _depunctuate(source)
    source_numbers = _numeric_cores(source)
    source_times = _source_times(source)
    source_dates = _month_days(source, source=True)
    source_weekdays = _source_weekdays(source)
    source_years = _source_years(source)

    flags = []
    seen = set()

    def flag(claim, kind):
        key = normalise(claim)
        if key and key not in seen:
            seen.add(key)
            flags.append(Flag(claim=claim, reason=_REASONS[kind]))

    for kind, claim in extract_typed_claims(generated):
        if kind in ("currency", "percent", "number"):
            cores = _numeric_cores(claim)
            if cores <= source_numbers:
                continue
            # "1999" is supported by the "99" in "6/1/99", and nothing else.
            if kind == "number" and cores <= source_numbers | source_years:
                continue
            flag(claim, kind)
        elif kind == "time":
            value = _minutes(claim)
            if value is None or value not in source_times:
                flag(claim, kind)
        elif kind == "weekday":
            if normalise(claim) in source_normalised:
                continue
            if claim.lower() in _WEEKDAYS and claim.lower() in source_weekdays:
                continue
            flag(claim, kind)
        else:  # date
            if normalise(claim) in source_normalised:
                continue
            claimed = _month_days(claim, source=False)
            if claimed and claimed <= source_dates:
                continue
            flag(claim, kind)

    for name in extract_proper_nouns(generated):
        if not _name_in_source(name, source_normalised, source_depunctuated):
            flag(name, "name")

    return GroundingResult(grounded=not flags, flags=flags)


# --- Evaluation hook (section 4.6) -----------------------------------------


def groundedness_rate(outputs):
    """Percentage of outputs with zero ungrounded flags.

    `outputs` is any iterable of dicts carrying an "ungrounded_flags" key --
    the shape /api/summarise and /api/draft already return, so a batch can be
    scored straight from recorded API responses without re-running the model.

    This is the metric that belongs in the report. It answers "how often did
    the system state something the source did not support", which is the
    question ROUGE cannot answer.
    """
    outputs = list(outputs)
    total = len(outputs)
    clean = sum(1 for item in outputs if not item.get("ungrounded_flags"))
    return {
        "total": total,
        "grounded": clean,
        "flagged": total - clean,
        "rate": (clean / total) if total else 0.0,
        "entity_backend": ENTITY_BACKEND,
    }
