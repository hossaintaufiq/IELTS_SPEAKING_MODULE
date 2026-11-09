"""
Pronunciation (PR) Scorer
Evaluates phonetic clarity, rhythm regularity, and acoustic continuity.
"""

from typing import Dict, List

class PronunciationScorer:
    def __init__(self):
        pass

    def evaluate(self, words_data: List[Dict]) -> Dict:
        """
        Evaluates acoustic timing stability and speech chunking regularity.
        """
        if not words_data or len(words_data) < 4:
            return {
                "clarity_score": 0.5,
                "rhythm_regularity": 0.5,
                "band_score": 5.0,
                "feedback": "Speech sample insufficient for detailed pronunciation analysis."
            }

        # Calculate average word duration & duration variance
        durations = [(w["end"] - w["start"]) for w in words_data if (w["end"] - w["start"]) > 0]
        avg_duration = sum(durations) / len(durations)
        variance = sum((d - avg_duration) ** 2 for d in durations) / len(durations)

        # Confidence probabilities from Whisper/Acoustic model
        probabilities = [w.get("prob", 0.90) for w in words_data]
        mean_confidence = sum(probabilities) / len(probabilities)

        # Band Heuristics:
        # High confidence (>0.90) + stable rhythm = Band 7.5 - 8.5
        # Moderate confidence (0.80 - 0.90) = Band 6.5
        # Low confidence (<0.80) or extreme rhythm irregularity = Band 5.0 - 5.5
        if mean_confidence >= 0.92 and variance < 0.12:
            band = 8.0
            feedback = "Clear, articulate phoneme delivery with natural rhythm and effective sentence stress."
        elif mean_confidence >= 0.85:
            band = 7.0
            feedback = "Generally clear pronunciation; easy to understand despite occasional accent influence."
        elif mean_confidence >= 0.75:
            band = 6.0
            feedback = "Pronunciation is understandable overall, but occasional mispronunciations require listener effort."
        else:
            band = 5.0
            feedback = "Frequent phonetic inaccuracies or irregular rhythm reduce intelligibility."

        return {
            "acoustic_confidence": round(mean_confidence, 2),
            "rhythm_variance": round(variance, 3),
            "band_score": round(band, 1),
            "feedback": feedback
        }

