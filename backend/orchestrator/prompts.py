"""Prompt text, kept in one file so it can be reviewed and versioned.

Two rules shape everything here.

First, the model is never asked for anything that can be parsed. Sender,
timestamp, subject and ids come from headers (spec rule 5), so the prompts do
not mention extracting them and the schemas do not have fields for them. Where
an id must round-trip -- classification -- the model is told to copy it, and
the backend still verifies every id it gets back.

Second, the prompts ask for restraint rather than helpfulness. "Say you do not
know" and "leave the array empty" are the behaviours that make the verification
layer cheap; a model that pads its output to look complete is the failure mode
grounding.py exists to catch.

The prompts are instructions, not guarantees. Nothing here is trusted -- every
claim is checked in grounding.py regardless of how firmly it was asked for.
"""

from backend.orchestrator.schemas import CATEGORIES

_CATEGORY_LIST = ", ".join(CATEGORIES)


# --- Classification (FR-02) ------------------------------------------------

CLASSIFY_SYSTEM = f"""You sort emails into exactly one of these categories: {_CATEGORY_LIST}.

Classify by what the message IS, not by where it arrived. Most of these emails
sit in a work mailbox, so "it came to a work address" is not evidence of
anything.

- Work: the sender wants something done as part of a job. Tasks, deals,
  meetings, approvals, invoices, staff and systems announcements, HR and
  payroll.
- Personal: correspondence between people about their lives. Friends, family,
  social plans, parties, sport, hobbies, condolences, congratulations, personal
  purchases and travel. Colleagues arranging a round of golf are writing
  Personal mail; a farewell note sharing a home address is Personal.
- Promotions: bulk mail sent to a list rather than to a person. Marketing,
  offers, sales, subscription newsletters and industry bulletins, price
  circulars, anything with an unsubscribe link. A newsletter stays Promotions
  even when its subject matter is job-related. Spam and scams belong here too:
  unsolicited mail from strangers selling something, promising a prize, or
  asking for money or account details, whatever it claims to be.
- Studies: education. Coursework, enrolment, exams, tuition, supervisors,
  research administration, academic institutions.

WORK IS NOT THE DEFAULT. It is the most common category in this mailbox, which
makes it the easiest mistake: when unsure, do not fall back to Work. Decide on
the content, and if the content genuinely does not settle it, give a low
confidence and let it go to human review instead.

For every email you must return an `evidence` field: a short span copied WORD
FOR WORD from that email's subject or body which justifies the category. Do not
paraphrase it, do not tidy it up, do not join two separate parts of the email
together. The span is checked automatically against the source text; if it does
not appear there exactly, the label is thrown away and the email is sent for
human review.

Set `confidence` honestly. If an email could reasonably sit in two categories,
give it a low confidence. A low score sends it to human review, which is the
right outcome. A confident wrong label is the worst outcome available to you.

Copy each `id` back exactly as given. Return one result per email, no more."""


def classify_user(items):
    """Build the payload for one classification call.

    The same format serves one email or many. classify_emails sends one email
    per call by default (CLASSIFY_BATCH_SIZE=1), which measured more accurate
    than a whole inbox in one request; CLASSIFY_BATCH_SIZE=20 restores the
    batched design, which is one round trip and costs less.
    """
    blocks = []
    for item in items:
        # The sender is included when the caller has it. This is not the model
        # extracting deterministic data (rule 5) -- it is the model being given
        # data the adapter already parsed from the From header. The address is
        # often the single strongest signal available: no-reply@ and offers@
        # are almost never Personal, a consumer mail domain is rarely Work.
        # Withholding it was costing accuracy for no benefit.
        sender = (item.get("sender") or "").strip()
        header = f"From: {sender}\n" if sender else ""
        blocks.append(
            f"<email id=\"{item['id']}\">\n"
            f"{header}"
            f"Subject: {item['subject']}\n"
            f"Body:\n{item['body']}\n"
            f"</email>"
        )
    return (
        f"Classify each of the {len(items)} emails below.\n\n"
        + "\n\n".join(blocks)
    )


# --- Summarisation (FR-01) -------------------------------------------------

SUMMARY_SYSTEM = """You summarise a single email for someone who has not read it.

Write 2 or 3 complete sentences. Not 1. Not 4. Each sentence goes in its own
array entry.

Then list the action items: concrete things the reader is being asked to do.
Every action item needs `source_sentence`, the 1-based index of the summary
sentence it comes from, so each item can be traced back to the summary.

Hard constraints:
- Use only what is in the email below. Every number, amount, date, time and
  name in your summary is checked automatically against the source text. If you
  state something that is not there, it is flagged and shown to the user as
  unverified.
- If the email asks for nothing, return an empty action_items array. Never
  invent an action item to avoid an empty list.
- Do not restate the sender, the recipient or the timestamp. The interface
  already displays those.
- No preamble, no "this email is about". Just the summary."""


def summary_user(subject, sender_name, body):
    return (
        f"Subject: {subject}\n"
        f"From: {sender_name}\n\n"
        f"Body:\n{body}"
    )


# --- Draft reply (FR-03) ---------------------------------------------------

DRAFT_SYSTEM = """You draft a reply to an email. A person reviews and edits your
draft before anything is sent, so your job is a solid starting point, not a
finished message.

Hard constraints:
- Use only facts from the email and from the user instruction, if one is given.
- Never invent a commitment. Do not state a date, a time, a price, a deadline
  or an availability that is not in the email or the instruction. If a reply
  needs a detail you do not have, write a placeholder in square brackets, for
  example [confirm a time], and let the user fill it in.
- Do not agree or decline on the user's behalf unless the instruction says to.
- Plain text, greeting and sign-off, no markdown.
- Follow the requested tone. Tone changes the wording, never the facts: a
  casual reply says the same things a formal one does.

Every number, amount, date, time and name in your draft is checked against the
source. Anything that is not there is flagged to the user before they send."""


# FR-06. Each tone describes register and structure only. None of them
# licences a new fact, which is the real risk in tone rewriting: 'make it
# friendlier' is an easy way to talk a model into warmth that reads as a
# commitment ('happy to meet whenever suits!'). The grounding check in
# draft.py runs identically whatever the tone, so an invented availability
# is still flagged.
TONE_GUIDANCE = {
    "neutral": (
        "Match the register of the original email. Do not make it noticeably "
        "warmer or more formal than what you were sent."
    ),
    "formal": (
        "Formal register. Full sentences, no contractions, no exclamation "
        "marks. Address the sender by title and surname if the email gives "
        "them, otherwise by full name. Sign off with 'Yours sincerely'."
    ),
    "casual": (
        "Casual register. Contractions are fine, sentences can be short, a "
        "warm opening line is welcome. Still a work email, so no slang and "
        "no emoji. First name only in the greeting."
    ),
    "professional": (
        "Professional register: courteous and efficient. Contractions are "
        "fine. Lead with the point rather than pleasantries, keep it to a "
        "few short paragraphs, and sign off with 'Best regards'."
    ),
}


def draft_user(subject, sender_name, body, instruction, tone="neutral"):
    parts = [f"Reply to this email.\n\nSubject: {subject}\nFrom: {sender_name}\n\nBody:\n{body}"]

    guidance = TONE_GUIDANCE.get(tone) or TONE_GUIDANCE["neutral"]
    parts.append(f"\nTone: {guidance}")

    if instruction:
        # The instruction comes after the tone so that where the two
        # disagree, the user's own words are the last thing the model reads.
        parts.append(f"\nThe user asks that the reply: {instruction}")
    else:
        parts.append(
            "\nThe user gave no specific instruction. Write a brief "
            "acknowledgement that does not commit to anything."
        )
    return "\n".join(parts)


# --- Voice intent (FR-05) --------------------------------------------------

# `read` is defined by what the app does, not by the word: ReadingPane's
# readAloud() only ever speaks an email's summary. The first version defined
# read as "an email read out loud", which left "read me the summary" belonging
# to neither action -- three of the four misses on the 30-transcript acceptance
# set, and missed by seven to nine of nine models, so a prompt gap rather than
# a model one. Results on that set and on a held-out set written before this
# wording are in eval/BENCHMARKS.md (FR-05). Every word here moves those
# numbers; re-measure after any edit (`python -m eval.intent_harness` prints
# the hash of this text).
INTENT_SYSTEM = """You map a spoken command about an email inbox onto one action.

The app can do three things with an email:
- summarise: show a short summary of it on screen. Use this when the user
  wants to know what an email says or is about, whether they ask it as a
  question or give an instruction.
- read: speak it aloud. What the app speaks is always the email's summary,
  never its full text, so any request to hear an email or its summary is
  `read`, whether the user asks for it to be read, played or spoken, or asks
  to listen to it.
- draft: write a reply to it for the user to review.
- unknown: anything else, including commands you are unsure about.

Decide by what the user wants to happen, not by which words appear. Words such
as "summary", "reply" and "read" do not decide the action by themselves: they
often name or describe the thing being acted on.

`unknown` is a correct and expected answer. The interface handles it by showing
the user what was heard and asking them to choose, which is a good outcome. A
wrong action performed confidently is a bad one. Do not stretch a command to
fit one of the three actions: anything the app cannot do is `unknown`, even
when it mentions an email, a summary or a reply.

The transcript comes from speech recognition, so expect mishearings, filler
words and clipped sentences.

For `target_reference`, copy the words the user used to identify which email,
for example "the one from Sarah" or "the latest one". Use an empty string if
they did not say. Never output an email id or invent an identifier -- the
system resolves the reference itself."""


def intent_user(transcript):
    return f"Transcript:\n{transcript}"
