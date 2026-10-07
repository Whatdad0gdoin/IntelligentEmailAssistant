"""Marketing mail survives preprocessing (preprocess.py).

Three ways a promotional email used to reach the classifier, the summariser and
the inbox snippet as nothing at all:

* its offer was a picture, and the picture's alt text went with the tags;
* its text/plain part was a one-line "View this email in your browser" stub,
  which was chosen over the HTML because it was not empty, and then removed as
  a footer;
* its first line, or a link bar above the offer, matched a footer phrase, and
  the body was cut there.

These call the production functions on real strings. No model, no stub, except
where a route is driven end to end.
"""

import os
import random
import time
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser

import pytest

from backend.adapters.headers import parse_message
from backend.orchestrator.preprocess import (
    _FOOTER_PHRASES,
    _cut_at,
    _cut_footer,
    html_to_text,
    preprocess,
    preprocess_email,
    strip_signature,
)

BUDGET = 12000
OFFER = "50% OFF all laptops - ends Sunday 11:59pm"


# --- Image alt text -------------------------------------------------------------


def test_an_image_keeps_its_alt_text():
    html = f'<p>This weekend</p><a href="https://shop.example"><img src="cid:b1" alt="{OFFER}"></a>'
    assert f"[image: {OFFER}]" in html_to_text(html)


@pytest.mark.parametrize("img", [
    '<img src="https://t.example/open.gif" width="1" height="1" alt="">',   # tracking pixel
    '<img src="spacer.gif">',                                               # no alt at all
    '<img src="rule.png" alt=" - ">',                                       # punctuation only
])
def test_decorative_images_add_nothing(img):
    assert html_to_text(f"<p>Hello</p>{img}<p>World</p>").split() == ["Hello", "World"]


def test_alt_text_is_decoded_once():
    assert "[image: Tom & Jerry]" in html_to_text('<img alt="Tom &amp; Jerry">')


def test_a_less_than_sign_in_alt_text_does_not_swallow_what_follows():
    """The tag stripper runs after the alt text is inserted. A raw "<" left in
    it would read as the start of a tag running to the next ">"."""
    text = html_to_text('<img alt="Price < $50 today"><p>Shop the range now</p>')
    assert "[image: Price < $50 today]" in text
    assert "Shop the range now" in text


@pytest.mark.parametrize("img, expected", [
    ("<img alt='Single quoted'>", "[image: Single quoted]"),
    ("<img alt=Unquoted src=x.png>", "[image: Unquoted]"),
    ('<IMG SRC="x.png" ALT="Upper case">', "[image: Upper case]"),
])
def test_alt_attribute_spellings(img, expected):
    assert expected in html_to_text(img)


def test_another_attribute_ending_in_alt_is_not_the_alt_text():
    assert "tracking" not in html_to_text('<img data-alt="tracking-id-123" src="x.png">')


@pytest.mark.parametrize("img, expected", [
    # Firebase and Cloud Storage image URLs end "?alt=media&token=...".
    ('<img src="https://firebasestorage.googleapis.com/b/banner.png?alt=media&amp;token=9f2c"'
     ' alt="Summer sale: 40% off all shoes">', "[image: Summer sale: 40% off all shoes]"),
    ('<img src="https://t.example/open.gif?alt=json&amp;uid=12345" alt="">', ""),
    ('<img title="see alt=Hidden" src="x.png">', ""),
    ("<img src=https://x.example/a.png?alt=media alt=Real>", "[image: Real]"),
])
def test_alt_inside_another_attribute_is_not_the_alt_text(img, expected):
    assert html_to_text(img) == expected


def test_long_alt_text_is_bounded():
    text = html_to_text(f'<img alt="{"word " * 200}">')
    assert len(text) < 260


# --- The footer cut --------------------------------------------------------------


def test_a_view_in_browser_header_does_not_wipe_the_email():
    body = ("View this email in your browser\n"
            "SPRING SALE - 40% off all hoodies this weekend only.\n"
            "Shop now at example-store.test. Free shipping over $50.\n"
            "Unsubscribe | Manage preferences | Privacy policy\n")
    cleaned = strip_signature(body)
    assert "SPRING SALE - 40% off all hoodies" in cleaned
    assert "Free shipping over $50." in cleaned
    assert "View this email" not in cleaned
    assert "Unsubscribe" not in cleaned


def test_a_header_bar_of_two_footer_lines_is_one_unit():
    """Judging the first line by the second alone found nothing between them
    and cut the offer beneath both."""
    body = ("View this email in your browser\n"
            "Unsubscribe | Manage preferences\n"
            "SPRING SALE - 40% off all hoodies this weekend only.\n"
            "Shop now at example-store.test. Free shipping over $50 on all orders.\n"
            "Unsubscribe\n")
    assert strip_signature(body) == (
        "SPRING SALE - 40% off all hoodies this weekend only.\n"
        "Shop now at example-store.test. Free shipping over $50 on all orders.")


def test_a_link_bar_above_the_content_is_dropped_not_cut_at():
    body = ("Hi Max,\nYour weekly digest from UniSkills is here.\n"
            "Privacy Policy | Terms\n"
            "3 new internships match your profile: Data Analyst Intern (Melbourne).\n"
            "You are receiving this because you signed up at uniskills.test\n")
    cleaned = strip_signature(body)
    assert "Data Analyst Intern (Melbourne)" in cleaned
    assert "Privacy Policy" not in cleaned
    assert "You are receiving this" not in cleaned


def test_a_legal_notice_over_several_lines_is_still_cut_whole():
    """Its second phrase follows more than a line of prose, but the prose is
    legal vocabulary, so the notice is footer from its first line."""
    body = ("Please find the revised schedule attached.\n\n"
            "Confidentiality notice\n"
            "This message contains information which may be confidential and privileged.\n"
            "Unless you are the addressee you may not use, copy or disclose it.\n"
            "If you are not the intended recipient, please notify the sender and delete it.\n")
    assert strip_signature(body) == "Please find the revised schedule attached."


def test_a_list_footer_with_a_postal_address_is_cut_whole():
    body = ("Our autumn range is in store now.\n\n"
            "You are receiving this email because you opted in at our website.\n"
            "Our mailing address is:\nExample Store, 1 Collins St, Melbourne VIC 3000\n\n"
            "Want to change how you receive these emails?\n"
            "You can update your preferences or unsubscribe from this list.\n")
    assert strip_signature(body) == "Our autumn range is in store now."


def test_a_footer_phrase_with_nothing_after_it_still_cuts():
    assert strip_signature("See you at 6.\n\nSent from my iPhone") == "See you at 6."


def _old_cut(text):
    return _cut_at(text, _FOOTER_PHRASES)


FOOTER_LINES = [
    "Unsubscribe | Manage preferences",
    "View this email in your browser",
    "Privacy policy",
    "You are receiving this because you subscribed.",
    "Confidentiality notice",
    "© 2026 Example Pty Ltd",
    "Sent from my phone",
]
CONTENT_LINES = [
    "The quarterly figures are attached for your review before Friday.",
    "SPRING SALE: 40% off every hoodie in the store this weekend only.",
    "Can you send me the address for Saturday? I lost the invitation.",
    "short line",
    "This message contains information which may be confidential.",
    "",
]


def test_the_new_cut_never_keeps_less_than_the_old_one():
    """Whatever the mix of lines, the old result is a prefix of the new one."""
    rng = random.Random(3164)
    for _ in range(3000):
        lines = [rng.choice(FOOTER_LINES + CONTENT_LINES) for _ in range(rng.randint(1, 9))]
        text = "\n".join(lines)
        assert _cut_footer(text).startswith(_old_cut(text)), text


# --- HTML structure the other cleaning steps depend on -----------------------------


def test_quoted_history_in_separate_divs_is_still_cut():
    """Outlook-style header lines, one <div> each. Counting the boundary
    between two blocks as two line breaks put a blank line between "From:"
    and "Sent:", and the quoted-history marker needs them adjacent."""
    html = ("<div>Sounds good, see you then.</div>"
            "<div><b>From:</b> Alice &lt;alice@x.com&gt;</div>"
            "<div><b>Sent:</b> Monday, 5 October 2026 9:00 AM</div>"
            "<div><b>To:</b> Bob</div><div><b>Subject:</b> Lunch</div>"
            "<div>QUOTED-HISTORY: the budget is $50,000.</div>")
    assert preprocess(html, BUDGET, is_html=True).text == "Sounds good, see you then."


def test_an_unclosed_style_keeps_the_text_after_it():
    """Dropping everything after it would lose the email with the junk."""
    assert "World" in html_to_text("<p>Hello</p><style>.x{color:red}<p>World</p>")
    assert html_to_text("<p>Hello</p><script>track()</script><p>World</p>").split() == ["Hello", "World"]


HOSTILE_BODIES = {
    "100 KB of <": ("<" * 100_000, True),               # 8 s before the fix, on every inbox load
    "unclosed img tags": ("<img x" * 20_000, True),     # 4 s
    "unclosed script tags": ("<script " * 10_000, True),  # 5.5 s
    "20k sign-off lines": ("Thanks\n" * 20_000, False),  # about 20 s: every sign-off was tried
}


@pytest.mark.parametrize("name", sorted(HOSTILE_BODIES))
def test_hostile_bodies_are_cleaned_in_linear_time(name):
    """One email like these stalled every inbox load, because the inbox
    cleans every body on every load. The bound is loose: the fixed code takes
    well under a tenth of a second on each."""
    body, is_html = HOSTILE_BODIES[name]
    start = time.perf_counter()
    preprocess(body, BUDGET, is_html=is_html)
    assert time.perf_counter() - start < 2.0


# --- Choosing the part: plain text, or HTML when the plain text cleans to nothing --


class _Parts:
    def __init__(self, text, html):
        self.body_text, self.body_html = text, html


STUB = "View this email in your browser: https://megastore.example/v/123"
PROMO_HTML = (f'<html><body><img src="cid:banner1" alt="{OFFER}">'
              '<p style="font-size:10px">Unsubscribe | Privacy policy</p></body></html>')


def test_a_stub_plain_part_falls_back_to_the_html():
    assert preprocess_email(_Parts(STUB, PROMO_HTML), BUDGET).text == f"[image: {OFFER}]"


def test_a_real_plain_part_is_still_preferred():
    cleaned = preprocess_email(_Parts("Lunch on Friday at 1?", PROMO_HTML), BUDGET)
    assert cleaned.text == "Lunch on Friday at 1?"


def test_an_empty_plain_part_uses_the_html():
    assert preprocess_email(_Parts("  \n", PROMO_HTML), BUDGET).text == f"[image: {OFFER}]"


def test_a_plain_part_that_cleans_to_nothing_without_html_stays_empty():
    assert preprocess_email(_Parts(STUB, ""), BUDGET).is_empty


def test_html_looking_plain_text_is_still_read_as_plain_text():
    """Unchanged from before: the part's type decides, not its look."""
    assert "a <b> c" in preprocess_email(_Parts("a <b> c and more text", ""), BUDGET).text


def _image_only_promo(message_id="img-only-1@megastore.example"):
    m = EmailMessage()
    m["From"] = "MegaStore <deals@megastore.example>"
    m["To"] = "student@monash.edu"
    m["Subject"] = "This weekend only"
    m["Date"] = "Mon, 05 Oct 2026 09:00:00 +1100"
    m["Message-ID"] = f"<{message_id}>"
    m.set_content(STUB)
    m.add_alternative(PROMO_HTML, subtype="html")
    m.get_payload()[1].add_related(b"\x89PNG\r\n\x1a\n" + b"\x00" * 64, maintype="image",
                                   subtype="png", cid="<banner1>")
    return m


def test_an_image_only_promotion_parsed_from_mime_has_words():
    parsed = BytesParser(policy=policy.default).parsebytes(_image_only_promo().as_bytes())
    email = parse_message(parsed)
    assert preprocess(email.raw_body, BUDGET, is_html=email.is_html).is_empty   # what happened before
    assert preprocess_email(email, BUDGET).text == f"[image: {OFFER}]"


# --- Through the API ---------------------------------------------------------------


def _deliver(tmp_path, message, name="promo.eml"):
    mailbox = tmp_path / "mailbox"
    os.makedirs(mailbox, exist_ok=True)
    (mailbox / name).write_bytes(message.as_bytes())


def test_the_inbox_snippet_and_the_summary_prompt_see_the_offer(client, auth_headers, stub_llm, tmp_path):
    _deliver(tmp_path, _image_only_promo())
    stub_llm.queue({"results": []})   # labels are not the point here
    response = client.get("/api/inbox", headers=auth_headers)
    emails = [e for group in response.get_json()["groups"].values() for e in group]
    promo = next(e for e in emails if e["id"] == "img-only-1@megastore.example")
    assert promo["snippet"] == f"[image: {OFFER}]"
    assert OFFER in stub_llm.calls[0]["user"]   # the classification prompt

    stub_llm.queue({"summary": ["The store is offering 50% off all laptops.",
                                "The offer ends on Sunday."],
                    "action_items": []})
    response = client.post("/api/summarise", json={"email_id": "img-only-1@megastore.example"},
                           headers=auth_headers)
    assert response.status_code == 200, response.get_json()
    assert OFFER in stub_llm.calls[-1]["user"]
