import json
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).parent

IN_TOK_PER_S = 10
OUT_TOK_PER_S = 20
PRICES = {
    "realtime-2.1": {"input": 32.0, "cached": 0.40, "output": 64.0},
    "realtime-2.1-mini": {"input": 10.0, "cached": 0.30, "output": 20.0},
}
SYSTEM_PROMPT_TOKENS = 400


@dataclass
class Turn:
    candidate_s: float
    examiner_s: float


def standard_test(examiner_share: str) -> list[Turn]:
    if examiner_share == "light":
        p1, p2, p3 = (12, 15, 4), (1, 120, 24), (7, 30, 8)
    else:
        p1, p2, p3 = (12, 15, 9), (1, 120, 40), (7, 30, 20)
    turns = []
    for count, cand, exam in (p1, p2, p3):
        turns += [Turn(cand, exam)] * count
    return turns


def cost(turns: list[Turn], model: str, policy: str) -> dict:
    p = PRICES[model]
    context = SYSTEM_PROMPT_TOKENS
    input_usd = cached_usd = output_usd = 0.0
    window = 8 if policy == "truncate" else None
    history: list[int] = []
    for t in turns:
        new_in = t.candidate_s * IN_TOK_PER_S
        out = t.examiner_s * OUT_TOK_PER_S
        prior = sum(history[-window:]) if window else sum(history)
        prior += SYSTEM_PROMPT_TOKENS
        if policy == "no-cache":
            input_usd += (prior + new_in) * p["input"] / 1e6
        else:
            cached_usd += prior * p["cached"] / 1e6
            input_usd += new_in * p["input"] / 1e6
        output_usd += out * p["output"] / 1e6
        history += [new_in + out]
    total = input_usd + cached_usd + output_usd
    return {
        "input_usd": round(input_usd, 3),
        "cached_usd": round(cached_usd, 3),
        "output_usd": round(output_usd, 3),
        "total_usd": round(total, 3),
        "responses": len(turns),
        "candidate_min": round(sum(t.candidate_s for t in turns) / 60, 1),
        "examiner_min": round(sum(t.examiner_s for t in turns) / 60, 1),
    }


def main() -> None:
    rows = []
    for share in ("light", "heavy"):
        turns = standard_test(share)
        for model in PRICES:
            for policy in ("no-cache", "cached", "truncate"):
                row = {"examiner": share, "model": model, "policy": policy, **cost(turns, model, policy)}
                rows.append(row)
    (HERE / "results.json").write_text(json.dumps(rows, indent=2))
    lines = [
        "| Examiner talk | Model | Context policy | Candidate min | Examiner min | Input | Cached | Output | Total |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        lines.append(
            f"| {r['examiner']} | {r['model']} | {r['policy']} | {r['candidate_min']} | {r['examiner_min']} | "
            f"${r['input_usd']} | ${r['cached_usd']} | ${r['output_usd']} | **${r['total_usd']}** |"
        )
    (HERE / "results.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
