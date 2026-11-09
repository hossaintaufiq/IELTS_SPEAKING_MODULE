"""
IELTS Score Synthesizer
Combines Fluency & Coherence, Lexical Resource, Grammatical Range & Accuracy,
and Pronunciation using official British Council / Cambridge rounding rules.
"""

from typing import Dict

def ielts_round(raw_score: float) -> float:
    """
    Official IELTS Rounding Rule:
    - If the average ends in .25, round UP to the next half band (e.g. 6.25 -> 6.5).
    - If the average ends in .75, round UP to the next whole band (e.g. 6.75 -> 7.0).
    - Otherwise, round to the nearest whole or half band.
    """
    whole = int(raw_score)
    fraction = raw_score - whole

    if fraction < 0.25:
        return float(whole)
    elif fraction < 0.75:
        return float(whole) + 0.5
    else:
        return float(whole + 1)

class ScoreSynthesizer:
    def __init__(self):
        pass

    def synthesize(self, fc_res: Dict, lr_res: Dict, gra_res: Dict, pr_res: Dict) -> Dict:
        fc_band = fc_res.get("band_score", 5.0)
        lr_band = lr_res.get("band_score", 5.0)
        gra_band = gra_res.get("band_score", 5.0)
        pr_band = pr_res.get("band_score", 5.0)

        raw_average = (fc_band + lr_band + gra_band + pr_band) / 4.0
        final_band = ielts_round(raw_average)

        # Generate targeted recommendations based on the weakest criterion
        scores = {
            "Fluency and Coherence": fc_band,
            "Lexical Resource": lr_band,
            "Grammatical Range and Accuracy": gra_band,
            "Pronunciation": pr_band
        }
        weakest_area = min(scores, key=scores.get)

        recommendations = []
        if weakest_area == "Fluency and Coherence":
            recommendations.append("Practice speaking in 2-minute sustained turns without stopping to reduce hesitation gaps.")
        elif weakest_area == "Lexical Resource":
            recommendations.append("Incorporate more C1/C2 collocations and topic-specific vocabulary instead of repeating basic adjectives.")
        elif weakest_area == "Grammatical Range and Accuracy":
            recommendations.append("Increase usage of conditional structures ('If I had...', 'Were it not for...') and relative clauses.")
        elif weakest_area == "Pronunciation":
            recommendations.append("Focus on sentence stress and intonation rhythm to avoid a flat or hesitant delivery.")

        return {
            "overall_band": final_band,
            "raw_average": round(raw_average, 2),
            "breakdown": {
                "fluency_and_coherence": {
                    "band": fc_band,
                    "wpm": fc_res.get("wpm", 0),
                    "pause_count": fc_res.get("pause_count", 0),
                    "feedback": fc_res.get("feedback", "")
                },
                "lexical_resource": {
                    "band": lr_band,
                    "ttr": lr_res.get("ttr", 0),
                    "c1_c2_percentage": lr_res.get("c1_c2_percentage", 0),
                    "feedback": lr_res.get("feedback", "")
                },
                "grammatical_range_and_accuracy": {
                    "band": gra_band,
                    "complexity_ratio": gra_res.get("complexity_ratio", 0),
                    "feedback": gra_res.get("feedback", "")
                },
                "pronunciation": {
                    "band": pr_band,
                    "acoustic_confidence": pr_res.get("acoustic_confidence", 0),
                    "feedback": pr_res.get("feedback", "")
                }
            },
            "primary_weakness": weakest_area,
            "key_recommendation": recommendations[0] if recommendations else "Continue practicing all 4 criteria regularly."
        }

