"""Reply drafting (FR-03, spec section 4.5).

The risk a draft carries is different from the one a summary carries. A wrong
summary misinforms the person reading it; a wrong draft can be sent to someone
else over the user's name. A model that invents "Friday at 3pm works for me"
has committed the user to a meeting they never agreed to.

So the same entity and number check runs over the draft, and commitment-shaped
claims -- times, dates, amounts, deadlines -- that are not in the source email
or the user instruction are flagged above the textarea before the user reads
the draft (section 5.4).

There is no send path in this build, and none is reachable from here. This
module returns text. Whether it ever goes anywhere is a decision the user makes
with an explicit Approve click, which lives in the frontend.

Drafts are not cached: the same email with a different instruction is a
different draft, and re-running is the user asking for another attempt.
"""

import logging

from backend.orchestrator import prompts
from backend.orchestrator.client import LLMError, get_client
from backend.orchestrator.grounding import check_grounding
from backend.orchestrator.preprocess import preprocess
from backend.orchestrator.schemas import DEFAULT_TONE, DRAFT_SCHEMA, TONES

log = logging.getLogger(__name__)

# Long enough that a user instruction is expressive, short enough that the
# field cannot be used to smuggle a large payload into the prompt.
MAX_INSTRUCTION_CHARS = 500


class DraftValidationError(LLMError):
    """The model returned no usable draft."""


class EmptyEmailError(LLMError):
    """There is nothing left to reply to once quoting and footers are removed."""


def draft_reply(email, instruction, config, session_key=None, user_email=None,
                tone=DEFAULT_TONE):
    """Draft a reply to one SourceEmail. Returns the /api/draft response body.

    `tone` (FR-06) changes register only. It is validated against the TONES
    enum rather than passed through, so an unexpected value falls back to
    neutral instead of being interpolated into the prompt as free text.
    """
    instruction = (instruction or "").strip()[:MAX_INSTRUCTION_CHARS]
    tone = tone if tone in TONES else DEFAULT_TONE

    cleaned = preprocess(
        email.raw_body,
        config.token_budget_chars,
        is_html=email.is_html,
        label=f"draft {email.id[:12]}",
    )
    if cleaned.is_empty:
        raise EmptyEmailError(
            "This email has no readable text to reply to once quoted replies "
            "and footers are removed."
        )

    client = get_client(config)
    user_prompt = prompts.draft_user(
        email.subject, email.sender_name, cleaned.text, instruction, tone
    )

    text = ""
    for attempt in (1, 2):
        payload = client.complete_json(
            system=prompts.DRAFT_SYSTEM,
            user=user_prompt,
            schema_name="email_draft",
            schema=DRAFT_SCHEMA,
            purpose="draft",
            session_key=session_key,
        )
        text = (payload.get("draft") or "").strip()
        if text:
            break
        log.warning("draft %s: empty draft on attempt %d", email.id, attempt)
    else:
        raise DraftValidationError("The model returned an empty draft after a retry.")

    # What the model was legitimately given: the email, the deterministic
    # header fields, and the user's own instruction. A name or date drawn from
    # any of these is not a fabrication. The recipient and the signed-in
    # address are included so a greeting and a sign-off do not read as invented
    # names on every single draft.
    grounding_source = "\n".join(
        part for part in (
            email.subject,
            email.sender_name,
            email.recipient,
            user_email or "",
            cleaned.text,
            instruction,
        ) if part
    )
    result = check_grounding(text, grounding_source)

    if not result.grounded:
        log.info("draft %s: %d ungrounded claim(s)", email.id, len(result.flags))

    return {
        "draft": text,
        "grounded": result.grounded,
        "ungrounded_flags": result.as_api_flags(),
        # Echoed back so the UI cannot display a tone the draft was not
        # written in, which is what happens if an invalid value falls back
        # to neutral and nothing says so.
        "tone": tone,
    }
