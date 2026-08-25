"""Preprocessing tests (spec section 8: reply chain, forwarded chain, HTML).

These call the production functions on real strings. No model, no stub.
"""

from backend.orchestrator.preprocess import (
    html_to_text,
    preprocess,
    snippet,
    strip_quoted_history,
    strip_signature,
    truncate_from_top,
)

BUDGET = 12000


# --- Reply chains ----------------------------------------------------------

REPLY_CHAIN = """Can we move the meeting to Friday at 2pm?

Best regards,
David

On Mon, 24 Aug 2026 at 16:02, Student <student@monash.edu> wrote:

> Thursday at 11am still suits me.
>
> On Mon, 24 Aug 2026 at 09:15, David <d@northgate.com.au> wrote:
>
> > Confirming Thursday at 11am.
"""


def test_reply_chain_keeps_only_the_newest_message():
    result = preprocess(REPLY_CHAIN, BUDGET)
    assert "Friday at 2pm" in result.text
    assert "11am" not in result.text
    assert "wrote:" not in result.text
    assert ">" not in result.text


def test_reply_chain_is_the_reason_this_matters():
    """The whole point: the model must not summarise the older message.

    Without the cut, "Thursday at 11am" is in the text twice and "Friday at
    2pm" once, and a summariser will happily report the wrong meeting.
    """
    assert REPLY_CHAIN.count("11am") == 2
    assert preprocess(REPLY_CHAIN, BUDGET).text.count("11am") == 0


def test_outlook_original_message_marker():
    text = "Here is the update.\n\n-----Original Message-----\nFrom: Someone\nOld content here."
    assert strip_quoted_history(text) == "Here is the update."


def test_outlook_underscore_divider():
    text = "Here is the update.\n\n" + "_" * 32 + "\nFrom: Someone\nOld content."
    assert strip_quoted_history(text) == "Here is the update."


def test_pasted_header_block_inside_the_body():
    text = (
        "Please see below.\n\n"
        "From: Someone <s@example.com>\n"
        "Sent: Monday, 24 August 2026 09:15\n"
        "To: Student\n"
        "Subject: Old thread\n\n"
        "The old message body."
    )
    assert strip_quoted_history(text) == "Please see below."


def test_forwarded_chain():
    text = (
        "Thought you should see this.\n\n"
        "---------- Forwarded message ----------\n"
        "From: Someone <s@example.com>\n"
        "The forwarded content."
    )
    assert strip_quoted_history(text) == "Thought you should see this."


def test_begin_forwarded_message_variant():
    text = "FYI.\n\nBegin forwarded message:\n\nFrom: Someone\nContent."
    assert strip_quoted_history(text) == "FYI."


def test_a_single_quoted_line_is_not_treated_as_a_chain():
    """One "> " line inside original prose is a quotation, not a reply chain.

    Cutting here would throw away the sentence that follows it.
    """
    text = "She wrote:\n\n> a short quotation\n\nand I agree with that entirely."
    result = strip_quoted_history(text)
    assert "I agree with that entirely" in result


# --- Signatures and footers ------------------------------------------------


def test_rfc_signature_delimiter():
    text = "The actual message.\n\n-- \nJane Doe\nSenior Engineer"
    assert strip_signature(text) == "The actual message."


def test_signoff_block_is_removed():
    text = "Please review the draft.\n\nBest regards,\nDavid Robinson\nOperations Manager"
    assert strip_signature(text) == "Please review the draft."


def test_legal_footer_is_removed():
    text = (
        "Your account was accessed.\n\n"
        "This email and any attachments are confidential and intended solely "
        "for the addressee."
    )
    assert strip_signature(text) == "Your account was accessed."


def test_unsubscribe_footer_is_removed():
    text = "Sale ends soon.\n\nUnsubscribe | Manage preferences"
    assert strip_signature(text) == "Sale ends soon."


def test_signoff_heuristic_does_not_eat_real_content():
    """"Thanks" followed by paragraphs is not a signature.

    The conservative condition exists because cutting here would delete the
    substance of the email.
    """
    text = (
        "Thanks\n\n"
        "for sending that through. I have gone over the numbers in detail and "
        "there are a few things that need to change before we can sign off on "
        "the final version of this report.\n\n"
        "The second issue is the timeline, which does not allow enough room "
        "for the review cycle we agreed to at the start of the project."
    )
    assert "timeline" in strip_signature(text)


# --- HTML ------------------------------------------------------------------

HTML_EMAIL = """<html><head><style>.a{color:red}</style></head><body>
<h1>Big Sale</h1>
<p>Up to <strong>60% off</strong> everything.</p>
<ul><li>Laptops from $899</li><li>Headphones from $79</li></ul>
<script>track();</script>
<p>Ends in 48 hours. Don&rsquo;t miss out.</p>
</body></html>"""


def test_html_is_flattened_to_text():
    text = html_to_text(HTML_EMAIL)
    assert "<" not in text and ">" not in text
    assert "Big Sale" in text
    assert "60% off" in text
    assert "$899" in text


def test_html_script_and_style_content_is_dropped():
    text = html_to_text(HTML_EMAIL)
    assert "track()" not in text
    assert "color:red" not in text


def test_html_entities_are_decoded():
    assert "’" in html_to_text("<p>Don&rsquo;t</p>")


def test_html_block_boundaries_become_line_breaks():
    """Without this, "Big SaleUp to 60% off" would run together as one word."""
    text = html_to_text("<p>First sentence.</p><p>Second sentence.</p>")
    assert "First sentence." in text
    assert "Second sentence." in text
    assert "sentence.Second" not in text


def test_html_is_autodetected():
    result = preprocess(HTML_EMAIL, BUDGET)
    assert "<p>" not in result.text
    assert "Big Sale" in result.text


def test_plain_text_is_not_treated_as_html():
    text = "A plain message with a < b and c > d in it."
    assert "a < b" in preprocess(text, BUDGET).text


# --- Truncation ------------------------------------------------------------


def test_truncation_keeps_the_top_not_the_bottom():
    """Section 4.2: truncate from the top.

    Mail clients stack older content underneath, so the top is the message the
    user is actually looking at.
    """
    text = "FIRSTPART " * 50 + "LASTPART " * 50
    result, truncated = truncate_from_top(text, 200)
    assert truncated is True
    assert "FIRSTPART" in result
    assert "LASTPART" not in result
    assert len(result) <= 200


def test_short_text_is_not_truncated():
    result, truncated = truncate_from_top("short", 200)
    assert result == "short"
    assert truncated is False


def test_truncation_is_reported_on_the_result():
    result = preprocess("word " * 5000, 200)
    assert result.truncated is True
    assert result.final_chars <= 200
    assert result.original_chars == 25000


# --- Counts and snippets ---------------------------------------------------


def test_character_counts_are_recorded():
    result = preprocess(REPLY_CHAIN, BUDGET)
    assert result.original_chars == len(REPLY_CHAIN)
    assert result.final_chars == len(result.text)
    assert result.final_chars < result.original_chars


def test_empty_body_is_reported_not_guessed():
    assert preprocess("", BUDGET).is_empty is True
    assert preprocess("> only quoted content\n> more quoted", BUDGET).is_empty is True


def test_snippet_is_single_line_and_bounded():
    result = snippet("A line.\nAnother line.\n\nAnd more text after that.", 20)
    assert "\n" not in result
    assert len(result) <= 21  # plus the ellipsis
