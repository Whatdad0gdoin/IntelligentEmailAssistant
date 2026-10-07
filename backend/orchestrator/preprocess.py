"""Preprocessing, run before any prompt is built (spec section 4.2).

Why this exists at all: a reply chain puts three older messages underneath the
one the user is actually looking at, and a model handed the whole blob will
happily summarise the oldest one. Signatures and legal footers add tokens and
proper nouns that then show up in summaries as if they were content. Cleaning
first is cheaper and more reliable than prompting around the mess.

Everything here is deterministic string work. No model is involved, so nothing
in this file can hallucinate.

Logging note (NFR-03): character counts are logged, content never is.
"""

import html as _html
import logging
import re
from dataclasses import dataclass

log = logging.getLogger(__name__)


# --- HTML ------------------------------------------------------------------

_SCRIPT_OR_STYLE = re.compile(r"(?i)<(script|style)\b")
_LINE_BREAK = re.compile(r"(?i)<(?:br|hr)\s*/?>")
_BLOCKS = r"(?:p|div|tr|h[1-6]|ul|ol|table|blockquote)"
_BLOCK_END = re.compile(r"(?i)</(?:" + _BLOCKS + r"|li)\s*>")
# A block starts a line as well as ending one. Without this, an image or a link
# followed by <p>Unsubscribe...</p> came out as one line, and a footer phrase
# that is not at the start of a line is not recognised as one.
_BLOCK_START = re.compile(r"(?i)<" + _BLOCKS + r"\b[^>]*>")
# Where one block closes and the next opens, that is still one line break.
# Counting it twice put a blank line between Outlook-style <div> header lines
# ("From:", "Sent:", ...), and the quoted-history marker needs them adjacent.
_BLOCK_BOUNDARY = re.compile(r"(?i)</(?:" + _BLOCKS + r"|li)\s*>\s*<" + _BLOCKS + r"\b[^>]*>")
_LIST_ITEM = re.compile(r"(?i)<li\b[^>]*>")
_TAG = re.compile(r"(?s)<[^>]+>")
_LOOKS_LIKE_HTML = re.compile(r"(?i)<(?:html|body|div|p|table|br|span)\b")

# An image's alt text is the only wording some marketing emails have: the offer
# is a picture, and its alt attribute says what the picture says. Dropping it
# with the other tags left those emails with no text at all. It is kept as
# "[image: ...]" so a reader can tell it was not prose. alt="" marks a
# decorative image or a tracking pixel by convention, and gives nothing.
_IMG = re.compile(r"(?is)<img\b[^>]*>")
# One attribute at a time, left to right, a quoted value read whole -- so an
# "alt=" inside another attribute's value (a Firebase or Cloud Storage URL ends
# "?alt=media&token=...") is never taken for the image's own alt text.
_ATTRIBUTE = re.compile(r"""([^\s"'<>/=]+)(?:\s*=\s*("[^"]*"|'[^']*'|[^\s"'>]+))?""")
_MAX_ALT_CHARS = 200


def _alt_value(tag):
    """The alt attribute of an <img ...> tag, or None."""
    for attribute in _ATTRIBUTE.finditer(tag, 4):   # past "<img"
        if attribute.group(1).lower() == "alt":
            value = attribute.group(2) or ""
            return value[1:-1] if value[:1] in ("'", '"') else value
    return None


def _alt_text(match):
    value = _alt_value(match.group(0))
    if value is None:
        return " "
    value = re.sub(r"\s+", " ", _html.unescape(value)).strip()[:_MAX_ALT_CHARS]
    if not any(ch.isalnum() for ch in value):
        return " "
    # Escaped again because the tag stripper runs next and the whole text is
    # unescaped once at the end: a literal "<" in the alt text must not be
    # taken for the start of a tag and eat the words after it.
    return f" [image: {_html.escape(value, quote=False)}] "


_CLOSING = {"script": re.compile(r"(?i)</script\s*>"), "style": re.compile(r"(?i)</style\s*>")}


def _drop_scripts_and_styles(text):
    """Remove <script> and <style> elements, contents included, in one pass.

    The regex this replaces searched to the end of the text for a closing tag
    from every opening one that had none, so ten thousand unclosed tags took
    several seconds. Here each kind is searched for at most once after it is
    found unclosed. An unclosed one is left for the tag stripper, as before:
    dropping everything after it would lose the email's text with the junk.
    """
    kept, position, unclosed = [], 0, set()
    while True:
        opening = _SCRIPT_OR_STYLE.search(text, position)
        if opening is None:
            kept.append(text[position:])
            break
        name = opening.group(1).lower()
        closing = None if name in unclosed else _CLOSING[name].search(text, opening.end())
        if closing is None:
            unclosed.add(name)
            kept.append(text[position:opening.end()])
            position = opening.end()
            continue
        kept.append(text[position:opening.start()] + " ")
        position = closing.end()
    return "".join(kept)


def html_to_text(raw):
    """Flatten HTML into readable plain text.

    A full HTML parser is not warranted here: the output is only ever fed to a
    model and to the grounding checker, both of which want prose, not
    structure. What matters is that block boundaries survive as line breaks so
    sentences do not run together -- if they did, the grounding checker would
    split sentences in the wrong places.
    """
    if not raw:
        return ""
    text = _drop_scripts_and_styles(raw)
    # Every tag pattern below needs a closing ">". After the last one in the
    # text no "<" can start a tag, and leaving the patterns to find that out
    # from each "<" in turn is quadratic: 100 KB of "<" took eight seconds, on
    # every inbox load. So tags are only looked for up to the last ">".
    last = text.rfind(">")
    text, rest = text[:last + 1], text[last + 1:]
    text = _IMG.sub(_alt_text, text)
    text = _LINE_BREAK.sub("\n", text)
    text = _BLOCK_BOUNDARY.sub("\n", text)
    text = _LIST_ITEM.sub("\n- ", text)
    text = _BLOCK_START.sub("\n", text)
    text = _BLOCK_END.sub("\n", text)
    text = _TAG.sub(" ", text) + rest
    text = _html.unescape(text)
    text = text.replace(" ", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def looks_like_html(raw):
    return bool(_LOOKS_LIKE_HTML.search(raw or ""))


# --- Quoted history and forwarded chains -----------------------------------

# Each pattern marks the point where the *current* message ends and quoted
# history begins. The earliest match in the body wins.
_HISTORY_MARKERS = (
    # "On Mon, 24 Aug 2026 at 16:02, Someone <a@b> wrote:" -- may wrap lines.
    re.compile(r"(?ims)^[ \t>]*on\s.{0,400}?\bwrote:[ \t]*$"),
    re.compile(r"(?im)^[ \t>]*-{2,}[ \t]*original message[ \t]*-{2,}[ \t]*$"),
    re.compile(r"(?im)^[ \t>]*-{2,}[ \t]*forwarded message[ \t]*-{2,}[ \t]*$"),
    re.compile(r"(?im)^[ \t>]*begin forwarded message:[ \t]*$"),
    # The horizontal rule Outlook puts above a quoted block.
    re.compile(r"(?m)^[ \t>]*_{10,}[ \t]*$"),
    # A header block pasted inside the body: From: followed by its siblings.
    re.compile(
        r"(?im)^[ \t>]*from:[ \t]*\S.*$(?:\r?\n[ \t>]*(?:sent|date|to|cc|subject)[ \t]*:.*$){1,4}"
    ),
    # A run of two or more quoted lines. One stray "> " can be a quotation
    # inside otherwise original prose; a run of them is a chain.
    re.compile(r"(?m)^[ \t]*>.*$(?:\r?\n[ \t]*>.*$)+"),
)

_STRAY_QUOTE_LINE = re.compile(r"(?m)^[ \t]*>.*$\r?\n?")


def strip_quoted_history(text):
    """Cut the body at the first quoted-history marker."""
    if not text:
        return ""
    cut = len(text)
    for pattern in _HISTORY_MARKERS:
        match = pattern.search(text)
        if match is not None and match.start() < cut:
            cut = match.start()
    trimmed = text[:cut]
    # Any lone quoted line above the cut goes too.
    return _STRAY_QUOTE_LINE.sub("", trimmed).strip()


# --- Signatures and legal footers ------------------------------------------

# RFC 3676 signature delimiter: a line containing exactly "-- ".
_SIG_DELIMITER = re.compile(r"(?m)^-- ?[ \t]*$")

_FOOTER_PHRASES = re.compile(
    r"(?im)^[ \t]*(?:"
    r"sent from my |"
    r"unsubscribe\b|"
    r"manage (?:your )?preferences|"
    r"view this email in your browser|"
    r"you are receiving this|"
    r"you.re receiving this|"
    r"this (?:e-?mail|message) (?:and any attachments |was sent )|"
    r"confidentiality notice|"
    r"if you are not the intended recipient|"
    r"to stop receiving|"
    r"privacy policy\b|"
    r"(?:copyright )?(?:©|\(c\)) ?\d{4}"
    r")"
)

# Words only footers use. Legal and list-management prose keeps using them
# after its opening phrase ("confidential", "intended recipient", "update your
# preferences"); an offer, a digest or a reply does not.
_FOOTER_VOCABULARY = re.compile(
    r"(?i)(?:\b(?:unsubscribe\w*|opt[- ]?(?:out|in)|subscri(?:be|bed|ber|bers|ption|ptions)|"
    r"mailing (?:list|address)|preferences|privacy|confidential\w*|privileged|"
    r"intended (?:solely|only|recipient)|addressee|disclos\w*|prohibited|"
    r"rights reserved|copyright|receiving this|notify the sender)\b|©)"
)
# Text after a footer phrase at least this long, and free of that vocabulary,
# is the message carrying on, not its footer.
_FOOTER_CONTENT_CHARS = 60

_SIGNOFF = re.compile(
    r"(?im)^[ \t]*(?:best regards|kind regards|warm regards|warmest regards|"
    r"best wishes|regards|best|thanks(?: again)?|thank you|many thanks|cheers|"
    r"sincerely|yours sincerely|yours faithfully|talk soon|speak soon)"
    r"[,.!]?[ \t]*$"
)

# A sign-off only counts as one when what follows looks like a name block:
# a few short lines and then the end of the message.
_MAX_SIGNATURE_LINES = 5
_MAX_SIGNATURE_LINE_CHARS = 90
_NON_EMPTY_LINE = re.compile(r"(?m)^[ \t]*\S")


def _cut_at(text, pattern):
    match = pattern.search(text)
    return text[: match.start()] if match else text


def _cut_footer(text):
    """Cut at the first footer phrase that the rest of the message bears out.

    The phrase alone is not enough. Marketing mail opens with "View this email
    in your browser" and puts "Unsubscribe | Privacy policy" in a bar above the
    offer, and cutting at the first such line threw the whole email away. So a
    phrase starts the footer only when what follows it -- up to the next footer
    phrase, or the end -- is footer too: short, or written in footer
    vocabulary. When real content follows instead, only the phrase's own line
    is dropped.

    Phrase lines with nothing but blank lines between them are judged as one
    run, by what follows the last of them: a header bar is often two such lines
    ("View this email in your browser", then "Unsubscribe | Preferences"), and
    judging the first by the second alone would cut the offer beneath both.

    This never keeps less than cutting at the first phrase did: the cut can
    only move later, and every dropped line sits before it.
    """
    def line_end(position):
        end = text.find("\n", position)
        return len(text) if end == -1 else end

    matches = list(_FOOTER_PHRASES.finditer(text))
    kept, start, cut = [], 0, len(text)
    i = 0
    while i < len(matches):
        last = i
        run_end = line_end(matches[i].end())
        while last + 1 < len(matches) and not text[run_end:matches[last + 1].start()].strip():
            last += 1
            run_end = line_end(matches[last].end())
        following_end = matches[last + 1].start() if last + 1 < len(matches) else len(text)
        following = text[run_end:following_end]
        if (len(following.strip()) >= _FOOTER_CONTENT_CHARS
                and not _FOOTER_VOCABULARY.search(following)):
            kept.append(text[start:matches[i].start()])
            start = run_end
            i = last + 1
            continue
        cut = matches[i].start()
        break
    kept.append(text[start:cut])
    return "".join(kept)


def strip_signature(text):
    """Remove trailing signature blocks and legal footers.

    Deliberately conservative on the sign-off heuristic. Cutting at every
    "Thanks," would delete real content from messages that end mid-sentence, so
    a sign-off only counts when the lines beneath it are short and few -- the
    shape of a name and a job title, not the shape of a paragraph.
    """
    if not text:
        return ""
    text = _cut_at(text, _SIG_DELIMITER)
    text = _cut_footer(text)

    # A sign-off counts only with at most _MAX_SIGNATURE_LINES lines beneath
    # it, so it can only be one of the last few lines. Searching from there
    # finds the same one, and keeps a body of thirty thousand "Thanks" lines
    # from taking most of a minute.
    starts = [line.start() for line in _NON_EMPTY_LINE.finditer(text)]
    window = starts[-(_MAX_SIGNATURE_LINES + 1)] if len(starts) > _MAX_SIGNATURE_LINES else 0
    for match in _SIGNOFF.finditer(text, window):
        tail = text[match.end():]
        lines = [line.strip() for line in tail.splitlines() if line.strip()]
        if len(lines) <= _MAX_SIGNATURE_LINES and all(
            len(line) <= _MAX_SIGNATURE_LINE_CHARS for line in lines
        ):
            text = text[: match.start()]
            break
    return text.strip()


# --- Whitespace and truncation ---------------------------------------------


def normalise_whitespace(text):
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace(" ", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def truncate_from_top(text, budget_chars):
    """Keep the first `budget_chars` characters, cut on a whitespace boundary.

    Measured from the top because that is where the message the user is looking
    at lives -- mail clients stack older content underneath. Truncating from the
    bottom would keep the least relevant half.
    """
    if budget_chars <= 0 or len(text) <= budget_chars:
        return text, False
    window = text[:budget_chars]
    boundary = max(window.rfind("\n"), window.rfind(" "))
    if boundary > budget_chars * 0.6:
        window = window[:boundary]
    return window.rstrip(), True


# --- Entry point -----------------------------------------------------------


@dataclass(frozen=True)
class Preprocessed:
    """Cleaned body plus the counts we are allowed to log."""

    text: str
    original_chars: int
    final_chars: int
    truncated: bool

    @property
    def is_empty(self):
        return not self.text.strip()


def preprocess(raw_body, budget_chars, is_html=None, label=""):
    """Clean one message body. Returns a Preprocessed."""
    raw_body = raw_body or ""
    original_chars = len(raw_body)

    if is_html is None:
        is_html = looks_like_html(raw_body)
    text = html_to_text(raw_body) if is_html else raw_body

    text = normalise_whitespace(text)
    text = strip_quoted_history(text)
    text = strip_signature(text)
    text = normalise_whitespace(text)
    text, truncated = truncate_from_top(text, budget_chars)

    log.info(
        "preprocess%s: %d chars in, %d chars out, html=%s, truncated=%s",
        f" [{label}]" if label else "",
        original_chars,
        len(text),
        is_html,
        truncated,
    )
    return Preprocessed(
        text=text,
        original_chars=original_chars,
        final_chars=len(text),
        truncated=truncated,
    )


def preprocess_email(email, budget_chars, label=""):
    """Clean the body a reader would see: the plain-text part, or the HTML part
    when the plain text is empty -- before cleaning or after it.

    Marketing mail often pairs its HTML with a one-line text/plain stub ("View
    this email in your browser: <link>"). The stub is not empty, so it was the
    part chosen, and cleaning then removed it as a footer: the email reached
    the classifier, the summariser and the inbox snippet as nothing at all,
    while the HTML and its image alt text were never looked at.

    `email` is anything with `body_text` and `body_html` (a SourceEmail).
    """
    text = email.body_text or ""
    html = email.body_html or ""
    if text.strip():
        cleaned = preprocess(text, budget_chars, is_html=False, label=label)
        if not cleaned.is_empty or not html.strip():
            return cleaned
        log.info("preprocess%s: plain-text part empty once cleaned; using the HTML part",
                 f" [{label}]" if label else "")
    return preprocess(html, budget_chars, is_html=True, label=label)


def snippet(text, max_chars):
    """A short single-line preview, cut on a word boundary."""
    flat = re.sub(r"\s+", " ", text or "").strip()
    if len(flat) <= max_chars:
        return flat
    window = flat[:max_chars]
    space = window.rfind(" ")
    if space > max_chars * 0.5:
        window = window[:space]
    return window.rstrip() + "…"
