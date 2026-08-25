"""Categorisation tests (FR-02, spec sections 4.3 and 8).

"Feed a classification response with an evidence span that is not in the source
and assert it routes to Review."

The stub supplies the model response; every assertion is about what the backend
does with it. That is the behaviour under test -- whether a fabricated evidence
span is caught, not whether a model produces one.
"""

from backend.orchestrator.classify import classify_emails
from backend.orchestrator.schemas import CATEGORIES, REVIEW_CATEGORY

EMAILS = [{
    "id": "e1",
    "subject": "Project deadline moved to Friday",
    "body": "Can we reschedule our Thursday meeting to Friday at 2pm to review the report?",
}]


def _response(**overrides):
    result = {
        "id": "e1",
        "category": "Work",
        "confidence": 0.95,
        "evidence": "reschedule our Thursday meeting",
    }
    result.update(overrides)
    return {"results": [result]}


# --- Evidence verification -------------------------------------------------


def test_verified_evidence_keeps_the_label(config, stub_llm):
    stub_llm.queue(_response())
    result = classify_emails(EMAILS, config)[0]
    assert result["category"] == "Work"
    assert result["confidence"] == 0.95


def test_fabricated_evidence_routes_to_review(config, stub_llm):
    """The label is discarded, not merely doubted."""
    stub_llm.queue(_response(evidence="the client approved the budget increase"))
    result = classify_emails(EMAILS, config)[0]
    assert result["category"] == REVIEW_CATEGORY


def test_fabricated_evidence_is_not_returned_to_the_user(config, stub_llm):
    """Showing an unverified span would present a fabrication as a quotation."""
    stub_llm.queue(_response(evidence="the client approved the budget increase"))
    assert classify_emails(EMAILS, config)[0]["evidence"] == ""


def test_paraphrased_evidence_routes_to_review(config, stub_llm):
    stub_llm.queue(_response(evidence="asks to move the meeting to Friday"))
    assert classify_emails(EMAILS, config)[0]["category"] == REVIEW_CATEGORY


def test_evidence_quoted_from_the_subject_verifies(config, stub_llm):
    """The subject is part of the email, so a span from it is real evidence."""
    stub_llm.queue(_response(evidence="Project deadline moved to Friday"))
    assert classify_emails(EMAILS, config)[0]["category"] == "Work"


def test_empty_evidence_routes_to_review(config, stub_llm):
    stub_llm.queue(_response(evidence=""))
    assert classify_emails(EMAILS, config)[0]["category"] == REVIEW_CATEGORY


# --- Confidence threshold --------------------------------------------------


def test_confidence_below_threshold_routes_to_review(config, stub_llm):
    stub_llm.queue(_response(confidence=0.42))
    result = classify_emails(EMAILS, config)[0]
    assert result["category"] == REVIEW_CATEGORY
    # The score is still reported so the UI can show how unsure it was.
    assert result["confidence"] == 0.42


def test_confidence_at_the_threshold_is_accepted(config, stub_llm):
    stub_llm.queue(_response(confidence=config.classify_confidence_threshold))
    assert classify_emails(EMAILS, config)[0]["category"] == "Work"


def test_confidence_threshold_is_configurable(config, stub_llm):
    config.classify_confidence_threshold = 0.99
    stub_llm.queue(_response(confidence=0.95))
    assert classify_emails(EMAILS, config)[0]["category"] == REVIEW_CATEGORY


def test_out_of_range_confidence_is_clamped(config, stub_llm):
    stub_llm.queue(_response(confidence=7.5))
    assert classify_emails(EMAILS, config)[0]["confidence"] == 1.0


def test_non_numeric_confidence_does_not_crash(config, stub_llm):
    stub_llm.queue(_response(confidence="very sure"))
    assert classify_emails(EMAILS, config)[0]["category"] == REVIEW_CATEGORY


# --- Review is never a silent fallback to a real category ------------------


def test_review_is_never_silently_relabelled_as_work(config, stub_llm):
    """Section 4.3: misclassifying into a real category is worse than Review."""
    stub_llm.queue(_response(evidence="invented span", confidence=0.99))
    assert classify_emails(EMAILS, config)[0]["category"] not in CATEGORIES


def test_category_outside_the_enum_routes_to_review(config, stub_llm):
    """The schema should prevent this. Checked anyway."""
    stub_llm.queue(_response(category="Newsletters"))
    assert classify_emails(EMAILS, config)[0]["category"] == REVIEW_CATEGORY


# --- Batch behaviour -------------------------------------------------------


def test_a_whole_batch_costs_one_api_call(config, stub_llm):
    """Section 3: classification is batched, not per email."""
    emails = [
        {"id": f"e{n}", "subject": f"Subject {n}", "body": f"Body number {n} about work."}
        for n in range(6)
    ]
    stub_llm.queue({"results": [
        {"id": f"e{n}", "category": "Work", "confidence": 0.9, "evidence": f"Body number {n}"}
        for n in range(6)
    ]})
    results = classify_emails(emails, config)
    assert len(results) == 6
    assert stub_llm.call_count == 1


def test_results_come_back_in_input_order(config, stub_llm):
    emails = [{"id": f"e{n}", "subject": "s", "body": f"Body number {n} here."} for n in range(3)]
    stub_llm.queue({"results": [
        {"id": "e2", "category": "Work", "confidence": 0.9, "evidence": "Body number 2"},
        {"id": "e0", "category": "Personal", "confidence": 0.9, "evidence": "Body number 0"},
        {"id": "e1", "category": "Studies", "confidence": 0.9, "evidence": "Body number 1"},
    ]})
    assert [r["id"] for r in classify_emails(emails, config)] == ["e0", "e1", "e2"]


def test_an_email_the_model_skipped_still_gets_an_answer(config, stub_llm):
    emails = [{"id": "e1", "subject": "s", "body": "Some content here."},
              {"id": "e2", "subject": "s", "body": "Other content here."}]
    stub_llm.queue({"results": [
        {"id": "e1", "category": "Work", "confidence": 0.9, "evidence": "Some content here"},
    ]})
    results = {r["id"]: r for r in classify_emails(emails, config)}
    assert results["e2"]["category"] == REVIEW_CATEGORY


def test_a_result_for_an_unrequested_id_is_discarded(config, stub_llm):
    """Otherwise a batch could relabel an email that was never in it."""
    stub_llm.queue({"results": [
        {"id": "e1", "category": "Work", "confidence": 0.9,
         "evidence": "reschedule our Thursday meeting"},
        {"id": "not-in-this-batch", "category": "Work", "confidence": 0.9, "evidence": "x"},
    ]})
    results = classify_emails(EMAILS, config)
    assert len(results) == 1
    assert results[0]["id"] == "e1"


def test_empty_batch_makes_no_api_call(config, stub_llm):
    assert classify_emails([], config) == []
    assert stub_llm.call_count == 0


def test_an_email_with_no_text_goes_to_review_without_an_api_call(config, stub_llm):
    result = classify_emails([{"id": "e1", "subject": "", "body": ""}], config)[0]
    assert result["category"] == REVIEW_CATEGORY
    assert stub_llm.call_count == 0


# --- Caching (section 4.1) -------------------------------------------------


def test_repeat_classification_costs_zero_api_calls(config, stub_llm):
    stub_llm.queue(_response())
    first = classify_emails(EMAILS, config, user="u@example.com")
    second = classify_emails(EMAILS, config, user="u@example.com")
    assert first == second
    assert stub_llm.call_count == 1


def test_the_cache_does_not_leak_between_users(config, stub_llm):
    stub_llm.queue(_response(), _response(category="Personal"))
    first = classify_emails(EMAILS, config, user="a@example.com")[0]
    second = classify_emails(EMAILS, config, user="b@example.com")[0]
    assert stub_llm.call_count == 2
    assert first["category"] == "Work"
    assert second["category"] == "Personal"


# --- Preprocessing is applied before the prompt ----------------------------


def test_quoted_history_is_not_sent_to_the_model(config, stub_llm):
    stub_llm.queue(_response(evidence="The current message"))
    classify_emails(
        [{
            "id": "e1",
            "subject": "Re: thread",
            "body": "The current message.\n\nOn Mon, 24 Aug 2026, X wrote:\n\n> secret older text",
        }],
        config,
    )
    assert "secret older text" not in stub_llm.calls[0]["user"]
