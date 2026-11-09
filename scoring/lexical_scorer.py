"""
Lexical Resource (LR) Scorer
Evaluates vocabulary range, Type-Token Ratio (TTR), CEFR tiers, and discourse marker usage.
"""

import json
import os
import re
from typing import Dict, List, Set

class LexicalScorer:
    def __init__(self, cefr_path: str = None, markers_path: str = None):
        self.c1_c2_words: Set[str] = set()
        self.b1_b2_words: Set[str] = set()
        self.discourse_markers: List[str] = []

        if cefr_path and os.path.exists(cefr_path):
            try:
                with open(cefr_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.c1_c2_words = set(w.lower() for w in data.get("C1_C2", []))
                    self.b1_b2_words = set(w.lower() for w in data.get("B1_B2", []))
            except Exception:
                pass

        if markers_path and os.path.exists(markers_path):
            try:
                with open(markers_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    for group in data.values():
                        self.discourse_markers.extend([m.lower() for m in group])
            except Exception:
                pass

    def _tokenize(self, text: str) -> List[str]:
        words = re.findall(r"\b[a-zA-Z]{2,}\b", text.lower())
        return words

    def evaluate(self, transcript: str) -> Dict:
        tokens = self._tokenize(transcript)
        total_tokens = len(tokens)

        if total_tokens < 5:
            return {
                "ttr": 0.0,
                "c1_c2_percentage": 0.0,
                "discourse_markers_found": [],
                "band_score": 4.0,
                "feedback": "Utterance too brief to assess vocabulary range."
            }

        unique_tokens = set(tokens)
        ttr = len(unique_tokens) / total_tokens

        # Check CEFR Advanced Words
        c1_matches = [w for w in unique_tokens if w in self.c1_c2_words]
        b1_matches = [w for w in unique_tokens if w in self.b1_b2_words]
        c1_ratio = (len(c1_matches) / max(len(unique_tokens), 1)) * 100.0

        # Check Discourse Markers
        lower_text = transcript.lower()
        found_markers = [m for m in self.discourse_markers if m in lower_text]

        # IELTS Band Mapping Heuristics for Lexical Resource
        # Band 8-9: Rich varied vocabulary, flexible paraphrasing, uncommon idioms (C1 ratio > 12%, TTR > 0.65)
        # Band 7: Varied vocabulary, some less common collocations (C1 ratio > 6%, TTR > 0.55)
        # Band 6: Adequate vocabulary for discussion, some inappropriate choices
        # Band 5: Limited vocabulary, repetitive use of basic words
        if c1_ratio >= 10.0 and ttr >= 0.60 and len(found_markers) >= 2:
            band = 8.0
            feedback = "Sophisticated vocabulary with effective use of less common idioms and cohesive markers."
        elif (c1_ratio >= 5.0 or len(found_markers) >= 2) and ttr >= 0.52:
            band = 7.0
            feedback = "Good vocabulary range. Successfully uses topic-specific expressions and discourse markers."
        elif ttr >= 0.45:
            band = 6.0
            feedback = "Adequate lexical resource. Conveys meaning successfully but relies on common everyday phrasing."
        elif ttr >= 0.35:
            band = 5.0
            feedback = "Limited vocabulary range with repetition of basic words. Needs more academic variety."
        else:
            band = 4.5
            feedback = "Narrow vocabulary range causing difficulty with expression."

        return {
            "total_words": total_tokens,
            "unique_words": len(unique_tokens),
            "ttr": round(ttr, 3),
            "c1_c2_percentage": round(c1_ratio, 1),
            "c1_matches": c1_matches[:5],
            "discourse_markers_found": list(set(found_markers)),
            "band_score": round(band, 1),
            "feedback": feedback
        }

