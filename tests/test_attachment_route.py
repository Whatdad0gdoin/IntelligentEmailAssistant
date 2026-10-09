"""GET /api/inbox/<id>/attachments/<index> (backend/routes/attachments.py).

The one route that serves attachment bytes, so that the person signed in can
open what the inbox lists. Everything it serves was chosen by whoever sent the
email and comes from the application's own origin, so half of this file is
about what the route refuses to do: render a sender's HTML or SVG, let a file
name write a header, or let a browser guess a type.

The other half holds the rest of the attachment promise in place. Opening an
attachment must not send anything to a model, write a file name or a byte of
content to a log, or put anything on disk.
"""

import logging
import os
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser

import pytest

from backend.adapters.headers import INLINE_IMAGE_MIN_BYTES
from backend.routes.attachments import INLINE_TYPES
from tests.conftest import TEST_EMAIL, WORK_EMAIL_ID

CONTENT_MARKER = "ATTACHMENT-CONTENT-MUST-NOT-LEAVE"
EMAIL_ID = "open@example.org"
PDF = b"%PDF-1.4 " + CONTENT_MARKER.encode()
PNG = b"\x89PNG\r\n\x1a\n" + b"p" * 64


def _message(message_id=EMAIL_ID):
    message = EmailMessage()
    message["From"] = "Grace Hopper <grace@example.org>"
    message["To"] = "you@example.com"
    message["Subject"] = "Assignment brief"
    message["Date"] = "Tue, 02 Sep 2026 09:30:00 +1000"
    message["Message-ID"] = f"<{message_id}>"
    message.set_content("The brief is attached.")
    return message


def _deliver(tmp_path, message, name="open.eml"):
    """Drop a message into the local mailbox the fixture source also reads."""
    mailbox = tmp_path / "mailbox"
    os.makedirs(mailbox, exist_ok=True)
    (mailbox / name).write_bytes(message.as_bytes())


def _url(index, email_id=EMAIL_ID):
    return f"/api/inbox/{email_id}/attachments/{index}"


@pytest.fixture
def brief(tmp_path):
    """One email carrying a PDF, a text file and a picture, in that order."""
    message = _message()
    message.add_attachment(PDF, maintype="application", subtype="pdf",
                           filename="SECRET-NAME-brief.pdf")
    message.add_attachment(CONTENT_MARKER, filename="rubric.txt")
    message.add_attachment(PNG, maintype="image", subtype="png", filename="diagram.png")
    _deliver(tmp_path, message)
    return message


def _serve_one(client, auth_headers, tmp_path, data, maintype, subtype, filename):
    """Deliver an email with a single attachment and open that attachment."""
    message = _message()
    message.add_attachment(data, maintype=maintype, subtype=subtype, filename=filename)
    _deliver(tmp_path, message)
    return client.get(_url(0), headers=auth_headers)


# --- it serves the file ------------------------------------------------------------


def test_a_pdf_comes_back_byte_for_byte(client, auth_headers, brief):
    response = client.get(_url(0), headers=auth_headers)
    assert response.status_code == 200
    assert response.data == PDF
    assert response.headers["Content-Type"] == "application/pdf"
    assert response.headers["Content-Disposition"].startswith("inline;")


def test_a_text_file_comes_back_as_plain_text(client, auth_headers, brief):
    response = client.get(_url(1), headers=auth_headers)
    assert response.status_code == 200
    assert response.data.decode().strip() == CONTENT_MARKER
    assert response.headers["Content-Type"].startswith("text/plain")


def test_a_picture_comes_back_as_a_picture(client, auth_headers, brief):
    response = client.get(_url(2), headers=auth_headers)
    assert response.status_code == 200
    assert response.data == PNG
    assert response.headers["Content-Type"] == "image/png"


def test_the_position_is_the_one_the_reading_pane_lists(client, auth_headers, brief):
    """No second identifier: the nth entry of `attachments` is attachment n."""
    listed = client.get(f"/api/inbox/{EMAIL_ID}", headers=auth_headers).get_json()["attachments"]
    assert [a["filename"] for a in listed] == ["SECRET-NAME-brief.pdf", "rubric.txt", "diagram.png"]
    for index, entry in enumerate(listed):
        response = client.get(_url(index), headers=auth_headers)
        assert response.status_code == 200
        assert len(response.data) == entry["size"]
        assert entry["filename"] in response.headers["Content-Disposition"]


def test_an_image_pasted_into_the_message_can_be_opened(client, auth_headers, tmp_path):
    """The case that started this: a screenshot in the body, shown as "[image: image.png]"."""
    picture = b"\x89PNG\r\n\x1a\n" + b"s" * INLINE_IMAGE_MIN_BYTES
    message = _message()
    message.add_alternative('<p><img src="cid:ii_1"></p>', subtype="html")
    message.get_payload()[1].add_related(picture, maintype="image", subtype="png", cid="<ii_1>",
                                         filename="image.png", disposition="inline")
    _deliver(tmp_path, message)

    listed = client.get(f"/api/inbox/{EMAIL_ID}", headers=auth_headers).get_json()["attachments"]
    assert listed == [{"filename": "image.png", "content_type": "image/png", "size": len(picture)}]
    response = client.get(_url(0), headers=auth_headers)
    assert response.status_code == 200 and response.data == picture


def test_a_forwarded_email_is_saved_as_an_eml_file(client, auth_headers, tmp_path):
    inner = EmailMessage()
    inner["From"] = "someone@example.org"
    inner["Subject"] = "Original"
    inner.set_content("Original text.")
    message = _message()
    message.add_attachment(inner)
    _deliver(tmp_path, message)

    response = client.get(_url(0), headers=auth_headers)
    assert response.status_code == 200
    assert response.headers["Content-Type"] == "application/octet-stream"
    assert 'attachment; filename="forwarded-message.eml"' in response.headers["Content-Disposition"]
    assert BytesParser(policy=policy.default).parsebytes(response.data)["Subject"] == "Original"


def test_an_empty_file_is_served_empty_rather_than_refused(client, auth_headers, tmp_path):
    response = _serve_one(client, auth_headers, tmp_path, b"", "application", "pdf", "blank.pdf")
    assert response.status_code == 200
    assert response.data == b""


# --- what it refuses -----------------------------------------------------------------


def test_opening_an_attachment_needs_a_token(client, brief):
    assert client.get(_url(0)).status_code == 401


def test_a_bad_token_is_refused(client, brief):
    response = client.get(_url(0), headers={"Authorization": "Bearer not-a-token"})
    assert response.status_code == 401


@pytest.mark.parametrize("index", [3, 49, 50, 999999])
def test_a_position_past_the_end_is_a_404(client, auth_headers, brief, index):
    response = client.get(_url(index), headers=auth_headers)
    assert response.status_code == 404
    assert "error" in response.get_json()


@pytest.mark.parametrize("index", ["-1", "abc", "0.5", "1e3", ""])
def test_a_position_that_is_not_a_whole_number_is_a_404(client, auth_headers, brief, index):
    assert client.get(_url(index), headers=auth_headers).status_code == 404


def test_an_unknown_email_is_a_404(client, auth_headers, brief):
    assert client.get(_url(0, "nobody@example.org"), headers=auth_headers).status_code == 404


def test_an_email_without_attachments_has_nothing_to_open(client, auth_headers):
    assert client.get(_url(0, WORK_EMAIL_ID), headers=auth_headers).status_code == 404


def test_only_get_is_routed(client, auth_headers, brief):
    for method in ("post", "put", "delete", "patch"):
        assert getattr(client, method)(_url(0), headers=auth_headers).status_code == 405


# --- a sender's file is never rendered as a page ---------------------------------------


SCRIPT = b"<script>fetch('/api/inbox').then(steal)</script>"


@pytest.mark.parametrize("maintype,subtype,filename,data", [
    ("text", "html", "invoice.html", SCRIPT),
    ("image", "svg+xml", "logo.svg", b'<svg xmlns="http://www.w3.org/2000/svg">' + SCRIPT + b"</svg>"),
    ("application", "xhtml+xml", "page.xhtml", SCRIPT),
    ("text", "xml", "feed.xml", SCRIPT),
    ("application", "javascript", "run.js", b"steal()"),
    ("application", "zip", "bundle.zip", b"PK\x03\x04"),
    ("application", "x-unknown-thing", "mystery", b"\x00\x01"),
])
def test_anything_not_on_the_inline_list_is_a_download(client, auth_headers, tmp_path,
                                                       maintype, subtype, filename, data):
    """text/html is the obvious case and image/svg+xml the one that gets missed:
    an SVG is a document that can carry script, not just a picture."""
    response = _serve_one(client, auth_headers, tmp_path, data, maintype, subtype, filename)
    assert response.status_code == 200
    assert response.headers["Content-Type"] == "application/octet-stream"
    assert response.headers["Content-Disposition"].startswith("attachment;")
    assert response.data == data          # still the user's file, intact


def test_the_inline_list_holds_nothing_a_browser_would_run():
    """Adding a type here is a security decision. This fails so that it is made
    on purpose: raster images, PDF and plain text only."""
    assert INLINE_TYPES == {
        "image/png", "image/jpeg", "image/gif", "image/webp", "image/bmp",
        "application/pdf", "text/plain", "text/csv",
    }


def test_html_declared_with_parameters_or_capitals_is_still_a_download(client, auth_headers, tmp_path):
    raw = (
        b"From: a@example.org\r\nSubject: Sneaky\r\nMessage-ID: <" + EMAIL_ID.encode() + b">\r\n"
        b"Date: Tue, 02 Sep 2026 09:30:00 +1000\r\n"
        b'Content-Type: multipart/mixed; boundary="B"\r\n\r\n'
        b"--B\r\nContent-Type: text/plain\r\n\r\nBody.\r\n"
        b'--B\r\nContent-Type: TEXT/HTML; charset="utf-8"; name="a.html"\r\n'
        b'Content-Disposition: attachment; filename="a.html"\r\n\r\n' + SCRIPT + b"\r\n"
        b"--B--\r\n"
    )
    mailbox = tmp_path / "mailbox"
    os.makedirs(mailbox, exist_ok=True)
    (mailbox / "sneaky.eml").write_bytes(raw)
    response = client.get(_url(0), headers=auth_headers)
    assert response.status_code == 200
    assert response.headers["Content-Type"] == "application/octet-stream"
    assert response.headers["Content-Disposition"].startswith("attachment;")


@pytest.mark.parametrize("index", [0, 1, 2])
def test_every_response_tells_the_browser_not_to_guess_or_keep(client, auth_headers, brief, index):
    headers = client.get(_url(index), headers=auth_headers).headers
    assert headers["X-Content-Type-Options"] == "nosniff"
    assert "default-src 'none'" in headers["Content-Security-Policy"]
    assert "sandbox" in headers["Content-Security-Policy"]
    assert "no-store" in headers["Cache-Control"] and "private" in headers["Cache-Control"]


def _assert_one_harmless_disposition(response):
    """Read the header back the way a browser would: one disposition, and a
    file name is its only parameter. One quoted value, so the name did not
    close it early; no line break, so it did not start a header of its own."""
    from werkzeug.http import parse_options_header

    assert response.status_code == 200
    disposition = response.headers["Content-Disposition"]
    assert "\r" not in disposition and "\n" not in disposition
    assert "Set-Cookie" not in response.headers
    kind, parameters = parse_options_header(disposition)
    assert kind == "inline"
    assert set(parameters) == {"filename"}
    assert disposition.count('"') == 2


@pytest.mark.parametrize("hostile", [
    'evil"; filename="x.html',
    'back\\slash".pdf',
    "semi;colon;x=1.pdf",
])
def test_a_file_name_cannot_write_its_own_header(client, auth_headers, tmp_path, hostile):
    """The name is sender-chosen text placed inside a header value."""
    response = _serve_one(client, auth_headers, tmp_path, b"x", "application", "pdf", hostile)
    _assert_one_harmless_disposition(response)


def test_a_file_name_cannot_start_a_new_header(client, auth_headers, tmp_path):
    """A line break cannot be typed into a file name, but RFC 2231 lets a sender
    percent-encode one, and it decodes to a real CR LF."""
    raw = (
        b"From: a@example.org\r\nSubject: Split\r\nMessage-ID: <" + EMAIL_ID.encode() + b">\r\n"
        b"Date: Tue, 02 Sep 2026 09:30:00 +1000\r\n"
        b'Content-Type: multipart/mixed; boundary="B"\r\n\r\n'
        b"--B\r\nContent-Type: text/plain\r\n\r\nBody.\r\n"
        b"--B\r\nContent-Type: application/pdf\r\n"
        b"Content-Disposition: attachment;"
        b" filename*=utf-8''two%0D%0ASet-Cookie%3A%20stolen%3D1.pdf\r\n\r\n%PDF\r\n"
        b"--B--\r\n"
    )
    mailbox = tmp_path / "mailbox"
    os.makedirs(mailbox, exist_ok=True)
    (mailbox / "split.eml").write_bytes(raw)
    _assert_one_harmless_disposition(client.get(_url(0), headers=auth_headers))


def test_the_header_is_safe_even_for_a_name_the_parser_did_not_clean():
    """headers.py strips control characters from names before they get here.
    The route does not rely on that: handed a raw name, it still writes one
    well-formed header value."""
    from werkzeug.http import parse_options_header

    from backend.routes.attachments import _content_disposition

    value = _content_disposition('a"b\r\nSet-Cookie: s=1; x="y".pdf', inline=False)
    assert "\r" not in value and "\n" not in value
    assert value.count('"') == 2
    kind, parameters = parse_options_header(value)
    assert kind == "attachment" and set(parameters) == {"filename"}
    assert _content_disposition("", inline=True).startswith('inline; filename="attachment"')


def test_a_non_ascii_file_name_survives(client, auth_headers, tmp_path):
    response = _serve_one(client, auth_headers, tmp_path, b"%PDF", "application", "pdf",
                          ("utf-8", "", "réunion café.pdf"))
    disposition = response.headers["Content-Disposition"]
    assert "filename*=UTF-8''r%C3%A9union%20caf%C3%A9.pdf" in disposition
    assert 'filename="runion caf.pdf"' in disposition


# --- the rest of the promise still holds ---------------------------------------------------


def test_opening_an_attachment_sends_nothing_to_the_model(client, auth_headers, brief, stub_llm):
    for index in range(3):
        assert client.get(_url(index), headers=auth_headers).status_code == 200
    assert stub_llm.calls == []


def test_neither_the_name_nor_the_content_reaches_the_log(client, auth_headers, brief, caplog):
    with caplog.at_level(logging.DEBUG):
        for index in range(3):
            client.get(_url(index), headers=auth_headers)
        client.get(_url(7), headers=auth_headers)            # and a miss
    assert "attachment 0 of" in caplog.text, "the route logged nothing, so this proves nothing"
    assert "SECRET-NAME" not in caplog.text
    assert "rubric" not in caplog.text and "diagram" not in caplog.text
    assert CONTENT_MARKER not in caplog.text


def test_opening_an_attachment_writes_nothing_to_disk(client, auth_headers, brief, tmp_path):
    before = sorted(p for p in tmp_path.rglob("*") if p.is_file())
    for index in range(3):
        client.get(_url(index), headers=auth_headers)
    assert sorted(p for p in tmp_path.rglob("*") if p.is_file()) == before


def test_the_json_routes_still_carry_no_attachment_content(client, auth_headers, brief, stub_llm):
    """Serving bytes on request changed nothing about what is listed."""
    stub_llm.queue({"results": []})
    inbox = client.get("/api/inbox", headers=auth_headers)
    reading = client.get(f"/api/inbox/{EMAIL_ID}", headers=auth_headers)
    for response in (inbox, reading):
        assert response.status_code == 200
        assert CONTENT_MARKER not in response.get_data(as_text=True)
    assert set(reading.get_json()["attachments"][0]) == {"filename", "content_type", "size"}


def test_someone_who_does_not_own_the_mailbox_cannot_open_its_attachments(
        client, auth_headers, config, monkeypatch):
    """GMAIL_OWNER applies here as it does to the inbox: any other login is
    served the fixture mailbox, so the real one is never asked for a file."""
    from backend.adapters import email_source as module

    asked = []

    class RealMailbox:
        def get_attachment(self, email_id, index):
            asked.append((email_id, index))
            raise AssertionError("the owner's mailbox was read for someone else")

    config.email_source = "gmail"
    config.gmail_owner = "owner@example.org"
    monkeypatch.setitem(module._sources, module._source_key(config, "gmail"), RealMailbox())

    response = client.get(_url(0, "anything@mail.gmail.com"), headers=auth_headers)
    assert response.status_code == 404
    assert asked == []


def test_the_owner_is_served_from_their_own_mailbox(client, auth_headers, config, monkeypatch):
    """The other half of the test above: the same wiring, with the signed-in
    account as the owner, does reach the configured mailbox."""
    from backend.adapters import email_source as module
    from backend.adapters.headers import AttachmentContent

    asked = []

    class RealMailbox:
        def get_attachment(self, email_id, index):
            asked.append((email_id, index))
            return AttachmentContent(filename="mine.pdf", content_type="application/pdf", data=b"%PDF")

    config.email_source = "gmail"
    config.gmail_owner = TEST_EMAIL
    monkeypatch.setitem(module._sources, module._source_key(config, "gmail"), RealMailbox())

    response = client.get(_url(4, "anything@mail.gmail.com"), headers=auth_headers)
    assert response.status_code == 200 and response.data == b"%PDF"
    assert asked == [("anything@mail.gmail.com", 4)]


# --- routing ----------------------------------------------------------------------------


def test_the_attachment_path_is_not_swallowed_by_the_message_route(app):
    """/api/inbox/<path:email_id> matches slashes. If it won, every attachment
    request would return the message's JSON instead of the file."""
    adapter = app.url_map.bind("localhost")
    endpoint, args = adapter.match("/api/inbox/abc@example.org/attachments/2")
    assert endpoint == "attachments.open_attachment"
    assert args == {"email_id": "abc@example.org", "index": 2}
    assert adapter.match("/api/inbox/abc@example.org")[0] == "inbox.inbox_message"


def test_the_latency_window_records_the_rule_not_the_email_id(app, client, auth_headers, brief):
    """NFR-01's timer stores a route rule for every request (middleware/timing.py).
    The new rule carries two parameters, and neither value may be kept."""
    from backend.middleware.timing import WINDOW_KEY

    window = app.config[WINDOW_KEY]
    window.clear()
    client.get(_url(0), headers=auth_headers)
    keys = [key for key, _seconds in window.snapshot()]
    assert keys == ["GET /api/inbox/<email_id>/attachments/<index>"]
