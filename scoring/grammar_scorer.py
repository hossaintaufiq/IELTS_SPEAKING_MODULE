"""
Grammatical Range and Accuracy (GRA) Scorer
Evaluates syntactic complexity, clause subordination, and structural consistency.
"""

import re
from typing import Dict, List

class GrammarScorer:
    def __init__(self):
        # Subordinate conjunctions & relative pronouns signaling complex sentences
        self.complex_markers = {
            "because", "although", "even though", "since", "while", "whereas",
            "if", "unless", "provided that", "which", "who", "whom", "whose",
            "where", "that", "in order to", "so that", "despite"
        }

    def _split_sentences(self, text: str) -> List[str]:
        # Split by punctuation
        sents = re.split(r"[.!?]+", text)
        return [s.strip() for s in sents if len(s.strip()) > 3]

    def evaluate(self, transcript: str) -> Dict:
        sentences = self._split_sentences(transcript)
        total_sentences = len(sentences)

        if total_sentences == 0:
            return {
                "sentence_count": 0,
                "complex_sentence_ratio": 0.0,
                "band_score": 4.0,
                "feedback": "Not enough complete sentences to assess grammatical range."
            }

        complex_sentence_count = 0
        markers_found = []

        for sent in sentences:
            words = set(re.findall(r"\b[a-zA-Z-]+\b", sent.lower()))
            matched = words.intersection(self.complex_markers)
            if matched:
                complex_sentence_count += 1
                markers_found.extend(list(matched))

        complexity_ratio = complex_sentence_count / total_sentences

        # Band Heuristics:
        # Band 8-9: Wide range of complex structures used flexibly and accurately (>60% complex sentences)
        # Band 7: Frequently produces complex sentences, though some minor errors persist (>40% complex sentences)
        # Band 6: Mix of simple and complex structures, but limited flexibility (>20% complex sentences)
        # Band 5: Produces basic sentence forms, errors are frequent
        if complexity_ratio >= 0.65:
            band = 8.0
            feedback = "Impressive variety of complex and compound sentence structures used naturally."
        elif complexity_ratio >= 0.40:
            band = 7.0
            feedback = "Good grammatical range. Frequently employs subordinate clauses and varied structures."
        elif complexity_ratio >= 0.20:
            band = 6.0
            feedback = "Uses a mix of simple and complex sentences. Some tendency to stick to familiar sentence frames."
        elif total_sentences >= 2:
            band = 5.0
            feedback = "Relies mainly on simple structures. Needs more compound and complex sentences to raise score."
        else:
            band = 4.5
            feedback = "Grammar structures are very basic and limited."

        return {
            "sentence_count": total_sentences,
            "complex_sentences": complex_sentence_count,
            "complexity_ratio": round(complexity_ratio, 2),
            "structural_markers": list(set(markers_found)),
            "band_score": round(band, 1),
            "feedback": feedback
        }

