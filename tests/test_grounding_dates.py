"""Dates, days and years are checked by meaning, not spelling (grounding.py).

A summary that writes "July 14" for an email's "14JUL" has invented nothing,
and flagging it teaches the reader to ignore the warning. But the relaxation
must not let a genuinely absent date through, so every "supported" case below
has a matching "still flagged" case.
"""

import pytest

from backend.orchestrator.grounding import check_grounding


def _flags(generated, source):
    return [f.claim for f in check_grounding(generated, source).flags]


@pytest.mark.parametrize("source", [
    "Your flight departs 14JUL from IAH.",
    "Departing Jul 14, returning later.",
    "Departing JUL 14.",
    "Departing 14 July.",
    "Departing 7/14/01.",
    "Departing 14-07-2026.",
    "Departing 2026-07-14.",
])
def test_a_written_out_date_matches_the_abbreviated_source(source):
    assert _flags("Your flight departs on July 14.", source) == []


@pytest.mark.parametrize("source, claim", [
    ("We are available 24/7.", "We are available from 24 July."),
    ("Delivery takes 3-5 business days.", "Delivery is due on March 5."),
    ("Open Mon-Fri 9-5.", "It opens on 5 September."),
    ("Half: 1/2 of the total.", "It is due on 2 January."),
    ("Upgrade to 2.1.10 today.", "Upgrade by February 10."),
    ("Departing 14/7.", "Departing on July 14."),
])
def test_numbers_that_only_look_like_a_date_vouch_for_none(source, claim):
    """A numeric date in the source needs its year: "24/7", a fraction, a range
    and a version number are not dates. "14/7" alone is flagged too -- a false
    flag on a real date, the cheaper of the two mistakes."""
    assert _flags(claim, source) != []


def test_may_the_verb_is_not_the_month():
    assert _flags("The deadline is May 2.", "Step 2 may take a few minutes.") == ["May 2"]
    assert _flags("The deadline is May 2.", "Due 2 May, as agreed.") == []


def test_an_ordinal_matches_a_bare_day():
    assert _flags("The meeting was on January 17th.", "At the Jan 17 meeting we agreed.") == []


def test_a_different_day_of_the_same_month_is_still_flagged():
    assert _flags("Your flight departs on July 15.", "Your flight departs 14JUL.") == ["July 15"]


def test_a_different_month_is_still_flagged():
    assert _flags("It is due on June 14.", "It is due 7/14.") == ["June 14"]


@pytest.mark.parametrize("source", ["See you Thurs.", "Open Mon-Fri 8am-6pm.", "THURS 2PM"])
def test_a_written_out_weekday_matches_an_abbreviation(source):
    generated = "See you Thursday." if "hurs" in source.lower() else "Open Monday to Friday."
    assert _flags(generated, source) == []


def test_a_different_weekday_is_still_flagged():
    assert _flags("See you Tuesday.", "See you Thurs.") == ["Tuesday"]


def test_an_ordinary_lower_case_word_is_not_a_weekday():
    """'sat' the verb must not vouch for Saturday."""
    assert _flags("They meet on Saturday.", "We sat down and agreed to meet.") == ["Saturday"]


@pytest.mark.parametrize("source, claim", [
    ("Your SAT registration is confirmed.", "The test is on Saturday."),
    ("The Sun reported the merger.", "It was reported on Sunday."),
    ("Wed in June, they say.", "The party is on Wednesday."),
])
def test_capitalised_words_that_spell_a_day_are_not_one_alone(source, claim):
    assert _flags(claim, source) != []


@pytest.mark.parametrize("source, claim", [
    ("Flight QF1 SAT 14JUL 0915.", "It departs on Saturday."),
    ("Open Mon-Sat.", "It is open on Saturday."),
    ("Closed Sat & Sun.", "It is closed on Sunday."),
    ("Brunch Sun 10am.", "Brunch is on Sunday."),
])
def test_those_words_still_count_beside_a_date_time_or_range(source, claim):
    assert _flags(claim, source) == []


def test_an_apostrophe_after_a_digit_is_not_a_year():
    assert _flags("He was born in 2010.", "He is 6'10\" tall.") == ["2010"]


@pytest.mark.parametrize("source", ["Contracts entered after 6/1/99.", "The class of '99 reunion."])
def test_a_four_digit_year_matches_a_two_digit_year_in_a_date(source):
    assert _flags("It covers contracts since 1999.", source) == []


def test_a_bare_number_does_not_vouch_for_a_year():
    assert _flags("It started in 1999.", "There were 99 bottles.") == ["1999"]


def test_the_wrong_century_or_year_is_still_flagged():
    assert _flags("It covers contracts since 1998.", "Contracts entered after 6/1/99.") == ["1998"]


def test_exact_matches_still_pass_as_before():
    assert _flags("Due Friday, 14 July, $5,000.", "Due Friday 14 July. Amount $5,000.") == []
