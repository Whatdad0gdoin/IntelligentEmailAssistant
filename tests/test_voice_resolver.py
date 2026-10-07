"""Spoken-reference probes for the voice target resolver (FR-05).

Deterministic and offline: resolve_target() is string matching, no model.

Speech recognition rarely mangles a name beyond recognition. Far more often it
hears a near-homophone ("sara"), substitutes a similar word ("robertson"), or
splits one written token into several spoken ones ("git hub", "fit three one
six four"). This file pins one inbox and a fixed set of each kind, plus
references to nothing in that inbox, so every change to the resolver is
measured against the same cases.

Measured on this set:

    resolver                      resolved   wrong   unrelated that resolved
    before joined words (135edeb)   15/27      0             1/16
    after                           20/27      0             1/16  (the same one)

The 11 correctly spelled references resolve in both. Of the 16 mishearings, 4
resolved before and 9 now. A probe that still returns None is marked
xfail(strict=True): the resolver *should* resolve it and does not yet. It is
strict so that a change which rescues one fails here until the probe is moved
across and the table above is updated. Returning None is the safe failure, since
the UI then asks; test_a_mishearing_never_reaches_the_wrong_email checks that no
probe ever resolves to a different email.

The route-level tests at the end cover the other half of "which email": the
order candidates arrive in, which decides what "the latest email" means.
"""

import pytest

from backend.orchestrator.intent import resolve_target

# The fixture inbox (backend/adapters/fixtures), as sender name and subject.
INBOX = [
    {"id": "01", "sender_name": "David Robinson", "subject": "Project deadline moved to Friday"},
    {"id": "06", "sender_name": "GitHub", "subject": "Security alert on ds-25/email-assistant"},
    {"id": "mb2", "sender_name": "Tom Whitaker", "subject": "Still on for Saturday?"},
    {"id": "03", "sender_name": "Sarah Chen", "subject": "Dinner this weekend?"},
    {"id": "04", "sender_name": "TechDeals", "subject": "48-hour flash sale - up to 60% off"},
    {"id": "mb1", "sender_name": "Dr Helen Marsh", "subject": "FIT3164 progress meeting moved to Tuesday"},
    {"id": "02", "sender_name": "Monash Enrolments", "subject": "Semester 2 unit registration now open"},
    {"id": "05", "sender_name": "Dr Amelia Ford", "subject": "Feedback on your research proposal"},
]

CORRECTLY_SPELLED = [
    ("summarise the email from sarah", "03"),
    ("read the one from robinson", "01"),
    ("read the github one", "06"),
    ("summarise the techdeals one", "04"),
    ("read the one from ford", "05"),
    ("read the one from amelia", "05"),
    ("read the one from whitaker", "mb2"),
    ("read the one from helen marsh", "mb1"),
    ("summarise the enrolment email", "02"),
    ("read the fit3164 email", "mb1"),
    ("summarise the monash one", "02"),
]

# Near misses the fuzzy name match already caught before joined words existed.
MISHEARD_FUZZY = [
    ("summarise the email from sara", "03"),
    ("read the one from whittaker", "mb2"),
    ("read the one from helen march", "mb1"),
    ("summarise the enrollment email", "02"),
]

# One written token heard as several spoken ones, rejoined exactly.
MISHEARD_SPLIT = [
    ("read the one from robin son", "01"),
    ("read the git hub one", "06"),
    ("summarise the tech deals one", "04"),
    ("read the fit three one six four email", "mb1"),
    ("read the fit 3164 email", "mb1"),
]


def _not_yet(heard, expected, why):
    return pytest.param(
        heard, expected, id=heard,
        marks=pytest.mark.xfail(strict=True, reason=f"not rescued yet: {why}"),
    )


# Ratios are difflib's, against the 0.78 fuzzy threshold in intent.py.
MISHEARD_UNRESOLVED = [
    _not_yet("summarise the email from cera", "03", "cera vs sarah is 0.44"),
    _not_yet("read the one from robertson", "01", "robertson vs robinson is 0.71"),
    _not_yet("read the get hub one", "06",
             "gethub vs github is 0.83, but a joined form is never fuzzy-matched"),
    _not_yet("read the one from fort", "05", "fort vs ford is 0.75"),
    _not_yet("read the one from a million", "05", "million vs amelia is 0.46"),
    _not_yet("read the one from white acre", "mb2",
             "whiteacre is not whitaker, and joins match exactly or not at all"),
    _not_yet("summarise the monarch one", "02", "monarch vs monash is 0.77"),
]

RESOLVES = CORRECTLY_SPELLED + MISHEARD_FUZZY + MISHEARD_SPLIT

ALL_PROBES = RESOLVES + [(p.values[0], p.values[1]) for p in MISHEARD_UNRESOLVED]

# References to nothing in this inbox. Each must come back None.
UNRELATED = [
    "summarise the email from tara",
    "summarise the email from bob",
    "read the gitlab email",
    "read the one from john",
    "summarise the email about pizza",
    "read it to me sorry",
    "draft a reply to the one about the party",
    "read the one from sam",
    "summarise the one from the tech team",
    # Joins to "thedeals", 0.82 against "techdeals": the false positive that
    # ruled out fuzzy-matching joined words.
    "read the one from the deals team",
    "what did dr white say",
    "read the hub email",
    "summarise the one from mon",
    "read the fit email",
    "read the one from robin",
    pytest.param(
        "the one about semester one", id="the one about semester one",
        marks=pytest.mark.xfail(
            strict=True,
            reason="resolved before and after: 'semester' matches the Semester 2 "
                   "email, and the spoken number is not compared with the subject's",
        ),
    ),
]


def test_the_probe_set_is_the_measured_one():
    """The table in the module docstring is only true of exactly this set."""
    assert len(CORRECTLY_SPELLED) == 11
    assert len(MISHEARD_FUZZY) + len(MISHEARD_SPLIT) + len(MISHEARD_UNRESOLVED) == 16
    assert len(RESOLVES) == 20
    assert len(UNRELATED) == 16


@pytest.mark.parametrize("heard,expected", ALL_PROBES, ids=[h for h, _ in ALL_PROBES])
def test_a_mishearing_never_reaches_the_wrong_email(heard, expected):
    """The property that matters most: asking is fine, a wrong dispatch is not."""
    assert resolve_target("", heard, INBOX) in (expected, None)


@pytest.mark.parametrize(
    "heard,expected",
    [pytest.param(h, e, id=h) for h, e in RESOLVES] + MISHEARD_UNRESOLVED,
)
def test_a_spoken_reference_resolves(heard, expected):
    assert resolve_target("", heard, INBOX) == expected


@pytest.mark.parametrize("heard", UNRELATED)
def test_a_reference_to_nothing_in_the_inbox_resolves_to_nothing(heard):
    assert resolve_target("", heard, INBOX) is None


# --- Joined words: where they may and may not count ------------------------

# Everyday phrases that are also one-word compounds in subject lines. The
# prototype that let joins match subjects sent every one of these to the
# compound's email instead of the newest one.
EVERYDAY_INBOX = [
    {"id": "newest", "sender_name": "Sarah Chen", "subject": "Dinner this weekend?"},
    {"id": "readme", "sender_name": "GitHub", "subject": "[ds-25/email-assistant] Update README.md"},
    {"id": "checkout", "sender_name": "TechDeals", "subject": "You left something in your checkout"},
    {"id": "setup", "sender_name": "Monash IT", "subject": "Finish your account setup"},
]


@pytest.mark.parametrize("heard", [
    "read me the latest email",
    "can you read me the most recent one",
    "check out the latest email",
    "set up a reply to the newest email",
])
def test_an_everyday_phrase_is_not_joined_into_a_subject_word(heard):
    """"read me" appears in 4 of the project's own voice transcripts."""
    assert resolve_target("", heard, EVERYDAY_INBOX) == "newest"


CODES_INBOX = [
    {"id": "cs", "sender_name": "Dr Peter Lee", "subject": "CS1001 tutorial swap"},
    {"id": "fit", "sender_name": "Dr Helen Marsh", "subject": "FIT3164 progress meeting moved to Tuesday"},
    {"id": "other", "sender_name": "Sarah Chen", "subject": "Dinner this weekend?"},
]


@pytest.mark.parametrize("heard,expected", [
    ("read the c s 1 0 0 1 email", "cs"),
    ("read the c s one zero zero one email", "cs"),
    ("read the c s one oh oh one email", "cs"),
    ("summarise the f i t 3 1 6 4 email", "fit"),
    ("summarise the fit 31 64 email", "fit"),
])
def test_a_code_spoken_in_pieces_is_glued_back_together(heard, expected):
    assert resolve_target("", heard, CODES_INBOX) == expected


def test_a_different_code_does_not_match():
    """Glued forms are exact: CS1002 is not CS1001."""
    assert resolve_target("", "read the c s 1 0 0 2 email", CODES_INBOX) is None


def test_a_spoken_number_word_still_matches_as_a_word():
    """Digits are added alongside the words, not swapped in for them. Swapped,
    "three" would stop matching and the two emails would tie on "reminders"."""
    candidates = [
        {"id": "three", "sender_name": "Ana Silva", "subject": "Three reminders"},
        {"id": "other", "sender_name": "Ben Okafor", "subject": "Reminders for Friday"},
    ]
    assert resolve_target("", "read the one about three reminders", candidates) == "three"


def test_a_number_word_inside_a_name_still_joins():
    """The joins run over the words as heard too, so "one" in "one drive" is not
    lost to the digit "1" before it can join up with "drive"."""
    candidates = [
        {"id": "drive", "sender_name": "OneDrive", "subject": "Your files are ready"},
        {"id": "other", "sender_name": "Sarah Chen", "subject": "Dinner"},
    ]
    assert resolve_target("", "read the one drive email", candidates) == "drive"


def test_words_are_not_joined_across_two_hypotheses():
    """Each alternative is a whole hypothesis; the last word of one and the first
    word of the next were never said together."""
    assert resolve_target("", "read the email from git", INBOX, alternatives=["hub"]) is None


# --- Joined words keep the existing ranking rules --------------------------


def test_a_joined_exact_match_outranks_a_near_miss():
    candidates = [
        {"id": "joined", "sender_name": "TechDeals", "subject": "Flash sale"},
        {"id": "fuzzy", "sender_name": "Teck Dealz", "subject": "Newsletter"},
    ]
    # "dealz" is 0.80 against "deals", a fuzzy hit worth 2; the rejoined
    # "techdeals" is exact and worth 3.
    assert resolve_target("", "summarise the tech deals email", candidates) == "joined"


def test_a_joined_sender_name_outranks_subject_words():
    candidates = [
        {"id": "subject", "sender_name": "Monash IT", "subject": "Security alert for your account"},
        {"id": "sender", "sender_name": "GitHub", "subject": "Weekly digest"},
    ]
    assert resolve_target("", "read the security email from git hub", candidates) == "sender"


def test_a_joined_match_on_two_emails_is_still_a_tie():
    candidates = [
        {"id": "a", "sender_name": "GitHub", "subject": "Pull request merged"},
        {"id": "b", "sender_name": "GitHub", "subject": "New sign-in"},
    ]
    assert resolve_target("", "read the git hub email", candidates) is None


def test_a_title_spelled_out_still_identifies_no_one():
    candidates = [
        {"id": "a", "sender_name": "Dr Amelia Ford", "subject": "Feedback"},
        {"id": "b", "sender_name": "Dr Peter Lee", "subject": "Timetable"},
    ]
    assert resolve_target("", "read the email from the d r", candidates) is None


# --- The route orders candidates (POST /api/voice/intent) ------------------

_LATEST = {"intent": "summarise", "target_reference": "the latest email", "confidence": 0.9}


def _post(client, auth_headers, transcript, emails):
    response = client.post("/api/voice/intent", headers=auth_headers, json={
        "transcript": transcript,
        "emails": emails,
    })
    assert response.status_code == 200, response.get_json()
    return response.get_json()["target_email_id"]


def _email(email_id, sender, received_at=None):
    entry = {"id": email_id, "sender_name": sender, "subject": f"Message {email_id}"}
    if received_at is not None:
        entry["received_at"] = received_at
    return entry


def test_the_latest_email_is_the_newest_not_the_first_category(client, auth_headers, stub_llm):
    """The frontend once sent the inbox in category order, Work first, so "the
    latest email" meant the newest Work email. With dates supplied, the route
    orders the list itself."""
    stub_llm.queue(_LATEST)
    emails = [
        _email("work-old", "Ann Work", "2026-08-25T09:24:00+00:00"),
        _email("personal", "Ben Personal", "2026-08-24T19:41:00+00:00"),
        _email("studies-new", "Cat Studies", "2026-09-04T19:26:00+00:00"),
    ]
    assert _post(client, auth_headers, "summarise the latest email", emails) == "studies-new"


def test_dates_in_different_offsets_are_compared_as_instants(client, auth_headers, stub_llm):
    """09:00 in Melbourne (+10:00) is 23:00 the day before in UTC."""
    stub_llm.queue(_LATEST)
    emails = [
        _email("melbourne", "Ann", "2026-09-05T09:00:00+10:00"),   # 2026-09-04T23:00Z
        _email("utc", "Ben", "2026-09-04T23:30:00Z"),
    ]
    assert _post(client, auth_headers, "summarise the latest email", emails) == "utc"


def test_an_undated_email_goes_last(client, auth_headers, stub_llm):
    stub_llm.queue(_LATEST)
    emails = [
        _email("undated", "Ann", ""),
        _email("garbled", "Ben", "not a date"),
        _email("dated", "Cat", "2026-08-01T00:00:00+00:00"),
    ]
    assert _post(client, auth_headers, "summarise the latest email", emails) == "dated"


def test_a_tie_keeps_the_order_it_was_sent_in(client, auth_headers, stub_llm):
    stub_llm.queue(_LATEST)
    same = "2026-09-04T19:26:00+00:00"
    emails = [_email("first", "Ann", same), _email("second", "Ben", same)]
    assert _post(client, auth_headers, "summarise the latest email", emails) == "first"


def test_without_dates_the_callers_order_stands(client, auth_headers, stub_llm):
    """`received_at` is optional; a caller that omits it is trusted as before."""
    stub_llm.queue(_LATEST)
    emails = [_email("first", "Ann"), _email("second", "Ben")]
    assert _post(client, auth_headers, "summarise the latest email", emails) == "first"


def test_the_cap_keeps_the_newest_emails_not_the_first_listed(client, auth_headers, stub_llm):
    """Only MAX_CANDIDATES are kept. In category order, 150 older Work emails
    pushed a newer Studies email past the cap, and its sender stopped resolving."""
    stub_llm.queue({"intent": "read", "target_reference": "the one from zed quill",
                    "confidence": 0.9})
    old_work = [
        _email(f"work-{n}", f"Sender{n:03d} Work", f"2026-07-01T{n % 24:02d}:00:00+00:00")
        for n in range(150)
    ]
    newest = _email("studies-new", "Zed Quill", "2026-09-04T19:26:00+00:00")
    assert _post(client, auth_headers, "read the one from zed quill", old_work + [newest]) == "studies-new"
