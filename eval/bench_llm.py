"""LLM latency under concurrency against any OpenAI-compatible server (vLLM, Ollama, ...).

Measures time to first token (TTFT) and total time per request with N simultaneous streams, to
answer: can one GPU serve 10-12 students and still answer fast enough?

    python -m eval.bench_llm --base-url http://localhost:8000/v1 --model <name> --streams 12
"""
from __future__ import annotations

import argparse
import asyncio
import time

from openai import AsyncOpenAI

from eval.metrics import latency_summary

SYSTEM = ("You are a friendly IELTS Speaking examiner. Ask one short question at a time. "
          "Reply in at most two sentences.")
TURNS = [
    "Hi, my name is Rahim and I work as a software engineer in Dhaka.",
    "I usually spend my weekends with my family, mostly cooking and watching films.",
    "I think technology has made it easier to learn languages, but it can also distract students.",
]


async def one_stream(client: AsyncOpenAI, model: str, user_text: str) -> tuple[float, float, int]:
    t0 = time.perf_counter()
    first = None
    chars = 0
    stream = await client.chat.completions.create(
        model=model, stream=True, max_tokens=80,
        messages=[{"role": "system", "content": SYSTEM}, {"role": "user", "content": user_text}],
    )
    async for chunk in stream:
        if chunk.choices and chunk.choices[0].delta.content:
            if first is None:
                first = time.perf_counter() - t0
            chars += len(chunk.choices[0].delta.content)
    return first or float("nan"), time.perf_counter() - t0, chars


async def run(base_url: str, model: str, streams: int, rounds: int) -> None:
    client = AsyncOpenAI(base_url=base_url, api_key="local")
    await one_stream(client, model, TURNS[0])  # warm-up, not counted
    ttft: list[float] = []
    total: list[float] = []
    for r in range(rounds):
        res = await asyncio.gather(*[one_stream(client, model, TURNS[(r + i) % len(TURNS)])
                                     for i in range(streams)])
        ttft += [x[0] for x in res]
        total += [x[1] for x in res]
    print(f"streams={streams} rounds={rounds} requests={len(ttft)}")
    print("TTFT  (s):", {k: round(v, 3) for k, v in latency_summary(ttft).items()})
    print("TOTAL (s):", {k: round(v, 3) for k, v in latency_summary(total).items()})


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default="http://localhost:8000/v1")
    ap.add_argument("--model", required=True)
    ap.add_argument("--streams", type=int, default=12)
    ap.add_argument("--rounds", type=int, default=5)
    a = ap.parse_args()
    asyncio.run(run(a.base_url, a.model, a.streams, a.rounds))
