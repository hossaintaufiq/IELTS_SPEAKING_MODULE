import json
from pathlib import Path

HERE = Path(__file__).parent

IN_TOK_PER_S = 10
OUT_TOK_PER_S = 20
SYSTEM_PROMPT_TOKENS = 400
PRICES = {
    "realtime-2.1": {"input": 32.0, "cached": 0.40, "output": 64.0},
    "realtime-2.1-mini": {"input": 10.0, "cached": 0.30, "output": 20.0},
}
STT_API_USD_PER_MIN = 0.003

PARTS = {
    "part1": [(15, 4)] * 12,
    "part2": [(120, 24)],
    "part3": [(30, 8)] * 7,
}

SCENARIOS = {
    "A. All Realtime full": {"part1": "realtime-2.1", "part2": "realtime-2.1", "part3": "realtime-2.1"},
    "B. All Realtime mini": {"part1": "realtime-2.1-mini", "part2": "realtime-2.1-mini", "part3": "realtime-2.1-mini"},
    "C. Part 1 scripted + API transcription, rest Realtime full": {"part1": "scripted-api", "part2": "realtime-2.1", "part3": "realtime-2.1"},
    "D. Parts 1 and 2 scripted + API transcription, Part 3 Realtime full": {"part1": "scripted-api", "part2": "scripted-api", "part3": "realtime-2.1"},
    "E. Parts 1 and 2 scripted + API transcription, Part 3 Realtime mini": {"part1": "scripted-api", "part2": "scripted-api", "part3": "realtime-2.1-mini"},
    "F. Fully scripted with local transcription (no voice API)": {"part1": "scripted-local", "part2": "scripted-local", "part3": "scripted-local"},
}


def realtime_cost(turns: list[tuple[int, int]], model: str) -> float:
    p = PRICES[model]
    history = 0
    total = 0.0
    for cand_s, exam_s in turns:
        new_in = cand_s * IN_TOK_PER_S
        out = exam_s * OUT_TOK_PER_S
        prior = history + SYSTEM_PROMPT_TOKENS
        total += (prior * p["cached"] + new_in * p["input"] + out * p["output"]) / 1e6
        history += new_in + out
    return total


def part_cost(turns: list[tuple[int, int]], mode: str) -> float:
    if mode.startswith("realtime"):
        return realtime_cost(turns, mode)
    if mode == "scripted-api":
        return sum(c for c, _ in turns) / 60 * STT_API_USD_PER_MIN
    return 0.0


def main() -> None:
    rows = []
    for name, plan in SCENARIOS.items():
        parts = {part: round(part_cost(PARTS[part], mode), 4) for part, mode in plan.items()}
        rows.append({"scenario": name, **parts, "total_usd": round(sum(parts.values()), 3)})
    base = rows[0]["total_usd"]
    for r in rows:
        r["vs_all_realtime_full_pct"] = round((r["total_usd"] / base - 1) * 100)
    (HERE / "results.json").write_text(json.dumps(rows, indent=2))
    lines = ["| Scenario | Part 1 | Part 2 | Part 3 | Total | vs A |", "|---|---|---|---|---|---|"]
    for r in rows:
        lines.append(f"| {r['scenario']} | ${r['part1']} | ${r['part2']} | ${r['part3']} | **${r['total_usd']}** | {r['vs_all_realtime_full_pct']}% |")
    (HERE / "results.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
