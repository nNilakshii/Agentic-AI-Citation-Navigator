from app.core.segmentation import split_sentences


def texts(source: str) -> list[str]:
    return [source[start:end] for start, end in split_sentences(source)]


def test_offsets_index_back_into_the_source():
    source = "First sentence here. Second one follows. Third ends it."
    for start, end in split_sentences(source):
        assert source[start:end] in texts(source)
    assert texts(source) == [
        "First sentence here.",
        "Second one follows.",
        "Third ends it.",
    ]


def test_spans_are_ordered_and_do_not_overlap():
    source = "Alpha runs first. Beta runs second. Gamma runs third."
    spans = split_sentences(source)
    for (_, end), (next_start, _) in zip(spans, spans[1:]):
        assert end <= next_start


def test_does_not_split_on_et_al():
    source = "This follows Vaswani et al. The setup is unchanged."
    assert texts(source) == ["This follows Vaswani et al. The setup is unchanged."]


def test_does_not_split_on_figure_reference_before_a_digit():
    source = "Accuracy improves as shown in Fig. 3 and the trend holds."
    assert len(split_sentences(source)) == 1


def test_does_not_split_inside_a_decimal():
    source = "The threshold was p < 0.05 across every run."
    assert len(split_sentences(source)) == 1


def test_does_not_split_on_an_initial():
    source = "The dataset was released by J. Doe and later extended."
    assert len(split_sentences(source)) == 1


def test_splits_on_a_paragraph_break_without_punctuation():
    source = "3 Method\n\nWe describe the approach."
    assert texts(source) == ["3 Method", "We describe the approach."]


def test_keeps_closing_quotes_with_the_sentence():
    source = 'He called it "grounding." The term stuck.'
    assert texts(source) == ['He called it "grounding."', "The term stuck."]


def test_drops_whitespace_and_stray_fragments():
    source = "Real sentence here.\n\n  \n\n.\n\nAnother real one."
    assert texts(source) == ["Real sentence here.", "Another real one."]


def test_handles_empty_input():
    assert split_sentences("") == []


def test_splits_an_over_long_span_at_whitespace():
    source = " ".join(["token"] * 500)  # 2999 chars, no terminal punctuation
    spans = split_sentences(source, max_chars=1000)
    assert len(spans) > 1
    for start, end in spans:
        assert end - start <= 1000
        assert source[start:end] == source[start:end].strip()


def test_max_length_split_preserves_offsets_and_order():
    source = "x" * 40 + " " + "y" * 40
    spans = split_sentences(source, max_chars=50)
    assert [source[s:e] for s, e in spans] == ["x" * 40, "y" * 40]


def test_ordinary_sentences_are_untouched_by_the_cap():
    source = "Short one. Short two."
    assert split_sentences(source) == split_sentences(source, max_chars=10_000)
