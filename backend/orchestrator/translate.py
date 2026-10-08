"""Translation (FR-07).

The RTM asks for "email content or drafted reply" to be translated into a
language the user chooses. Both are here:

  translate_email()  the open email: its subject and the same cleaned body the
                     reading pane shows (preprocess_email).
  translate_text()   text the client supplies -- the draft in the reply panel.

Neither is cached. A summary is three sentences about an email and the summary
cache keeps it; a translation is the whole message in another language, and
keeping one between calls would be keeping the body, which NFR-03 rules out.
Asking again costs one more call, a couple of seconds and a fraction of a cent.

What is checked, and why that
-----------------------------
A translation reads fluently whether or not it is right, and the error that
does damage is rarely a clumsy phrase. It is a figure that changed on the way
through: an amount that lost a zero, a date read in the other order, a link one
character off. Whether the meaning survived is beyond a string check; whether
the figures did is not, and the check is the same in every pair of languages:

  - every number in the translation must appear in the original ("number not
    in the original"), and every number in the original must appear in the
    translation ("number missing from the translation"). Numbers compare by
    their digits alone, separators dropped, so 1,000.50 and 1.000,50 -- one
    amount in English and in German notation -- are the same number, and
    digits written in another script count as the digits they are.
  - every URL and email address in the original must survive verbatim, and
    the translation may not contain one the original does not. A link added by
    an instruction hidden in the email is the case that matters there.

One exception, in one direction: a month the original names in words may come
back as its number, because that is how Chinese, Japanese and Korean write a
date (October 15 is 10月15日). Measured on 37 emails translated into Chinese
(2026-10-08), 15 of the 17 "number not in the original" flags were exactly
that, and a warning that fires on every dated email stops being read. The
reverse -- a numeric date written out with a month name -- is still flagged,
because that is where 3/4 becomes the wrong one of 3 April and March 4.

The flags use the summary's {claim, reason} shape, so the frontend shows them
with the same GroundingNotice. As in grounding.py, a flag means "check this",
not "this is wrong", and no flags means nothing checkable changed -- not that
the translation is good.

Long text
---------
A translation is as long as its original, and output is the slow half of a
model call. Measured on the shipped model (2026-10-08): about 4,000 characters
of English took 12.5 s into Chinese and 9.2 s into Spanish, at 65 and 107
output tokens a second. A body at the full 12,000-character budget would
overrun the client's 20-second timeout in one call, so a long text is cut at
paragraph, line or sentence boundaries and the pieces are translated at once,
each its own call, charged to the session budget like any other. The
whitespace between pieces is put back as it was, and the check runs over the
whole. Measured the same day through the route: 9,500 characters in four
pieces took 9.3 s into Chinese and 6.0 s into Spanish.

A response with no usable translation in it is retried once with the fault
stated, as summarise.py does, and then fails loudly (502).

Logging (NFR-03): ids, lengths, the language and flag counts. Never the text,
on either side of the translation.
"""

import logging
import re
import unicodedata
from concurrent.futures import ThreadPoolExecutor

from backend.orchestrator import prompts
from backend.orchestrator.client import LLMError, get_client
from backend.orchestrator.grounding import Flag, GroundingResult
from backend.orchestrator.preprocess import preprocess_email
from backend.orchestrator.schemas import (
    EMAIL_TRANSLATION_SCHEMA,
    LANGUAGES,
    TRANSLATION_SCHEMA,
)

log = logging.getLogger(__name__)

# Characters of original per model call, and calls in flight for one text.
# 2,500 characters is under 15 seconds of output even into Chinese at the
# slowest rate measured above, so a long email stays inside the client timeout
# and comes back in about the time its slowest piece takes.
CHUNK_CHARS = 2_500
MAX_CONCURRENT_PIECES = 6


class TranslationValidationError(LLMError):
    """The model returned no usable translation, even after a retry."""


class EmptyEmailError(LLMError):
    """There is nothing to translate once quoting and footers are removed."""


def _require_language(language):
    """Refuse a language that is not on the list.

    The route has already answered 400 for one. Reaching here means a caller
    went round it, and an unlisted value must not be written into a prompt.
    """
    if language not in LANGUAGES:
        raise ValueError("unsupported translation language")


# --- Cutting a long text ----------------------------------------------------

# Where a long text may be cut, best first: a blank line, a line break, the end
# of a sentence, any space. A full stop only ends a sentence with a space after
# it, or "1.5" would be cut in two; the CJK full stops need none, because
# Chinese and Japanese text has no spaces to fall back on.
_BOUNDARIES = (
    re.compile(r"\n[ \t]*\n"),
    re.compile(r"\n"),
    re.compile(r"(?<=[.!?])[ \t]|(?<=[\u3002\uff01\uff1f])"),
    re.compile(r"[ \t]"),
)


def _cut_point(text, limit):
    """Where to end the next piece: the latest boundary of the best kind.

    A boundary in the first third of the window is passed over, so a stray
    early line break does not produce a run of tiny pieces. With no boundary
    at all, the cut is at the limit itself.
    """
    window = text[:limit + 1]
    floor = max(1, limit // 3)
    for boundary in _BOUNDARIES:
        cut = None
        for match in boundary.finditer(window):
            if floor <= match.start() <= limit:
                cut = match.start()
        if cut is not None:
            return cut
    return limit


def split_text(text, limit=None):
    """Cut `text` into pieces of at most `limit` (default CHUNK_CHARS) characters.

    Returns [(piece, separator)]. Each piece has no whitespace at either end,
    and each separator is the whitespace that stood between it and the next,
    so the pieces' translations can be joined back with the original layout.
    A text within the limit comes back as one piece.
    """
    limit = limit or CHUNK_CHARS
    rest = (text or "").strip()
    pieces = []
    while len(rest) > limit:
        cut = _cut_point(rest, limit)
        head = rest[:cut].rstrip()
        tail = rest[cut:].lstrip()
        pieces.append((head, rest[len(head):len(rest) - len(tail)]))
        rest = tail
    pieces.append((rest, ""))
    return pieces


# --- Calling the model ------------------------------------------------------


def _field(payload, name):
    """One text field of a response, stripped, or ValueError naming the fault.

    Empty counts as unusable: an empty translation is not a translation. The
    fault is written into the log and into the retry prompt, so it names the
    field and never quotes it.
    """
    value = payload.get(name) if isinstance(payload, dict) else None
    if not isinstance(value, str):
        raise ValueError(f"the {name} was not a string")
    value = value.strip()
    if not value:
        raise ValueError(f"the {name} was empty")
    return value


def _call(client, user_prompt, schema_name, schema, read, session_key, label):
    """One model call, retried once if the response holds no usable translation.

    The client already retries a failed or unparseable call. This retry is
    for a response that parsed and is still unusable -- an empty translation --
    which only this module can judge (client.complete_json says the same).
    """
    fault = None
    for attempt in (1, 2):
        prompt = user_prompt if fault is None else prompts.translate_retry(user_prompt, fault)
        payload = client.complete_json(
            system=prompts.TRANSLATE_SYSTEM,
            user=prompt,
            schema_name=schema_name,
            schema=schema,
            purpose="translation",
            session_key=session_key,
        )
        try:
            return read(payload)
        except ValueError as exc:
            fault = exc
            log.warning("translate %s: unusable response on attempt %d (%s)", label, attempt, exc)
    raise TranslationValidationError(
        f"The model returned no usable translation after a retry ({fault})."
    )


def _translate(text, language, config, session_key, label, subject=None):
    """Translate `text`, and `subject` when one is given, piece by piece.

    Returns (translated subject, translated text). The subject travels with
    the first piece; the subject is "" when there is none to translate, and
    whatever the model wrote for a subject the email does not have is dropped.
    """
    client = get_client(config)
    pieces = split_text(text)
    total = len(pieces)

    def run(index):
        piece = pieces[index][0]
        part = (index + 1, total) if total > 1 else None
        if index == 0 and subject is not None:
            def read(payload):
                translated = _field(payload, "translation")
                return (_field(payload, "subject") if subject else "", translated)
            return _call(client, prompts.translate_email_user(subject, piece, language, part),
                         "email_translation", EMAIL_TRANSLATION_SCHEMA, read, session_key, label)
        translated = _call(client, prompts.translate_text_user(piece, language, part),
                           "text_translation", TRANSLATION_SCHEMA,
                           lambda payload: _field(payload, "translation"), session_key, label)
        return ("", translated)

    if total == 1:
        results = [run(0)]
    else:
        log.info("translate %s: %d pieces, translated at once", label, total)
        with ThreadPoolExecutor(max_workers=min(total, MAX_CONCURRENT_PIECES)) as pool:
            results = list(pool.map(run, range(total)))

    joined = "".join(translated + separator
                     for (_, translated), (_, separator) in zip(results, pieces))
    return results[0][0], joined


# --- The check --------------------------------------------------------------

# Where a URL or an address ends is decided in ASCII. Written straight against
# Chinese or Japanese text a link runs into the next character with no space,
# and \b and \w count those characters as letters.
_URL = re.compile(r"(?i)(?<![A-Za-z0-9])(?:https?://|www\.)[A-Za-z0-9\-._~:/?#\[\]@!$&'()*+,;=%]+")
_URL_TRAILING = ".,;:!?'\")]}"
_EMAIL_ADDRESS = re.compile(
    r"(?<![A-Za-z0-9._%+\-])[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,}"
)

# A number: digits, joined across the separators number formats use -- a comma
# or full stop (1,000.50 / 1.000,50), an apostrophe (1'000), or a space before a
# group of exactly three digits (1 000,50). \d matches the digits of every
# script, so ٢٥ and २५ are read too.
_NUMBER = re.compile(r"\d+(?:[.,'\u2019]\d+|[ \u00a0\u202f\u2009]\d{3}(?!\d))*")


def _digits(number):
    """A number's digits in ASCII, every separator dropped."""
    return "".join(str(unicodedata.decimal(ch)) for ch in number if ch.isdecimal())


_MONTH_NUMBERS = {name: number for number, names in enumerate((
    ("jan", "january"), ("feb", "february"), ("mar", "march"), ("apr", "april"),
    ("may",), ("jun", "june"), ("jul", "july"), ("aug", "august"),
    ("sep", "sept", "september"), ("oct", "october"), ("nov", "november"),
    ("dec", "december"),
), start=1) for name in names}


def _named_months(text):
    """The numbers of the months `text` names in words.

    Read from runs of letters, so "14JUL" counts. Only a capitalised word is a
    month: "it may rain" and "to march on" name none (grounding.py draws the
    same line for "may").
    """
    return {
        _MONTH_NUMBERS[word.lower()]
        for word in re.findall(r"[A-Za-z]+", text or "")
        if word[0].isupper() and word.lower() in _MONTH_NUMBERS
    }


def _inventory(text):
    """(URLs, email addresses, {digits: number as first written}) in `text`.

    Links and addresses are lifted out before numbers are read, so the digits
    inside a link are checked as part of the link and not again as numbers.
    """
    urls, addresses = [], []

    def lift(found, trailing=""):
        def replace(match):
            found.append(match.group(0).rstrip(trailing))
            return " "
        return replace

    rest = _URL.sub(lift(urls, _URL_TRAILING), text or "")
    rest = _EMAIL_ADDRESS.sub(lift(addresses), rest)
    numbers = {}
    for match in _NUMBER.finditer(rest):
        numbers.setdefault(_digits(match.group(0)), match.group(0))
    return urls, addresses, numbers


def check_translation(original, translation):
    """Flag every number, link and address that did not survive, either way.

    Deterministic, and blind to which language the translation is in. Returns
    the GroundingResult that summaries and drafts use.
    """
    original = original or ""
    translation = translation or ""
    original_urls, original_addresses, original_numbers = _inventory(original)
    translated_urls, translated_addresses, translated_numbers = _inventory(translation)
    # The one exception (module docstring): a month named in the original may
    # come back as its number. It only ever removes a flag.
    named_months = _named_months(original)

    flags, seen = [], set()

    def flag(claim, reason):
        if (claim, reason) not in seen:
            seen.add((claim, reason))
            flags.append(Flag(claim=claim, reason=reason))

    for digits, written in translated_numbers.items():
        if digits in original_numbers:
            continue
        if len(digits) <= 2 and int(digits) in named_months:
            continue
        flag(written, "number not in the original")
    for digits, written in original_numbers.items():
        if digits not in translated_numbers:
            flag(written, "number missing from the translation")
    for url in original_urls:
        if url not in translation:
            flag(url, "link missing from the translation")
    for url in translated_urls:
        if url not in original:
            flag(url, "link not in the original")
    for address in original_addresses:
        if address not in translation:
            flag(address, "email address missing from the translation")
    for address in translated_addresses:
        if address not in original:
            flag(address, "email address not in the original")

    return GroundingResult(grounded=not flags, flags=flags)


# --- Entry points -----------------------------------------------------------


def translate_email(email, language, config, session_key=None):
    """Translate one SourceEmail. Returns the /api/translate response body."""
    _require_language(language)
    cleaned = preprocess_email(email, config.token_budget_chars, label=f"translate {email.id[:12]}")
    if cleaned.is_empty:
        raise EmptyEmailError(
            "This email has no readable text to translate once quoted replies "
            "and footers are removed."
        )

    subject = (email.subject or "").strip()
    translated_subject, translated_body = _translate(
        cleaned.text, language, config, session_key, label=email.id[:12], subject=subject,
    )
    # The subject is checked with the body: it was translated in the same call,
    # and a figure moved from one to the other has not been lost.
    result = check_translation(f"{subject}\n{cleaned.text}",
                               f"{translated_subject}\n{translated_body}")
    log.info("translate %s into %s: %d chars in, %d chars out, %d flag(s)",
             email.id, language, len(cleaned.text), len(translated_body), len(result.flags))

    return {
        "email_id": email.id,
        "language": language,
        "subject": translated_subject,
        "translation": translated_body,
        "grounded": result.grounded,
        "ungrounded_flags": result.as_api_flags(),
    }


def translate_text(text, language, config, session_key=None):
    """Translate text the client supplied -- a drafted reply."""
    _require_language(language)
    if not isinstance(text, str) or not text.strip():
        raise EmptyEmailError("There is no text to translate.")

    _, translation = _translate(text, language, config, session_key, label="supplied")
    result = check_translation(text, translation)
    log.info("translate %d supplied chars into %s: %d chars out, %d flag(s)",
             len(text), language, len(translation), len(result.flags))
    return {
        "language": language,
        "translation": translation,
        "grounded": result.grounded,
        "ungrounded_flags": result.as_api_flags(),
    }
