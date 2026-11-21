from eval.metrics import latency_summary, percentile, wer


def test_wer_identical_is_zero():
    assert wer("I live in Dhaka.", "i live in dhaka").wer == 0


def test_wer_counts_each_error_type():
    r = wer("the cat sat on the mat", "the cat sit on mat today")
    assert (r.substitutions, r.deletions, r.insertions) == (1, 1, 1)
    assert r.wer == 3 / 6


def test_wer_empty_reference():
    assert wer("", "").wer == 0
    assert wer("", "hello").wer == 1


def test_percentile_and_summary():
    assert percentile([1, 2, 3, 4], 50) == 2.5
    s = latency_summary([1.0, 2.0, 3.0])
    assert s["p50"] == 2.0 and s["max"] == 3.0 and s["n"] == 3
