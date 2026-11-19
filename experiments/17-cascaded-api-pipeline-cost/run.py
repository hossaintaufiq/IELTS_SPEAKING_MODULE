import json
from pathlib import Path

HERE = Path(__file__).parent

CANDIDATE_MIN = 9.0
EXAMINER_MIN = 3.5
LLM_TURNS = 20
WORDS_PER_MIN = 130
TOKENS_PER_WORD = 1.4

STT_USD_PER_MIN = {"gpt-4o-mini-transcribe": 0.003, "gpt-4o-transcribe": 0.006}
TTS_USD_PER_MIN = {"gpt-4o-mini-tts": 0.015}
LLM_USD_PER_M = {"gpt-4.1-mini": {"input": 0.40, "cached": 0.10, "output": 1.60}}

PART3_EXAMINER_MIN = 56 / 60
SYSTEM_PROMPT_TOKENS = 600
EXAMINER_WORDS_PER_TURN = 25


def llm_cost(model: str) -> float:
    p = LLM_USD_PER_M[model]
    history = 0
    total = 0.0
    cand_tokens = CANDIDATE_MIN * WORDS_PER_MIN * TOKENS_PER_WORD / LLM_TURNS
    out_tokens = EXAMINER_WORDS_PER_TURN * TOKENS_PER_WORD
    for _ in range(LLM_TURNS):
        total += (history + SYSTEM_PROMPT_TOKENS) * p["cached"] / 1e6
        total += cand_tokens * p["input"] / 1e6
        total += out_tokens * p["output"] / 1e6
        history += cand_tokens + out_tokens
    return total


def main() -> None:
    rows = []
    for variant, spoken_min in (("all turns synthesised", EXAMINER_MIN), ("Part 3 only synthesised", PART3_EXAMINER_MIN)):
        for stt, stt_rate in STT_USD_PER_MIN.items():
            for tts, tts_rate in TTS_USD_PER_MIN.items():
                for llm in LLM_USD_PER_M:
                    parts = {
                        "stt_usd": CANDIDATE_MIN * stt_rate,
                        "llm_usd": llm_cost(llm),
                        "tts_usd": spoken_min * tts_rate,
                    }
                    rows.append(
                        {
                            "variant": variant,
                            "stt": stt,
                            "llm": llm,
                            "tts": tts,
                            **{k: round(v, 4) for k, v in parts.items()},
                            "total_usd": round(sum(parts.values()), 3),
                        }
                    )
    (HERE / "results.json").write_text(json.dumps(rows, indent=2))
    for r in rows:
        print(r)


if __name__ == "__main__":
    main()
