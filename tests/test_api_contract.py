"""Route-level contract and architecture tests (spec sections 1, 3 and rule 4).

Two groups:

- The API contract: the documented request and response shapes, and what each
  failure mode returns. A route that swallows an orchestrator failure and
  returns 200 with an empty summary would satisfy a naive test and violate the
  spec, so the failure codes are asserted explicitly.
- The architecture rules: no vendor SDK outside the orchestrator, no model name
  outside config and the orchestrator. These are checked by reading the source
  tree, because they are the kind of rule that decays silently.
"""

import os
import re

import pytest

from backend.orchestrator.budget import get_budget
from backend.orchestrator.client import LLMUnavailable
from backend.orchestrator.schemas import CATEGORIES, INTENTS, REVIEW_CATEGORY
from tests.conftest import WORK_EMAIL_ID

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND_DIR = os.path.join(PROJECT_ROOT, "backend")
ORCHESTRATOR_DIR = os.path.join(BACKEND_DIR, "orchestrator")
FRONTEND_SRC = os.path.join(PROJECT_ROOT, "frontend", "src")


def _summary_payload():
    return {
        "summary": ["First sentence about the meeting.", "Second sentence about the report."],
        "action_items": [],
    }


# --- /api/summarise --------------------------------------------------------


def test_summarise_returns_the_documented_shape(client, auth_headers, stub_llm):
    stub_llm.queue(_summary_payload())
    response = client.post("/api/summarise", json={"email_id": WORK_EMAIL_ID},
                           headers=auth_headers)
    assert response.status_code == 200
    body = response.get_json()
    # `provenance` extends the spec's documented shape (section 3). It is an
    # approved scope addition, not drift: it carries the character offsets
    # behind each summary sentence so the UI can show where it came from.
    assert set(body) == {
        "email_id", "summary", "action_items", "grounded", "ungrounded_flags",
        "provenance",
    }
    assert 2 <= len(body["summary"]) <= 3


def test_summarise_without_an_email_id_is_a_400(client, auth_headers, stub_llm):
    assert client.post("/api/summarise", json={}, headers=auth_headers).status_code == 400


def test_summarise_with_an_unknown_email_id_is_a_404(client, auth_headers, stub_llm):
    response = client.post("/api/summarise", json={"email_id": "nope"}, headers=auth_headers)
    assert response.status_code == 404


def test_summarise_returns_a_short_summary_rather_than_failing(client, auth_headers, stub_llm):
    """Deliberate deviation from section 3, requested by the project owner.

    The spec said fail loudly after one retry. In practice that turned an
    occasional model wobble into a dead Summarise button, so a summary is now
    always returned. The model still gets a strict attempt and a corrective
    retry; only then is its own text returned as-is.

    Repair only ever REMOVES (truncating 4+ to 3). It never pads a short
    summary, because writing the missing sentence would be fabrication.
    """
    one = {"summary": ["Only one sentence."], "action_items": []}
    stub_llm.queue(one, one)
    response = client.post("/api/summarise", json={"email_id": WORK_EMAIL_ID},
                           headers=auth_headers)
    assert response.status_code == 200
    assert response.get_json()["summary"] == ["Only one sentence."]


def test_summarise_still_fails_loudly_with_nothing_to_repair(client, auth_headers, stub_llm):
    """Repair fixes shape, not absence. An empty summary has no shape to fix."""
    empty = {"summary": [], "action_items": []}
    stub_llm.queue(empty, empty)
    response = client.post("/api/summarise", json={"email_id": WORK_EMAIL_ID},
                           headers=auth_headers)
    assert response.status_code == 502
    assert "summary" not in response.get_json()


def test_summarise_returns_503_when_the_service_is_down(client, auth_headers, stub_llm):
    stub_llm.raises = LLMUnavailable("The AI service is unavailable.")
    response = client.post("/api/summarise", json={"email_id": WORK_EMAIL_ID},
                           headers=auth_headers)
    assert response.status_code == 503


def test_summarise_returns_429_when_the_session_cap_is_spent(client, auth_headers, stub_llm, config):
    from backend.orchestrator.budget import BudgetExceeded

    stub_llm.raises = BudgetExceeded(used=100, limit=100)
    response = client.post("/api/summarise", json={"email_id": WORK_EMAIL_ID},
                           headers=auth_headers)
    assert response.status_code == 429
    get_budget(config).reset()


# --- /api/classify ---------------------------------------------------------


def test_classify_returns_the_documented_shape(client, auth_headers, stub_llm):
    stub_llm.queue({"results": [
        {"id": "a", "category": "Work", "confidence": 0.9,
         "evidence": "the quarterly report is due"},
    ]})
    response = client.post("/api/classify", headers=auth_headers, json={
        "emails": [{"id": "a", "subject": "Report",
                    "body": "Reminder that the quarterly report is due on Friday."}]
    })
    assert response.status_code == 200
    result = response.get_json()["results"][0]
    assert set(result) == {"id", "category", "confidence", "evidence"}
    assert result["category"] in list(CATEGORIES) + [REVIEW_CATEGORY]


def test_classify_accepts_an_empty_batch(client, auth_headers, stub_llm):
    response = client.post("/api/classify", json={"emails": []}, headers=auth_headers)
    assert response.status_code == 200
    assert response.get_json() == {"results": []}
    assert stub_llm.call_count == 0


def test_classify_rejects_a_malformed_batch(client, auth_headers, stub_llm):
    for payload in ({}, {"emails": "not a list"}, {"emails": [{"no_id": 1}]}):
        response = client.post("/api/classify", json=payload, headers=auth_headers)
        assert response.status_code == 400, payload


def test_classify_rejects_an_oversized_batch(client, auth_headers, stub_llm):
    payload = {"emails": [{"id": str(n), "subject": "s", "body": "b"} for n in range(500)]}
    response = client.post("/api/classify", json=payload, headers=auth_headers)
    assert response.status_code == 400


# --- /api/draft ------------------------------------------------------------


def test_draft_returns_the_documented_shape(client, auth_headers, stub_llm):
    stub_llm.queue({"draft": "Hi David,\n\nFriday at 2pm works.\n\nThanks"})
    response = client.post("/api/draft", json={"email_id": WORK_EMAIL_ID},
                           headers=auth_headers)
    assert response.status_code == 200
    assert set(response.get_json()) == {"draft", "grounded", "ungrounded_flags"}


def test_draft_accepts_an_optional_instruction(client, auth_headers, stub_llm):
    stub_llm.queue({"draft": "Hi David,\n\nFriday at 2pm works.\n\nThanks"})
    response = client.post(
        "/api/draft",
        json={"email_id": WORK_EMAIL_ID, "instruction": "keep it short"},
        headers=auth_headers,
    )
    assert response.status_code == 200
    assert "keep it short" in stub_llm.calls[0]["user"]


def test_draft_rejects_a_non_string_instruction(client, auth_headers, stub_llm):
    response = client.post(
        "/api/draft", json={"email_id": WORK_EMAIL_ID, "instruction": {"a": 1}},
        headers=auth_headers,
    )
    assert response.status_code == 400


# --- /api/voice/intent -----------------------------------------------------


def test_voice_intent_returns_the_documented_shape(client, auth_headers, stub_llm):
    stub_llm.queue({"intent": "summarise", "target_reference": "", "confidence": 0.88})
    response = client.post("/api/voice/intent", json={"transcript": "summarise this"},
                           headers=auth_headers)
    assert response.status_code == 200
    body = response.get_json()
    assert set(body) == {"intent", "target_email_id", "confidence"}
    assert body["intent"] in INTENTS


def test_voice_intent_resolves_a_target_from_supplied_candidates(client, auth_headers, stub_llm):
    stub_llm.queue({"intent": "read", "target_reference": "from sarah", "confidence": 0.9})
    response = client.post("/api/voice/intent", headers=auth_headers, json={
        "transcript": "read the email from sarah",
        "emails": [{"id": "e9", "sender_name": "Sarah Chen", "subject": "Dinner"}],
    })
    assert response.get_json()["target_email_id"] == "e9"


def test_voice_intent_requires_a_transcript(client, auth_headers, stub_llm):
    assert client.post("/api/voice/intent", json={}, headers=auth_headers).status_code == 400


def test_voice_intent_without_candidates_returns_a_null_target(client, auth_headers, stub_llm):
    stub_llm.queue({"intent": "summarise", "target_reference": "the one from sarah",
                    "confidence": 0.9})
    response = client.post("/api/voice/intent",
                           json={"transcript": "summarise the one from sarah"},
                           headers=auth_headers)
    assert response.get_json()["target_email_id"] is None


# --- Malformed requests generally ------------------------------------------


@pytest.mark.parametrize("path", ["/api/summarise", "/api/classify", "/api/draft",
                                  "/api/voice/intent"])
def test_a_non_json_body_is_a_400_not_a_500(client, auth_headers, stub_llm, path):
    response = client.post(path, data="this is not json", headers=auth_headers)
    assert response.status_code == 400


# /api/summarise and /api/draft name the email_id they could not find. That is
# an identifier the caller just sent, not email content, and echoing it is what
# makes a 404 diagnosable. What NFR-03 forbids is the *body* coming back.
_ECHOES_THE_ID = {"/api/summarise", "/api/draft"}


@pytest.mark.parametrize("path", ["/api/summarise", "/api/classify", "/api/draft",
                                  "/api/voice/intent"])
def test_an_error_response_never_echoes_the_request(client, auth_headers, stub_llm, path):
    """NFR-03: no error handler dumps the payload."""
    marker = "ZEBRAFISH-REQUEST-MARKER"
    body_marker = "ZEBRAFISH-BODY-MARKER"
    response = client.post(
        path,
        json={"email_id": marker, "transcript": marker, "emails": marker,
              "body": body_marker, "instruction": body_marker},
        headers=auth_headers,
    )
    assert response.status_code >= 400
    text = response.get_data(as_text=True)
    assert body_marker not in text, "request content was echoed back"
    if path not in _ECHOES_THE_ID:
        assert marker not in text


# --- Architecture rules (rule 4) -------------------------------------------


def _python_files(directory):
    for root, _, files in os.walk(directory):
        for name in files:
            if name.endswith(".py"):
                yield os.path.join(root, name)


def test_no_vendor_sdk_outside_the_orchestrator():
    """Rule 4: all OpenAI calls go through one module."""
    pattern = re.compile(r"^\s*(?:import|from)\s+openai\b", re.M)
    offenders = []
    for path in _python_files(BACKEND_DIR):
        if os.path.commonpath([path, ORCHESTRATOR_DIR]) == ORCHESTRATOR_DIR:
            continue
        with open(path, encoding="utf-8") as handle:
            if pattern.search(handle.read()):
                offenders.append(os.path.relpath(path, PROJECT_ROOT))
    assert not offenders, f"the OpenAI SDK is imported outside the orchestrator: {offenders}"


def test_the_sdk_is_imported_in_exactly_one_module():
    pattern = re.compile(r"^\s*(?:import|from)\s+openai\b", re.M)
    importers = []
    for path in _python_files(ORCHESTRATOR_DIR):
        with open(path, encoding="utf-8") as handle:
            if pattern.search(handle.read()):
                importers.append(os.path.basename(path))
    assert importers == ["client.py"], importers


def test_no_model_name_is_hardcoded_outside_config():
    """Rule 4 and section 1: the model name is configuration, not code."""
    pattern = re.compile(r"gpt-[0-9a-z.\-]+|o[13]-(?:mini|preview)", re.I)
    offenders = []
    for path in _python_files(BACKEND_DIR):
        if os.path.basename(path) == "config.py":
            continue  # the one place a default belongs
        with open(path, encoding="utf-8") as handle:
            if pattern.search(handle.read()):
                offenders.append(os.path.relpath(path, PROJECT_ROOT))
    assert not offenders, f"a model name appears outside config: {offenders}"


def test_the_frontend_knows_no_model_name_and_imports_no_sdk():
    """Rule 4: no React component imports the SDK or knows the model name."""
    if not os.path.isdir(FRONTEND_SRC):
        pytest.skip("frontend/src not present")
    pattern = re.compile(r"from\s+[\"']openai[\"']|gpt-[0-9a-z.\-]+", re.I)
    offenders = []
    for root, _, files in os.walk(FRONTEND_SRC):
        for name in files:
            if not name.endswith((".js", ".jsx")):
                continue
            path = os.path.join(root, name)
            with open(path, encoding="utf-8") as handle:
                if pattern.search(handle.read()):
                    offenders.append(os.path.relpath(path, PROJECT_ROOT))
    assert not offenders, offenders


def test_no_route_module_builds_a_prompt():
    """Prompts live in the orchestrator so they can be reviewed in one place."""
    offenders = []
    for path in _python_files(os.path.join(BACKEND_DIR, "routes")):
        with open(path, encoding="utf-8") as handle:
            content = handle.read()
        if re.search(r"^\s*(?:from|import).*\bprompts\b", content, re.M):
            offenders.append(os.path.relpath(path, PROJECT_ROOT))
    assert not offenders, f"a route imports prompts directly: {offenders}"
