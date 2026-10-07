"""Inbox tests (FR-08, spec sections 3 and 5.2).

Covers the grouped response, the Review bucket, and the rule that every field
except the category comes from headers rather than from the model (rule 5).

Runs the shipped default: one classification call per email, several at once
(the `per_email` fixture; conftest pins the batched setting for tests written
against the call-ordered queue). The stub answers each call from the email id
in its prompt, because concurrent calls arrive in no fixed order.
"""

import jwt
import pytest

from backend.adapters.email_source import get_email_source
from backend.orchestrator.budget import get_budget
from backend.orchestrator.client import LLMUnavailable
from backend.orchestrator.schemas import CATEGORIES, REVIEW_CATEGORY
from tests.conftest import PROMO_EMAIL_ID, WORK_EMAIL_ID


@pytest.fixture(autouse=True)
def per_email(config):
    config.classify_batch_size = 1
    return config

# Which fixture belongs where, when the classifier behaves.
EXPECTED = {
    WORK_EMAIL_ID: "Work",
    "9b7d3e51-studies-002@monash.edu": "Studies",
    "4a1c60bb-personal-003@example.com": "Personal",
    PROMO_EMAIL_ID: "Promotions",
    "1f5a8c72-studies-005@monash.edu": "Studies",
    "5d94b1c3-work-006@github.com": "Work",
}


def _labels(config, overrides=None):
    """What the model says about each fixture, keyed by email id.

    The evidence has to be genuinely verbatim: if it were not, the backend
    would correctly route everything to Review and the grouping assertions
    below would be testing the wrong thing. An override may replace an entry
    outright with an exception, which fails that email's call alone.
    """
    overrides = overrides or {}
    labels = {}
    for message in get_email_source(config).list_emails():
        override = overrides.get(message.id, {})
        if isinstance(override, BaseException):
            labels[message.id] = override
            continue
        entry = {
            "category": EXPECTED.get(message.id, "Work"),
            "confidence": 0.93,
            "evidence": message.subject,
        }
        entry.update(override)
        labels[message.id] = entry
    return labels


def test_inbox_requires_a_token(client):
    assert client.get("/api/inbox").status_code == 401


def test_inbox_returns_all_five_groups(client, auth_headers, config, stub_llm):
    stub_llm.answer_classification(_labels(config))
    body = client.get("/api/inbox", headers=auth_headers).get_json()
    assert set(body["groups"]) == set(CATEGORIES) | {REVIEW_CATEGORY}


def test_empty_groups_are_present_not_omitted(client, auth_headers, config, stub_llm):
    """An empty Review group is information: nothing needs attention."""
    stub_llm.answer_classification(_labels(config))
    groups = client.get("/api/inbox", headers=auth_headers).get_json()["groups"]
    assert groups[REVIEW_CATEGORY] == []


def test_emails_land_in_the_expected_groups(client, auth_headers, config, stub_llm):
    stub_llm.answer_classification(_labels(config))
    groups = client.get("/api/inbox", headers=auth_headers).get_json()["groups"]
    placed = {email["id"]: name for name, items in groups.items() for email in items}
    assert placed == EXPECTED


def test_every_email_appears_exactly_once(client, auth_headers, config, stub_llm):
    stub_llm.answer_classification(_labels(config))
    groups = client.get("/api/inbox", headers=auth_headers).get_json()["groups"]
    ids = [email["id"] for items in groups.values() for email in items]
    assert len(ids) == len(set(ids)) == 6


def test_an_unverified_label_lands_in_review(client, auth_headers, config, stub_llm):
    """Section 4.3: not a silent fallback to Work."""
    stub_llm.answer_classification(_labels(
        config, {WORK_EMAIL_ID: {"evidence": "a span that is not in this email"}}
    ))
    groups = client.get("/api/inbox", headers=auth_headers).get_json()["groups"]
    assert [e["id"] for e in groups[REVIEW_CATEGORY]] == [WORK_EMAIL_ID]
    assert WORK_EMAIL_ID not in [e["id"] for e in groups["Work"]]


def test_a_low_confidence_label_lands_in_review(client, auth_headers, config, stub_llm):
    stub_llm.answer_classification(_labels(config, {PROMO_EMAIL_ID: {"confidence": 0.3}}))
    groups = client.get("/api/inbox", headers=auth_headers).get_json()["groups"]
    assert [e["id"] for e in groups[REVIEW_CATEGORY]] == [PROMO_EMAIL_ID]


def test_the_email_shape_matches_the_contract(client, auth_headers, config, stub_llm):
    stub_llm.answer_classification(_labels(config))
    groups = client.get("/api/inbox", headers=auth_headers).get_json()["groups"]
    email = next(e for e in groups["Work"] if e["id"] == WORK_EMAIL_ID)
    assert set(email) == {
        "id", "thread_id", "sender", "sender_name", "subject", "received_at",
        "unread", "snippet", "category", "category_confidence", "attachments",
    }


def test_deterministic_fields_come_from_headers(client, auth_headers, config, stub_llm):
    """Rule 5: the model is never asked for any of these."""
    stub_llm.answer_classification(_labels(config))
    groups = client.get("/api/inbox", headers=auth_headers).get_json()["groups"]
    email = next(e for e in groups["Work"] if e["id"] == WORK_EMAIL_ID)
    assert email["sender"] == "d.robinson@northgate.com.au"
    assert email["sender_name"] == "David Robinson"
    assert email["subject"] == "Project deadline moved to Friday"
    assert email["received_at"].startswith("2026-08-24T23:24:11")
    assert email["unread"] is True
    # A reply, so its thread root is the message it answers, not itself.
    assert email["thread_id"] == "c8f21a04-work-000@monash.edu"


def test_the_snippet_is_cut_from_the_cleaned_body(client, auth_headers, config, stub_llm):
    """The list must not preview a quoted reply chain or an unsubscribe link."""
    stub_llm.answer_classification(_labels(config))
    groups = client.get("/api/inbox", headers=auth_headers).get_json()["groups"]
    work = next(e for e in groups["Work"] if e["id"] == WORK_EMAIL_ID)
    assert "11am" not in work["snippet"]
    assert ">" not in work["snippet"]
    promo = groups["Promotions"][0]
    assert "unsubscribe" not in promo["snippet"].lower()
    assert "<" not in promo["snippet"]


def test_each_email_is_classified_in_its_own_call(client, auth_headers, config, stub_llm):
    """Section 3 originally said one batch for the whole inbox. One email per
    call measured better on the held-out split (classify.py), so a cold load
    makes one call per email -- concurrently, on the load, never per render."""
    stub_llm.answer_classification(_labels(config))
    client.get("/api/inbox", headers=auth_headers)
    ids = sorted(m.id for m in get_email_source(config).list_emails())
    assert sorted(stub_llm.classification_batches()) == [[email_id] for email_id in ids]


def test_batch_size_20_classifies_the_whole_inbox_in_one_call(client, auth_headers, config, stub_llm):
    """The one-line revert: CLASSIFY_BATCH_SIZE=20 is the batched design."""
    config.classify_batch_size = 20
    stub_llm.answer_classification(_labels(config))
    groups = client.get("/api/inbox", headers=auth_headers).get_json()["groups"]
    placed = {email["id"]: name for name, items in groups.items() for email in items}
    assert placed == EXPECTED
    assert stub_llm.call_count == 1
    assert len(stub_llm.classification_batches()[0]) == len(EXPECTED)


def test_a_second_inbox_fetch_costs_no_api_calls(client, auth_headers, config, stub_llm):
    stub_llm.answer_classification(_labels(config))
    first = client.get("/api/inbox", headers=auth_headers).get_json()
    calls_after_first = stub_llm.call_count
    second = client.get("/api/inbox", headers=auth_headers).get_json()
    assert first == second
    assert calls_after_first == len(EXPECTED)
    assert stub_llm.call_count == calls_after_first


def test_one_failed_call_costs_its_email_not_the_inbox(client, auth_headers, config, stub_llm):
    """It lands in Review for now and is asked about again on the next load."""
    stub_llm.answer_classification(_labels(
        config, {PROMO_EMAIL_ID: LLMUnavailable("The AI service is unavailable.")}
    ))
    response = client.get("/api/inbox", headers=auth_headers)
    assert response.status_code == 200
    groups = response.get_json()["groups"]
    placed = {email["id"]: name for name, items in groups.items() for email in items}
    assert placed == {**EXPECTED, PROMO_EMAIL_ID: REVIEW_CATEGORY}

    stub_llm.answer_classification(_labels(config))
    calls_before = stub_llm.call_count
    groups = client.get("/api/inbox", headers=auth_headers).get_json()["groups"]
    placed = {email["id"]: name for name, items in groups.items() for email in items}
    assert placed == EXPECTED
    assert stub_llm.classification_batches()[calls_before:] == [[PROMO_EMAIL_ID]]


def test_an_outage_is_reported_not_disguised_as_review(client, auth_headers, config, stub_llm):
    """Every call failed because the service did: the same 503 and message the
    single-call design gave, not an inbox in which everything needs review."""
    stub_llm.raises = LLMUnavailable("The AI service is unavailable. Please try again in a moment.")
    response = client.get("/api/inbox", headers=auth_headers)
    assert response.status_code == 503
    assert response.get_json() == {
        "error": "The AI service is unavailable. Please try again in a moment."
    }


def _session_key(token):
    """The budget key the JWT middleware derives for this login."""
    claims = jwt.decode(token, options={"verify_signature": False})
    return f"{claims['sub']}:{claims['iat']}"


def test_a_cold_load_costs_the_session_one_unit_per_twenty_emails(client, auth_headers, token,
                                                                  config, stub_llm):
    """Six emails, six calls, one unit of MAX_REQUESTS_PER_SESSION -- what the
    single batched call cost -- and nothing for the cached reload."""
    stub_llm.answer_classification(_labels(config))
    client.get("/api/inbox", headers=auth_headers)
    client.get("/api/inbox", headers=auth_headers)
    assert stub_llm.call_count == len(EXPECTED)
    assert get_budget(config).used(_session_key(token)) == 1


def test_an_exhausted_session_gets_429_before_any_model_call(client, auth_headers, token,
                                                              config, stub_llm):
    get_budget(config).spend(_session_key(token), cost=config.max_requests_per_session)
    stub_llm.answer_classification(_labels(config))
    response = client.get("/api/inbox", headers=auth_headers)
    assert response.status_code == 429
    assert stub_llm.call_count == 0


def test_confidence_is_reported_per_email(client, auth_headers, config, stub_llm):
    stub_llm.answer_classification(_labels(config))
    groups = client.get("/api/inbox", headers=auth_headers).get_json()["groups"]
    email = next(e for e in groups["Work"] if e["id"] == WORK_EMAIL_ID)
    assert email["category_confidence"] == 0.93


# --- Efficiency regressions --------------------------------------------------


def test_inbox_preprocesses_each_email_exactly_once(app, config, client, auth_headers, stub_llm, monkeypatch):
    """/api/inbox used to clean every body twice: once inside classify_emails
    and once for the snippet, with is_html passed to one call and not the
    other. Now it is cleaned once and shared. This pins the count so a future
    refactor cannot quietly double the work again."""
    import backend.routes.inbox as inbox_module
    from backend.adapters.email_source import get_email_source
    from backend.orchestrator import classify as classify_module

    calls = []
    real_email = inbox_module.preprocess_email
    real_body = classify_module.preprocess

    def counting_email(*args, **kwargs):
        calls.append(kwargs.get("label", ""))
        return real_email(*args, **kwargs)

    def counting_body(*args, **kwargs):
        calls.append(kwargs.get("label", ""))
        return real_body(*args, **kwargs)

    monkeypatch.setattr(inbox_module, "preprocess_email", counting_email)
    monkeypatch.setattr(classify_module, "preprocess", counting_body)

    stub_llm.answer_classification(_labels(config))
    response = client.get("/api/inbox", headers=auth_headers)
    assert response.status_code == 200

    total = len(get_email_source(app.config["APP_CONFIG"]).list_emails())
    assert total > 0
    assert len(calls) == total, f"expected {total} preprocess calls, saw {len(calls)}: {calls}"
