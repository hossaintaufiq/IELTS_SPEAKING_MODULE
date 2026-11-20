import json
import math
from pathlib import Path

HERE = Path(__file__).parent

TEST_WALL_S = 14 * 60
CANDIDATE_MIN = 9.0
EXAMINER_MIN = 3.5
LLM_TURNS = 20

STT_RTF = {"base.en": 0.052, "small.en": 0.146}
TTS_RTF = 0.65
LLM_TURN_S = {"qwen3:1.7b": 2.97, "llama3.2:3b": 3.98}

SERVER_USD_PER_MONTH = 150.0
TARGET_UTILISATION = 0.6
CONCURRENT_TARGETS = [5, 10, 15]
API_COST_PER_TEST = {"realtime-2.1-mini (cached)": 0.12, "realtime-2.1, light examiner (cached)": 0.35, "realtime-2.1, heavy examiner (cached)": 0.57}


def machine_seconds(stt: str, llm: str) -> dict:
    stt_s = CANDIDATE_MIN * 60 * STT_RTF[stt]
    tts_s = EXAMINER_MIN * 60 * TTS_RTF
    llm_s = LLM_TURNS * LLM_TURN_S[llm]
    return {"stt_s": round(stt_s, 1), "tts_s": round(tts_s, 1), "llm_s": round(llm_s, 1), "total_s": round(stt_s + tts_s + llm_s, 1)}


def main() -> None:
    rows = []
    for stt in STT_RTF:
        for llm in LLM_TURN_S:
            m = machine_seconds(stt, llm)
            load_per_test = m["total_s"] / TEST_WALL_S
            tests_per_machine_month = 30 * 86400 * TARGET_UTILISATION / m["total_s"]
            cost_per_test = SERVER_USD_PER_MONTH / tests_per_machine_month
            concurrency = {}
            for n in CONCURRENT_TARGETS:
                machines = math.ceil(n * load_per_test / TARGET_UTILISATION)
                concurrency[n] = {"machines": machines, "monthly_usd": machines * SERVER_USD_PER_MONTH}
            row = {
                "stt": stt,
                "llm": llm,
                **m,
                "load_per_concurrent_test": round(load_per_test, 3),
                "tests_per_machine_month_at_target_util": round(tests_per_machine_month),
                "server_cost_per_test_usd_when_full": round(cost_per_test, 3),
                "fleet": concurrency,
            }
            rows.append(row)
    breakeven = []
    for row in rows:
        for n, fleet in row["fleet"].items():
            for name, api in API_COST_PER_TEST.items():
                breakeven.append(
                    {
                        "stt": row["stt"],
                        "llm": row["llm"],
                        "concurrent": n,
                        "api": name,
                        "monthly_fleet_usd": fleet["monthly_usd"],
                        "break_even_tests_per_month": round(fleet["monthly_usd"] / api),
                    }
                )
    out = {
        "assumptions": {
            "server_usd_per_month": SERVER_USD_PER_MONTH,
            "target_utilisation": TARGET_UTILISATION,
            "machine": "4-core laptop class, measured RTFs",
        },
        "per_test": rows,
        "break_even": breakeven,
    }
    (HERE / "results.json").write_text(json.dumps(out, indent=2))
    for r in rows:
        print(r["stt"], r["llm"], r["total_s"], r["tests_per_machine_month_at_target_util"], r["server_cost_per_test_usd_when_full"], {k: v["machines"] for k, v in r["fleet"].items()})
    for b in breakeven:
        if b["stt"] == "base.en" and b["llm"] == "qwen3:1.7b":
            print(b)


if __name__ == "__main__":
    main()
