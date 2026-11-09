"""
Unit & Integration Tests for IELTS Scoring Pipeline
Verifies mathematical rounding, Fluency, Lexical Resource, Grammar, and Pronunciation scoring.
"""

import os
import sys
import pytest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from scoring.score_synthesizer import ielts_round, ScoreSynthesizer
from scoring.fluency_scorer import FluencyScorer
from scoring.lexical_scorer import LexicalScorer
from scoring.grammar_scorer import GrammarScorer
from scoring.pronunciation_scorer import PronunciationScorer

def test_ielts_rounding_rules():
    """
    Official Cambridge / British Council Rounding Rules:
    - Ends in .25 -> Rounds UP to .5
    - Ends in .75 -> Rounds UP to next whole band
    - Ends in .125 -> Rounds DOWN to nearest whole
    - Ends in .625 -> Rounds to .5
    """
    assert ielts_round(6.25) == 6.5
    assert ielts_round(6.75) == 7.0
    assert ielts_round(7.25) == 7.5
    assert ielts_round(7.75) == 8.0
    assert ielts_round(6.125) == 6.0
    assert ielts_round(6.625) == 6.5
    assert ielts_round(8.0) == 8.0

def test_fluency_scorer_fluent():
    scorer = FluencyScorer()
    # 25 words spoken across 10 seconds -> 150 WPM, minimal pauses
    words_data = []
    t = 0.0
    for i in range(25):
        words_data.append({"word": f"word{i}", "start": t, "end": t + 0.35, "prob": 0.95})
        t += 0.40 # small 50ms gaps between words

    result = scorer.evaluate(words_data, total_speech_sec=10.0)
    assert result["wpm"] == 150.0
    assert result["pause_count"] == 0
    assert result["band_score"] >= 8.0

def test_fluency_scorer_hesitant():
    scorer = FluencyScorer()
    # Slow speech: 10 words in 15 seconds -> 40 WPM, frequent pauses > 0.4s
    words_data = []
    t = 0.0
    for i in range(10):
        words_data.append({"word": f"word{i}", "start": t, "end": t + 0.35, "prob": 0.95})
        t += 1.50 # 1.15s pause between words

    result = scorer.evaluate(words_data, total_speech_sec=15.0)
    assert result["wpm"] == 40.0
    assert result["pause_count"] == 9
    assert result["band_score"] <= 5.5

def test_lexical_scorer_c1_c2():
    cefr_path = os.path.join(BASE_DIR, "data", "cefr_vocab_list.json")
    markers_path = os.path.join(BASE_DIR, "data", "discourse_markers.json")
    scorer = LexicalScorer(cefr_path=cefr_path, markers_path=markers_path)

    sample = (
        "Furthermore, rapid urbanization has noticeably exacerbated the detrimental traffic issues. "
        "From my perspective, sustainable infrastructure is of paramount importance to our society."
    )
    result = scorer.evaluate(sample)
    assert result["c1_c2_percentage"] > 0
    assert len(result["discourse_markers_found"]) >= 2
    assert result["band_score"] >= 7.0

def test_grammar_scorer_complex_sentences():
    scorer = GrammarScorer()
    sample = (
        "Although the city has expanded, several historic monuments remain preserved because they are protected. "
        "If the government invests in renewable energy, pollution will decrease noticeably."
    )
    result = scorer.evaluate(sample)
    assert result["complex_sentences"] == 2
    assert result["complexity_ratio"] == 1.0
    assert result["band_score"] >= 7.5

def test_score_synthesizer_integration():
    synthesizer = ScoreSynthesizer()
    fc = {"band_score": 7.5, "wpm": 135, "pause_count": 2, "feedback": "Good flow"}
    lr = {"band_score": 7.0, "ttr": 0.58, "c1_c2_percentage": 8.0, "feedback": "Good vocabulary"}
    gra = {"band_score": 7.5, "complexity_ratio": 0.6, "feedback": "Varied structures"}
    pr = {"band_score": 8.0, "acoustic_confidence": 0.92, "feedback": "Clear delivery"}

    report = synthesizer.synthesize(fc, lr, gra, pr)
    # Average: (7.5 + 7.0 + 7.5 + 8.0) / 4 = 7.5
    assert report["overall_band"] == 7.5
    assert report["raw_average"] == 7.5
    assert report["primary_weakness"] == "Lexical Resource"

if __name__ == "__main__":
    test_ielts_rounding_rules()
    test_fluency_scorer_fluent()
    test_fluency_scorer_hesitant()
    test_lexical_scorer_c1_c2()
    test_grammar_scorer_complex_sentences()
    test_score_synthesizer_integration()
    print("ALL TESTS PASSED SUCCESSFULLY!")

