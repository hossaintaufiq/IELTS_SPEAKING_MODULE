"""Kokoro TTS speed: time to generate a sentence and real-time factor (RTF).

    python -m eval.bench_tts --model models/cache/kokoro-v1.0.onnx --voices models/cache/voices-v1.0.bin

Note: kokoro-onnx runs on CPU by default. Whether it uses the GPU depends on the installed
onnxruntime build; check with the printed providers. First-audio time here is for a whole
sentence, not true streaming.
"""
from __future__ import annotations

import argparse
import time

from eval.metrics import latency_summary

SENTENCES = [
    "Good morning. My name is Sarah, and I'll be your examiner today.",
    "Let's talk about your hometown. Where are you from?",
    "Now I'm going to give you a topic, and I'd like you to talk about it for one to two minutes.",
]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--voices", required=True)
    ap.add_argument("--voice", default="bf_emma")
    ap.add_argument("--runs", type=int, default=5)
    a = ap.parse_args()

    from kokoro_onnx import Kokoro  # imported late: GPU box only

    k = Kokoro(a.model, a.voices)
    k.create(SENTENCES[0], voice=a.voice, speed=0.95, lang="en-gb")  # warm-up
    gen, rtf = [], []
    for _ in range(a.runs):
        for text in SENTENCES:
            t0 = time.perf_counter()
            samples, sr = k.create(text, voice=a.voice, speed=0.95, lang="en-gb")
            dt = time.perf_counter() - t0
            gen.append(dt)
            rtf.append(dt / (len(samples) / sr))
    print("generation time (s):", {k_: round(v, 3) for k_, v in latency_summary(gen).items()})
    print("RTF:", {k_: round(v, 3) for k_, v in latency_summary(rtf).items()})


if __name__ == "__main__":
    main()
