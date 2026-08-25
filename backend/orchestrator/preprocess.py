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

_SCRIPT_STYLE = re.compile(r"(?is)<(script|style)\b.*?</\1>")
_LINE_BREAK = re.compile(r"(?i)<(?:br|hr)\s*/?>")
_BLOCK_END = re.compile(r"(?i)</(?:p|div|tr|li|h[1-6]|ul|ol|table|blockquote)\s*>")
_LIST_ITEM = re.compile(r"(?i)<li\b[^>]*>")
_TAG = re.compile(r"(?s)<[^>]+>")
_LOOKS_LIKE_HTML = re.compile(r"(?i)<(?:html|body|div|p|table|br|span)\b")


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
    text = _SCRIPT_STYLE.sub(" ", raw)
    text = _LINE_BREAK.sub("\n", text)
    text = _LIST_ITEM.sub("\n- ", text)
    text = _BLOCK_END.sub("\n", text)
    text = _TAG.sub(" ", text)
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


def _cut_at(text, pattern):
    match = pattern.search(text)
    return text[: match.start()] if match else text


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
    text = _cut_at(text, _FOOTER_PHRASES)

    for match in _SIGNOFF.finditer(text):
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
