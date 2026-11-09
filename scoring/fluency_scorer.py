"""
Fluency and Coherence (FC) Scorer
Analyzes Speech Rate (WPM), pause frequency/duration, and hesitation patterns.
"""

import json
import os
from typing import Dict, List

class FluencyScorer:
    def __init__(self, fillers_path: str = None):
        self.fillers = {"um", "uh", "er", "ah", "like", "you know", "i mean"}
        if fillers_path and os.path.exists(fillers_path):
            try:
                with open(fillers_path, "r", encoding="utf-8") as f:
                    self.fillers = set(json.load(f))
            except Exception:
                pass

    def evaluate(self, words_data: List[Dict], total_speech_sec: float) -> Dict:
        """
        Calculates:
        - Words Per Minute (WPM)
        - Silent pause counts (>0.4s hesitation gaps)
        - Total silent pause duration
        - Filler word count
        - Predicted Fluency & Coherence Band (0.0 to 9.0)
        """
        if not words_data or total_speech_sec <= 0:
            return {
                "wpm": 0.0,
                "pause_count": 0,
                "total_pause_sec": 0.0,
                "filler_count": 0,
                "band_score": 4.0,
                "feedback": "Insufficient speech sample to evaluate fluency."
            }

        word_count = len(words_data)
        wpm = (word_count / total_speech_sec) * 60.0

        pause_count = 0
        total_pause_sec = 0.0
        filler_count = 0

        for i in range(len(words_data) - 1):
            curr_word = words_data[i]["word"].lower().strip(".,?!")
            if curr_word in self.fillers:
                filler_count += 1

            gap = words_data[i + 1]["start"] - words_data[i]["end"]
            # Pauses greater than 400ms indicate hesitation
            if gap > 0.40:
                pause_count += 1
                total_pause_sec += gap

        # Check last word for filler
        if words_data and words_data[-1]["word"].lower().strip(".,?!") in self.fillers:
            filler_count += 1

        # Official IELTS Fluency Band Mapping Heuristics
        # Band 9: 140-170 WPM, very rare hesitation (<2 pauses per min)
        # Band 7-8: 125-150 WPM, occasional hesitation
        # Band 6: 100-125 WPM, noticeable pauses or fillers
        # Band 5: 75-100 WPM, slow speech with frequent searching for words
        # Band 4: <75 WPM, halting speech
        if wpm >= 140 and pause_count <= 2:
            band = 8.5
            feedback = "Fluent speech with natural rhythm and minimal hesitation."
        elif wpm >= 125 and pause_count <= 5:
            band = 7.5
            feedback = "Speaks at length with good flow. Minor pauses for content rather than language."
        elif wpm >= 105 and pause_count <= 8:
            band = 6.5
            feedback = "Generally speaks with acceptable tempo, but exhibits noticeable hesitations or filler words."
        elif wpm >= 85:
            band = 5.5
            feedback = "Noticeable pauses and speech tempo slowdown while searching for vocabulary or grammar."
        else:
            band = 4.5
            feedback = "Frequent hesitations and pauses cause disjointed delivery."

        # Penalty for excessive filler density (>1 filler per 15 words)
        if filler_count > (word_count / 15):
            band = max(4.0, band - 0.5)
            feedback += f" High filler word density ({filler_count} fillers detected)."

        return {
            "wpm": round(wpm, 1),
            "pause_count": pause_count,
            "total_pause_sec": round(total_pause_sec, 2),
            "filler_count": filler_count,
            "band_score": round(band, 1),
            "feedback": feedback
        }

