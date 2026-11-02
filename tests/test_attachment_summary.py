"""A summary reads the documents attached to its email (FR-01).

orchestrator/attachments.py extracts the text of PDF, Word and text
attachments; the summarise route hands it to the summariser, which adds it to
the prompt and to the grounding source. Fixture 07, the Northgate invoice,
is the case it exists for: the amount due, 5,335.00, is only in the PDF.

What stays true: the classifier never sees an attachment; an image is never
downloaded or described; a cached summary downloads nothing; and no
attachment text is logged.
"""

import logging
import os
from email.message import EmailMessage

import pytest

from backend.adapters.email_source import FixtureEmailSource
from backend.orchestrator import attachments as attachments_module
from backend.orchestrator.summarise import summarise_email

INVOICE_ID = "b4d7e118-work-007@northgate.com.au"
QUOTES_THE_PDF = {
    "summary": ["Northgate invoiced 5,335.00 under NG-2291.",
                "Payment is due on 26 September 2026."],
    "action_items": [],
}


@pytest.fixture
def fetched(monkeypatch):
    """Every attachment the fixture source is asked for, as (email id, position)."""
    calls = []
    real = FixtureEmailSource.get_attachment

    def spy(self, email_id, index):
        calls.append((email_id, index))
        return real(self, email_id, index)

    monkeypatch.setattr(FixtureEmailSource, "get_attachment", spy)
    return calls


def _summarise(client, auth_headers, email_id=INVOICE_ID):
    return client.post("/api/summarise", json={"email_id": email_id}, headers=auth_headers)


def test_the_summary_prompt_carries_the_documents_text(client, auth_headers, stub_llm, fetched):
    stub_llm.queue(QUOTES_THE_PDF)
    assert _summarise(client, auth_headers).status_code == 200

    prompt = stub_llm.calls[-1]["user"]
    assert "Total due" in prompt and "5,335.00" in prompt         # the PDF
    assert "Data pipeline | A Chen" in prompt                      # the CSV
    assert "An image" in prompt and "do not describe it" in prompt  # the PNG, named only


def test_a_figure_only_in_the_attachment_is_grounded(client, auth_headers, stub_llm, fetched):
    stub_llm.queue(QUOTES_THE_PDF)
    body = _summarise(client, auth_headers).get_json()

    assert body["grounded"] is True, body["ungrounded_flags"]
    assert body["attachments_read"] == ["invoice-NG-2291.pdf", "milestone-schedule.csv"]


def test_without_the_attachment_the_same_figure_is_flagged(config, stub_llm):
    """The same summary checked against the body alone: the grounding source is
    what changed, not the checker."""
    email = FixtureEmailSource(config.email_fixture_dir).get_email(INVOICE_ID)
    stub_llm.queue(QUOTES_THE_PDF)

    result = summarise_email(email, config, use_cache=False)

    assert result["grounded"] is False
    assert "5,335" in str(result["ungrounded_flags"])
    assert result["attachments_read"] == []


def test_only_documents_are_downloaded(client, auth_headers, stub_llm, fetched):
    stub_llm.queue(QUOTES_THE_PDF)
    _summarise(client, auth_headers)
    # The PDF and the CSV; never the PNG.
    assert fetched == [(INVOICE_ID, 0), (INVOICE_ID, 1)]


def test_a_cached_summary_downloads_nothing(client, auth_headers, stub_llm, fetched):
    stub_llm.queue(QUOTES_THE_PDF)
    _summarise(client, auth_headers)
    fetched.clear()

    assert _summarise(client, auth_headers).status_code == 200
    assert fetched == []
    assert len(stub_llm.calls) == 1


def test_a_document_over_the_size_cap_is_named_not_downloaded(config):
    listed = FixtureEmailSource(config.email_fixture_dir).get_email(INVOICE_ID).attachments
    asked = []

    items = attachments_module.read_attachments(
        listed, lambda index: asked.append(index) or b"", max_bytes=500)

    assert asked == [1]   # the 219-byte CSV; the 947-byte PDF is over the cap
    assert items[0].status == attachments_module.STATUS_TOO_LARGE
    assert items[2].status == attachments_module.STATUS_IMAGE


def test_an_unreadable_file_is_named_and_the_summary_still_runs(config, tmp_path, client,
                                                                auth_headers, stub_llm):
    message = _message("Signed form", "form@example.org", "The signed form is attached.")
    message.add_attachment(b"%PDF-1.4 not really a pdf", maintype="application",
                           subtype="pdf", filename="form.pdf")
    _deliver(tmp_path, message)
    stub_llm.queue({"summary": ["A signed form is attached.", "It could not be opened."],
                    "action_items": []})

    response = _summarise(client, auth_headers, "form@example.org")

    assert response.status_code == 200
    assert "form.pdf" in stub_llm.calls[-1]["user"]
    assert "could not be read" in stub_llm.calls[-1]["user"]
    assert response.get_json()["attachments_read"] == []


def test_an_email_that_is_only_an_attachment_can_be_summarised(tmp_path, client, auth_headers,
                                                              stub_llm):
    message = _message("Room change", "room@example.org", "")
    message.add_attachment("The review moves to room 4 at 3pm on Friday.", filename="note.txt")
    _deliver(tmp_path, message)
    stub_llm.queue({"summary": ["The review moves to room 4.", "It starts at 3pm on Friday."],
                    "action_items": []})

    response = _summarise(client, auth_headers, "room@example.org")

    assert response.status_code == 200, response.get_json()
    assert response.get_json()["attachments_read"] == ["note.txt"]
    assert response.get_json()["grounded"] is True


def test_the_classifier_never_sees_attachment_text(client, auth_headers, stub_llm, fetched):
    stub_llm.queue({"results": []})
    client.get("/api/inbox", headers=auth_headers)

    assert stub_llm.calls
    for call in stub_llm.calls:
        assert "5,335.00" not in call["user"]
        assert "Data pipeline" not in call["user"]
    assert fetched == []


def test_attachment_text_never_reaches_the_log(client, auth_headers, stub_llm, caplog):
    with caplog.at_level(logging.DEBUG):
        stub_llm.queue(QUOTES_THE_PDF)
        _summarise(client, auth_headers)
    assert "BSB 083-004" not in caplog.text
    assert "Data pipeline" not in caplog.text


# --- helpers ------------------------------------------------------------------------


def _message(subject, message_id, body):
    message = EmailMessage()
    message["From"] = "Grace Hopper <grace@example.org>"
    message["To"] = "you@example.com"
    message["Subject"] = subject
    message["Date"] = "Tue, 02 Sep 2026 09:30:00 +1000"
    message["Message-ID"] = f"<{message_id}>"
    message.set_content(body)
    return message


def _deliver(tmp_path, message):
    """Drop a message into the local mailbox the fixture source also reads."""
    mailbox = tmp_path / "mailbox"
    os.makedirs(mailbox, exist_ok=True)
    (mailbox / f"{message['Message-ID'].strip('<>')}.eml").write_bytes(message.as_bytes())
