import json
import sys
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).parent
URL = "http://localhost:11434/api/chat"

SYSTEM = (
    "You are an IELTS Speaking examiner. Reply with one short follow-up question of at most 20 words. "
    "Do not give feedback, do not explain, do not use lists."
)

ANSWERS = [
    "I live in a small town near the sea. I like it because it is quiet, but sometimes it is boring for young people.",
    "I study computer science at university. I chose it because I enjoy solving problems and I think there are many jobs.",
    "In my free time I usually play football with my friends, although recently I have been learning the guitar.",
    "I think technology has made communication faster, but people sometimes forget how to talk face to face.",
    "Last year I travelled to Japan with my family. The food was incredible and the trains were always on time.",
]


def chat(model: str, answer: str) -> dict:
    body = json.dumps(
        {
            "model": model,
            "stream": False,
            "think": False,
            "options": {"temperature": 0.4, "num_predict": 60},
            "messages": [
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": answer},
            ],
        }
    ).encode()
    req = urllib.request.Request(URL, body, {"Content-Type": "application/json"})
    t0 = time.perf_counter()
    with urllib.request.urlopen(req, timeout=300) as r:
        data = json.loads(r.read())
    wall = time.perf_counter() - t0
    return {
        "reply": data["message"]["content"].strip(),
        "wall_s": round(wall, 2),
        "load_s": round(data.get("load_duration", 0) / 1e9, 2),
        "prompt_tokens": data.get("prompt_eval_count"),
        "output_tokens": data.get("eval_count"),
        "tokens_per_s": round(data["eval_count"] / (data["eval_duration"] / 1e9), 1),
    }


def valid(reply: str) -> bool:
    return reply.count("?") == 1 and reply.endswith("?") and len(reply.split()) <= 20


def main(models: list[str]) -> None:
    out = {}
    summary = {}
    for model in models:
        chat(model, "Hello.")
        runs = [chat(model, a) for a in ANSWERS]
        out[model] = runs
        walls = sorted(r["wall_s"] for r in runs)
        summary[model] = {
            "median_wall_s": walls[len(walls) // 2],
            "median_tokens_per_s": sorted(r["tokens_per_s"] for r in runs)[len(runs) // 2],
            "valid_replies": f"{sum(valid(r['reply']) for r in runs)}/{len(runs)}",
        }
        for a, r in zip(ANSWERS, runs):
            print(model, r["wall_s"], r["tokens_per_s"], "|", r["reply"], flush=True)
    (HERE / "results.json").write_text(json.dumps({"summary": summary, "runs": out}, indent=2))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main(sys.argv[1:] or ["qwen3:0.6b"])
