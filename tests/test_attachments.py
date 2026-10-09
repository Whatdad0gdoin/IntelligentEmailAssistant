"""Attachment metadata (backend/adapters/headers.py).

The inbox can now say "this email has a PDF". What it may say is bounded by
headers.py's promise that attachment content is never summarised, never sent
to a model and never logged, so most of these tests are about what does NOT
happen: no attachment text in the body, in the inbox's or the reading pane's
response, in a prompt or in a log.

The one way attachment bytes do leave the source is a person opening that
attachment. The last section here covers reading the bytes of one listed
attachment (attachment_content); the route that serves them is tested in
tests/test_attachment_route.py.
"""

import logging
import os
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser

from backend.adapters.headers import (
    INLINE_IMAGE_MIN_BYTES,
    MAX_ATTACHMENTS,
    Attachment,
    attachment_content,
    attachment_of,
    parse_message,
)
from backend.orchestrator.schemas import CATEGORIES

CONTENT_MARKER = "ATTACHMENT-CONTENT-MUST-NOT-LEAVE"


def _message(subject="Figures attached", message_id="att-1@example.org"):
    message = EmailMessage()
    message["From"] = "Grace Hopper <grace@example.org>"
    message["To"] = "you@example.com"
    message["Subject"] = subject
    message["Date"] = "Tue, 02 Sep 2026 09:30:00 +1000"
    message["Message-ID"] = f"<{message_id}>"
    message.set_content("The figures are in the PDF.")
    return message


def _parse(message):
    return parse_message(BytesParser(policy=policy.default).parsebytes(message.as_bytes()))


# --- what counts as an attachment -----------------------------------------------


def test_an_email_without_attachments_lists_none():
    assert _parse(_message()).attachments == []


def test_a_pdf_is_listed_with_its_name_type_and_decoded_size():
    message = _message()
    message.add_attachment(b"%PDF-1.4 " + b"x" * 4000, maintype="application",
                           subtype="pdf", filename="Q3 figures.pdf")
    assert _parse(message).attachments == [
        Attachment(filename="Q3 figures.pdf", content_type="application/pdf", size=4009)]


def test_attachment_content_never_reaches_the_body():
    """A text attachment is listed, and its text stays out of what is summarised."""
    message = _message()
    message.add_attachment(CONTENT_MARKER, filename="notes.txt")
    email = _parse(message)
    assert [a.filename for a in email.attachments] == ["notes.txt"]
    assert CONTENT_MARKER not in email.body_text + email.body_html
    assert "The figures are in the PDF." in email.body_text


def test_an_image_the_html_embeds_is_not_listed():
    """A signature logo referenced by Content-ID is part of the message, not a file
    the sender attached -- mail clients do not list it either."""
    message = _message()
    message.add_alternative('<p>Hi <img src="cid:logo1"></p>', subtype="html")
    html = message.get_payload()[1]
    html.add_related(b"\x89PNG\r\n", maintype="image", subtype="png", cid="<logo1>",
                     filename="logo.png", disposition="inline")
    assert _parse(message).attachments == []


def test_a_named_part_without_a_disposition_is_still_an_attachment():
    message = _message()
    message.add_attachment(b"%PDF", maintype="application", subtype="pdf", filename="x.pdf")
    del message.get_payload()[1]["Content-Disposition"]
    del message.get_payload()[1]["Content-Type"]
    message.get_payload()[1]["Content-Type"] = 'application/pdf; name="timetable.pdf"'
    assert [a.filename for a in _parse(message).attachments] == ["timetable.pdf"]


def test_a_forwarded_message_is_one_attachment_not_its_parts():
    inner = EmailMessage()
    inner["From"] = "someone@example.org"
    inner["Subject"] = "Original"
    inner.set_content("Original text.")
    inner.add_attachment(b"PK", maintype="application", subtype="zip", filename="inner.zip")
    message = _message()
    message.add_attachment(inner)
    listed = _parse(message).attachments
    assert [a.content_type for a in listed] == ["message/rfc822"]
    assert listed[0].size and listed[0].size > 0


def test_an_attached_email_is_listed_never_read_into_the_body():
    """Its text is attachment content like any other. A walk that checked each
    part on its own descended into the attached message and read its body as
    this one's -- into the summary, and into the prompt."""
    inner = EmailMessage()
    inner["From"] = "someone@example.org"
    inner["Subject"] = "Original"
    inner.set_content(f"{CONTENT_MARKER} The lab moves to room 2.14.")
    inner.add_alternative(f"<p>{CONTENT_MARKER}</p>", subtype="html")
    message = _message()
    message.add_attachment(inner)
    email = _parse(message)
    assert [a.content_type for a in email.attachments] == ["message/rfc822"]
    assert CONTENT_MARKER not in email.body_text + email.body_html
    assert email.body_text.strip() == "The figures are in the PDF."


def test_nothing_inside_an_attachment_is_read_as_body():
    """An attachment can be a container. Its text parts carry no disposition of
    their own, so the container's has to cover them."""
    container = EmailMessage()
    container.set_content(CONTENT_MARKER)
    container.add_alternative(f"<p>{CONTENT_MARKER}</p>", subtype="html")
    container["Content-Disposition"] = "attachment"
    message = _message()
    message.make_mixed()
    message.attach(container)
    email = _parse(message)
    assert CONTENT_MARKER not in email.body_text + email.body_html
    assert email.body_text.strip() == "The figures are in the PDF."


def test_a_non_ascii_file_name_is_decoded():
    message = _message()
    message.add_attachment(b"x", maintype="application", subtype="pdf",
                           filename=("utf-8", "", "réunion café.pdf"))
    assert [a.filename for a in _parse(message).attachments] == ["réunion café.pdf"]


def test_file_names_are_made_safe_to_display():
    assert attachment_of("application/pdf", "attachment",
                         "C:\\Users\\ada\\Desktop\\report.pdf", None, 1).filename == "report.pdf"
    assert attachment_of("application/pdf", "attachment",
                         "/home/ada/report.pdf", None, 1).filename == "report.pdf"
    assert attachment_of("application/pdf", "attachment",
                         "bad\x00name\x1f.pdf", None, 1).filename == "badname.pdf"
    long_name = attachment_of("application/pdf", "attachment", "a" * 300 + ".pdf", None, 1).filename
    assert len(long_name) <= 120 and long_name.endswith(".pdf")


def test_a_size_the_source_did_not_report_is_none_not_zero():
    assert attachment_of("application/pdf", "attachment", "x.pdf", None, None).size is None
    assert attachment_of("application/pdf", "attachment", "x.pdf", None, -5).size is None


def test_the_list_is_capped():
    message = _message()
    for n in range(MAX_ATTACHMENTS + 10):
        message.add_attachment(b"x", maintype="application", subtype="octet-stream",
                               filename=f"file{n}.bin")
    assert len(_parse(message).attachments) == MAX_ATTACHMENTS


# --- through the API ----------------------------------------------------------


def _deliver(tmp_path, message):
    """Drop a message into the local mailbox the fixture source also reads."""
    mailbox = tmp_path / "mailbox"
    os.makedirs(mailbox, exist_ok=True)
    (mailbox / "with-attachments.eml").write_bytes(message.as_bytes())


def _message_with_attachments():
    message = _message(subject="Assignment brief", message_id="brief@example.org")
    message.add_attachment(b"%PDF-1.4 " + CONTENT_MARKER.encode(), maintype="application",
                           subtype="pdf", filename="SECRET-NAME-brief.pdf")
    message.add_attachment(CONTENT_MARKER, filename="rubric.txt")
    return message


def _empty_classification(stub_llm):
    stub_llm.queue({"results": []})   # everything to Review: labels are not the point here


def test_the_inbox_lists_attachments_without_their_content(client, auth_headers, stub_llm, tmp_path):
    _deliver(tmp_path, _message_with_attachments())
    _empty_classification(stub_llm)
    response = client.get("/api/inbox", headers=auth_headers)
    assert response.status_code == 200
    emails = [e for group in response.get_json()["groups"].values() for e in group]
    brief = next(e for e in emails if e["subject"] == "Assignment brief")
    assert brief["attachments"] == [
        {"filename": "SECRET-NAME-brief.pdf", "content_type": "application/pdf",
         "size": len(b"%PDF-1.4 " + CONTENT_MARKER.encode())},
        {"filename": "rubric.txt", "content_type": "text/plain",
         "size": len(CONTENT_MARKER) + 1},
    ]
    assert CONTENT_MARKER not in response.get_data(as_text=True)
    # Every email carries the key, so the frontend never branches on absence.
    assert all(isinstance(e["attachments"], list) for e in emails)


def test_the_reading_pane_lists_attachments_without_their_content(client, auth_headers, stub_llm, tmp_path):
    _deliver(tmp_path, _message_with_attachments())
    response = client.get("/api/inbox/brief@example.org", headers=auth_headers)
    assert response.status_code == 200
    body = response.get_json()
    assert [a["filename"] for a in body["attachments"]] == ["SECRET-NAME-brief.pdf", "rubric.txt"]
    assert CONTENT_MARKER not in response.get_data(as_text=True)


def test_attachment_names_and_content_never_reach_the_model(client, auth_headers, stub_llm, tmp_path):
    _deliver(tmp_path, _message_with_attachments())
    _empty_classification(stub_llm)
    client.get("/api/inbox", headers=auth_headers)
    stub_llm.queue({"summary": ["The brief is attached.", "It covers the assignment."],
                    "action_items": []})
    client.post("/api/summarise", json={"email_id": "brief@example.org"}, headers=auth_headers)
    assert stub_llm.calls, "the model was never called, so this proves nothing"
    for call in stub_llm.calls:
        prompt = call["system"] + call["user"]
        assert CONTENT_MARKER not in prompt
        assert "SECRET-NAME" not in prompt


def test_attachment_names_and_content_never_reach_the_log(client, auth_headers, stub_llm,
                                                          tmp_path, caplog):
    _deliver(tmp_path, _message_with_attachments())
    _empty_classification(stub_llm)
    with caplog.at_level(logging.DEBUG):
        client.get("/api/inbox", headers=auth_headers)
        client.get("/api/inbox/brief@example.org", headers=auth_headers)
    assert "SECRET-NAME" not in caplog.text
    assert CONTENT_MARKER not in caplog.text


def test_the_demo_fixtures_have_no_attachments(client, auth_headers, stub_llm):
    _empty_classification(stub_llm)
    groups = client.get("/api/inbox", headers=auth_headers).get_json()["groups"]
    emails = [e for name in list(CATEGORIES) + ["Review"] for e in groups[name]]
    assert emails and all(e["attachments"] == [] for e in emails)


def test_a_malformed_attachment_costs_its_entry_not_the_email(monkeypatch):
    """The fixture and mailbox sources do not guard parse_message per message,
    so a part that blows up while being described must not take the email --
    or the inbox -- down with it."""
    from backend.adapters import headers as headers_module

    message = _message()
    message.add_attachment(b"%PDF", maintype="application", subtype="pdf", filename="good.pdf")
    message.add_attachment(b"x", maintype="application", subtype="octet-stream", filename="bad.bin")
    real = headers_module._leaf_attachment

    def flaky(part, content_type):
        if part.get_filename() == "bad.bin":
            raise ValueError("malformed")
        return real(part, content_type)

    monkeypatch.setattr(headers_module, "_leaf_attachment", flaky)
    email = _parse(message)
    assert [a.filename for a in email.attachments] == ["good.pdf"]
    assert "The figures are in the PDF." in email.body_text


def test_hostile_attachment_headers_do_not_break_parsing():
    raw = (
        b"From: a@example.org\r\nSubject: Hostile\r\nMessage-ID: <h@example.org>\r\n"
        b"Date: Tue, 02 Sep 2026 09:30:00 +1000\r\n"
        b'Content-Type: multipart/mixed; boundary="B"\r\n\r\n'
        b"--B\r\nContent-Type: text/plain\r\n\r\nBody text.\r\n"
        b"--B\r\nContent-Type: application/pdf\r\n"
        b"Content-Disposition: attachment; filename*=bogus-charset''%E2%28%A1.pdf\r\n"
        b"Content-Transfer-Encoding: base64\r\n\r\n!!!not base64!!!\r\n"
        b"--B\r\nContent-Type: application/zip\r\n"
        b"Content-Disposition: attachment; filename*0*=utf-8''a%20; filename*2=c.zip\r\n\r\nPK\r\n"
        b"--B--\r\n"
    )
    email = parse_message(BytesParser(policy=policy.default).parsebytes(raw))
    assert email.body_text.strip() == "Body text."
    assert len(email.attachments) == 2
    assert all(isinstance(a.filename, str) for a in email.attachments)


# --- an image pasted into the message ---------------------------------------------


def _with_embedded_image(data, filename="image.png"):
    """A message whose HTML shows an image by Content-ID, as a pasted screenshot does."""
    message = _message()
    message.add_alternative('<p>Look: <img src="cid:pasted1"></p>', subtype="html")
    message.get_payload()[1].add_related(data, maintype="image", subtype="png", cid="<pasted1>",
                                         filename=filename, disposition="inline")
    return message


def test_a_large_image_the_html_embeds_is_listed():
    """The app shows a message as plain text, so a pasted screenshot is on screen
    nowhere unless it is listed. A logo-sized one stays unlisted (see above)."""
    data = b"\x89PNG\r\n" + b"x" * INLINE_IMAGE_MIN_BYTES
    assert _parse(_with_embedded_image(data)).attachments == [
        Attachment(filename="image.png", content_type="image/png", size=len(data))]


def test_the_size_that_separates_a_pasted_image_from_a_logo():
    just_under = _with_embedded_image(b"x" * (INLINE_IMAGE_MIN_BYTES - 1))
    exactly = _with_embedded_image(b"x" * INLINE_IMAGE_MIN_BYTES)
    assert _parse(just_under).attachments == []
    assert len(_parse(exactly).attachments) == 1


def test_an_embedded_image_of_unknown_size_is_not_listed():
    """A size the source did not report cannot be judged, so nothing changes."""
    assert attachment_of("image/png", "inline", "image.png", "<pasted1>", None) is None


def test_only_an_image_is_listed_for_being_embedded_and_large():
    big = INLINE_IMAGE_MIN_BYTES * 10
    assert attachment_of("application/octet-stream", "inline", "blob.bin", "<c1>", big) is None
    assert attachment_of("text/html", "inline", "page.html", "<c1>", big) is None


def test_a_large_embedded_image_is_never_read_as_body():
    data = b"\x89PNG\r\n" + CONTENT_MARKER.encode() * 2000
    email = _parse(_with_embedded_image(data))
    assert len(email.attachments) == 1
    assert CONTENT_MARKER not in email.body_text + email.body_html


# --- reading one attachment, when a person opens it ------------------------------


def _raw(message):
    return BytesParser(policy=policy.default).parsebytes(message.as_bytes())


def test_the_bytes_of_a_listed_attachment_can_be_read_by_its_position():
    message = _message_with_attachments()
    listed = _parse(message).attachments
    pdf = attachment_content(_raw(message), 0)
    text = attachment_content(_raw(message), 1)
    assert (pdf.filename, pdf.content_type) == (listed[0].filename, listed[0].content_type)
    assert pdf.data == b"%PDF-1.4 " + CONTENT_MARKER.encode()
    assert (text.filename, text.content_type) == ("rubric.txt", "text/plain")
    assert text.data.decode().strip() == CONTENT_MARKER
    assert len(pdf.data) == listed[0].size and len(text.data) == listed[1].size


def test_a_position_that_is_not_in_the_list_reads_nothing():
    raw = _raw(_message_with_attachments())
    for index in (2, 99, -1, None, "0", 1.0, True):
        assert attachment_content(raw, index) is None, index
    assert attachment_content(_raw(_message()), 0) is None


def test_a_forwarded_message_is_read_as_the_email_it_is():
    inner = EmailMessage()
    inner["From"] = "someone@example.org"
    inner["Subject"] = "Original"
    inner.set_content("Original text.")
    message = _message()
    message.add_attachment(inner)
    content = attachment_content(_raw(message), 0)
    assert content.content_type == "message/rfc822"
    reopened = BytesParser(policy=policy.default).parsebytes(content.data)
    assert reopened["Subject"] == "Original"
    assert "Original text." in reopened.get_content()


def test_a_large_embedded_image_can_be_read():
    data = b"\x89PNG\r\n" + b"x" * INLINE_IMAGE_MIN_BYTES
    content = attachment_content(_raw(_with_embedded_image(data)), 0)
    assert (content.filename, content.content_type, content.data) == ("image.png", "image/png", data)


def test_a_position_means_the_same_attachment_when_listing_and_when_reading(monkeypatch):
    """One walk serves both. If a malformed part were skipped by the list and
    counted by the reader, opening the second attachment would serve the third."""
    from backend.adapters import headers as headers_module

    message = _message()
    message.add_attachment(b"x", maintype="application", subtype="octet-stream", filename="bad.bin")
    message.add_attachment(b"%PDF", maintype="application", subtype="pdf", filename="good.pdf")
    real = headers_module._leaf_attachment

    def flaky(part, content_type):
        if part.get_filename() == "bad.bin":
            raise ValueError("malformed")
        return real(part, content_type)

    monkeypatch.setattr(headers_module, "_leaf_attachment", flaky)
    assert [a.filename for a in _parse(message).attachments] == ["good.pdf"]
    content = attachment_content(_raw(message), 0)
    assert (content.filename, content.data) == ("good.pdf", b"%PDF")
    assert attachment_content(_raw(message), 1) is None


def test_reading_stops_at_the_same_cap_as_the_list():
    message = _message()
    for n in range(MAX_ATTACHMENTS + 3):
        message.add_attachment(b"x", maintype="application", subtype="octet-stream",
                               filename=f"file{n}.bin")
    raw = _raw(message)
    assert attachment_content(raw, MAX_ATTACHMENTS - 1).filename == f"file{MAX_ATTACHMENTS - 1}.bin"
    assert attachment_content(raw, MAX_ATTACHMENTS) is None
