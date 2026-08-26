"""Provenance location: which source passage supports each generated sentence.

The behaviour that matters most is the negative one. A fabricated sentence must
locate NOTHING. If it highlighted a vaguely similar passage instead, the
feature would be worse than useless -- it would dress a hallucination up with
apparent evidence.
"""

from backend.orchestrator.provenance import locate, split_with_offsets

SOURCE = (
    "Hi,\n\n"
    "Can we reschedule our Thursday meeting to Friday at 2pm? I'd like to review "
    "the quarterly report together before it goes out to the wider team.\n\n"
    "I've attached the latest draft so you can take a look beforehand.\n\n"
    "Best regards,\nDavid Robinson"
)


def _spanned(source, entry):
    return [source[s["start"]:s["end"]] for s in entry["spans"]]


def test_offsets_index_the_original_string():
    """Every span must slice back out of the exact text that was passed in."""
    for start, end, chunk in split_with_offsets(SOURCE):
        assert SOURCE[start:end] == chunk


def test_supported_sentence_locates_its_passage():
    result = locate(["The Thursday meeting is proposed to move to Friday at 2pm."], SOURCE)
    spans = _spanned(SOURCE, result[0])
    assert spans, "a directly supported sentence found no source"
    assert "reschedule our Thursday meeting" in spans[0]


def test_fabricated_sentence_locates_nothing():
    result = locate(["The budget was approved at $50,000 by the finance committee."], SOURCE)
    assert result[0]["spans"] == []


def test_generic_sentence_locates_nothing():
    """Stopword overlap alone must not count as evidence."""
    result = locate(["This is a message about the thing that we have."], SOURCE)
    assert result[0]["spans"] == []


def test_numbers_and_times_outrank_plain_words():
    """A shared time is stronger evidence than a shared common noun."""
    result = locate(["The meeting moves to 2pm."], SOURCE)
    assert result[0]["spans"], "a shared time should locate its sentence"
    assert "2pm" in _spanned(SOURCE, result[0])[0]


def test_every_sentence_gets_an_entry_even_with_no_match():
    sentences = ["Friday at 2pm works.", "Nothing here matches at all whatsoever."]
    result = locate(sentences, SOURCE)
    assert [r["sentence"] for r in result] == [0, 1]


def test_empty_source_is_handled():
    result = locate(["Anything at all."], "")
    assert result == [{"sentence": 0, "spans": []}]


def test_empty_sentence_list_is_handled():
    assert locate([], SOURCE) == []


def test_spans_are_capped():
    """A sentence matching everything is not evidence of anything."""
    repetitive = " ".join(["The quarterly report meeting Friday was reviewed."] * 12)
    result = locate(["The quarterly report meeting Friday was reviewed."], repetitive)
    assert len(result[0]["spans"]) <= 2


def test_spans_are_returned_in_document_order():
    result = locate(
        ["The Thursday meeting moves to Friday at 2pm and the quarterly report is attached."],
        SOURCE,
    )
    starts = [s["start"] for s in result[0]["spans"]]
    assert starts == sorted(starts)


def test_summarise_response_includes_provenance():
    """The API contract: /api/summarise carries provenance alongside the summary."""
    import inspect

    from backend.orchestrator import summarise as module

    source = inspect.getsource(module)
    assert '"provenance": locate(' in source, "summarise no longer returns provenance"
