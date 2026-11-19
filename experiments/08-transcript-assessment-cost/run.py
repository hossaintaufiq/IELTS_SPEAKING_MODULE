import json
from pathlib import Path

import tiktoken

HERE = Path(__file__).parent

TRANSCRIPT_SEGMENTS = [
    "I grew up in a small coastal town in the south of the country. It is a quiet place with narrow streets, a busy fish market and a long beach where people walk in the evening. What I like most about it is the sense of community, because everybody knows each other and neighbours always help when someone has a problem. However, there are not many job opportunities there, so many young people move to the capital.",
    "Technology has changed the way people study in a very significant way. Nowadays students can attend lectures online, search for information in seconds and collaborate with classmates who live in different countries. On the other hand, I believe that it can also be distracting, since notifications and social media constantly compete for our attention, which makes it harder to concentrate.",
    "The most memorable journey I have ever taken was a week in the mountains with my cousins. We hired a small cabin near a frozen lake and spent our days hiking through the forest. Although the weather was extremely cold, we cooked together every night and talked for hours. Looking back, I think it was special because we were completely disconnected from our busy lives.",
]

RUBRIC_PROMPT = (
    "You are an IELTS Speaking assessor. Score the candidate transcript from 0 to 9 in half-band steps on "
    "Fluency and Coherence, Lexical Resource, Grammatical Range and Accuracy. Do not score Pronunciation because "
    "only a transcript is available. For each criterion give a score, two strengths, two weaknesses and one "
    "example quote. Finish with an overall estimate and a short improvement plan. Return valid JSON only."
)

REPORT_OUTPUT_TOKENS = 700
MODELS = {"gpt-4.1-mini": {"input": 0.40, "cached": 0.10, "output": 1.60}}
WORDS_PER_MIN = 130


def build_transcript(words_target: int) -> str:
    text, words = [], 0
    while words < words_target:
        for seg in TRANSCRIPT_SEGMENTS:
            text.append(seg)
            words += len(seg.split())
            if words >= words_target:
                break
    return " ".join(text)


def main() -> None:
    enc = tiktoken.get_encoding("o200k_base")
    rubric_tokens = len(enc.encode(RUBRIC_PROMPT))
    rows = []
    for minutes in (3, 9, 14):
        words = minutes * WORDS_PER_MIN
        transcript = build_transcript(words)
        tokens = len(enc.encode(transcript))
        for model, p, rubric in [(m, p, r) for m, p in MODELS.items() for r in (rubric_tokens, 2000)]:
            input_tokens = rubric + tokens
            cost = (input_tokens * p["input"] + REPORT_OUTPUT_TOKENS * p["output"]) / 1e6
            rows.append(
                {
                    "candidate_speech_min": minutes,
                    "words": len(transcript.split()),
                    "transcript_tokens": tokens,
                    "rubric_tokens": rubric,
                    "model": model,
                    "cost_usd": round(cost, 5),
                    "cost_per_1000_assessments_usd": round(cost * 1000, 2),
                }
            )
    (HERE / "results.json").write_text(json.dumps(rows, indent=2))
    for r in rows:
        print(r)


if __name__ == "__main__":
    main()
