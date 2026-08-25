"""Inbox tests (FR-08, spec sections 3 and 5.2).

Covers the grouped response, the Review bucket, and the rule that every field
except the category comes from headers rather than from the model (rule 5).
"""

from backend.adapters.email_source import get_email_source
from backend.orchestrator.schemas import CATEGORIES, REVIEW_CATEGORY
from tests.conftest import PROMO_EMAIL_ID, WORK_EMAIL_ID

# Which fixture belongs where, when the classifier behaves.
EXPECTED = {
    WORK_EMAIL_ID: "Work",
    "9b7d3e51-studies-002@monash.edu": "Studies",
    "4a1c60bb-personal-003@example.com": "Personal",
    PROMO_EMAIL_ID: "Promotions",
    "1f5a8c72-studies-005@monash.edu": "Studies",
    "5d94b1c3-work-006@github.com": "Work",
}


def _classification(config, overrides=None):
    """Build a model response that quotes real evidence from each fixture.

    The evidence has to be genuinely verbatim: if it were not, the backend
    would correctly route everything to Review and the grouping assertions
    below would be testing the wrong thing.
    """
    overrides = overrides or {}
    results = []
    for message in get_email_source(config).list_emails():
        entry = {
            "id": message.id,
            "category": EXPECTED.get(message.id, "Work"),
            "confidence": 0.93,
            "evidence": message.subject,
        }
        entry.update(overrides.get(message.id, {}))
        results.append(entry)
    return {"results": results}


def test_inbox_requires_a_token(client):
    assert client.get("/api/inbox").status_code == 401


def test_inbox_returns_all_five_groups(client, auth_headers, config, stub_llm):
    stub_llm.queue(_classification(config))
    body = client.get("/api/inbox", headers=auth_headers).get_json()
    assert set(body["groups"]) == set(CATEGORIES) | {REVIEW_CATEGORY}


def test_empty_groups_are_present_not_omitted(client, auth_headers, config, stub_llm):
    """An empty Review group is information: nothing needs attention."""
    stub_llm.queue(_classification(config))
    groups = client.get("/api/inbox", headers=auth_headers).get_json()["groups"]
    assert groups[REVIEW_CATEGORY] == []


def test_emails_land_in_the_expected_groups(client, auth_headers, config, stub_llm):
    stub_llm.queue(_classification(config))
    groups = client.get("/api/inbox", headers=auth_headers).get_json()["groups"]
    placed = {email["id"]: name for name, items in groups.items() for email in items}
    assert placed == EXPECTED


def test_every_email_appears_exactly_once(client, auth_headers, config, stub_llm):
    stub_llm.queue(_classification(config))
    groups = client.get("/api/inbox", headers=auth_headers).get_json()["groups"]
    ids = [email["id"] for items in groups.values() for email in items]
    assert len(ids) == len(set(ids)) == 6


def test_an_unverified_label_lands_in_review(client, auth_headers, config, stub_llm):
    """Section 4.3: not a silent fallback to Work."""
    stub_llm.queue(_classification(
        config, {WORK_EMAIL_ID: {"evidence": "a span that is not in this email"}}
    ))
    groups = client.get("/api/inbox", headers=auth_headers).get_json()["groups"]
    assert [e["id"] for e in groups[REVIEW_CATEGORY]] == [WORK_EMAIL_ID]
    assert WORK_EMAIL_ID not in [e["id"] for e in groups["Work"]]


def test_a_low_confidence_label_lands_in_review(client, auth_headers, config, stub_llm):
    stub_llm.queue(_classification(config, {PROMO_EMAIL_ID: {"confidence": 0.3}}))
    groups = client.get("/api/inbox", headers=auth_headers).get_json()["groups"]
    assert [e["id"] for e in groups[REVIEW_CATEGORY]] == [PROMO_EMAIL_ID]


def test_the_email_shape_matches_the_contract(client, auth_headers, config, stub_llm):
    stub_llm.queue(_classification(config))
    groups = client.get("/api/inbox", headers=auth_headers).get_json()["groups"]
    email = next(e for e in groups["Work"] if e["id"] == WORK_EMAIL_ID)
    assert set(email) == {
        "id", "thread_id", "sender", "sender_name", "subject", "received_at",
        "unread", "snippet", "category", "category_confidence",
    }


def test_deterministic_fields_come_from_headers(client, auth_headers, config, stub_llm):
    """Rule 5: the model is never asked for any of these."""
    stub_llm.queue(_classification(config))
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
    stub_llm.queue(_classification(config))
    groups = client.get("/api/inbox", headers=auth_headers).get_json()["groups"]
    work = next(e for e in groups["Work"] if e["id"] == WORK_EMAIL_ID)
    assert "11am" not in work["snippet"]
    assert ">" not in work["snippet"]
    promo = groups["Promotions"][0]
    assert "unsubscribe" not in promo["snippet"].lower()
    assert "<" not in promo["snippet"]


def test_classification_runs_as_one_batch_for_the_whole_inbox(client, auth_headers, config, stub_llm):
    """Section 3: batch on login, not per email on render."""
    stub_llm.queue(_classification(config))
    client.get("/api/inbox", headers=auth_headers)
    assert stub_llm.call_count == 1


def test_a_second_inbox_fetch_costs_no_api_calls(client, auth_headers, config, stub_llm):
    stub_llm.queue(_classification(config))
    first = client.get("/api/inbox", headers=auth_headers).get_json()
    second = client.get("/api/inbox", headers=auth_headers).get_json()
    assert first == second
    assert stub_llm.call_count == 1


def test_confidence_is_reported_per_email(client, auth_headers, config, stub_llm):
    stub_llm.queue(_classification(config))
    groups = client.get("/api/inbox", headers=auth_headers).get_json()["groups"]
    email = next(e for e in groups["Work"] if e["id"] == WORK_EMAIL_ID)
    assert email["category_confidence"] == 0.93
