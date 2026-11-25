"""Automated end-to-end probe: talk to the running test server like the browser does.

Synthesises a spoken sentence with Kokoro, streams it as 16 kHz PCM in real time over /ws, and
prints every server event with timestamps. Lets us measure STT correctness and reply delay
without a human speaking. Run it ON the GPU box (needs kokoro-onnx, websockets, numpy).

    python -m eval.ws_probe "My name is Rahim Ahmed and I live in Dhaka." --wait 25
"""
from __future__ import annotations

import argparse
import asyncio
import json
import time

import numpy as np
import websockets


def synth(text: str, model: str, voices: str, voice: str = "am_adam") -> np.ndarray:
    from kokoro_onnx import Kokoro

    samples, sr = Kokoro(model, voices).create(text, voice=voice, speed=1.0, lang="en-us")
    n = int(len(samples) * 16000 / sr)
    return np.interp(np.linspace(0, len(samples) - 1, n), np.arange(len(samples)), samples).astype(np.float32)


async def run(args) -> None:
    pcm16 = (synth(args.text, args.model, args.voices) * 32767).astype(np.int16)
    pcm16 = np.concatenate([pcm16, np.zeros(16000 * 2, dtype=np.int16)])   # 2 s of silence ends the turn
    t0 = time.perf_counter()
    audio_bytes = 0
    t_first_audio_after = None
    t_sent_end = None

    async with websockets.connect(f"ws://{args.host}/ws", max_size=None) as ws:
        async def reader():
            nonlocal audio_bytes, t_first_audio_after
            async for m in ws:
                now = time.perf_counter() - t0
                if isinstance(m, bytes):
                    audio_bytes += len(m)
                    if t_sent_end is not None and t_first_audio_after is None and now > t_sent_end:
                        t_first_audio_after = now
                    continue
                e = json.loads(m)
                if e["type"] == "timer":
                    continue
                print(f"{now:6.2f}s  {e['type']:<10} {e.get('role','')} {e.get('text') or e.get('phase') or e.get('seconds') or ''}")

        task = asyncio.create_task(reader())
        await ws.send(json.dumps({"action": "start"}))
        # Wait for the intro to begin (the first connection loads models, ~15 s), then for it to finish.
        while audio_bytes == 0 and time.perf_counter() - t0 < 60:
            await asyncio.sleep(0.2)
        last, quiet_since = audio_bytes, time.perf_counter()
        while time.perf_counter() - quiet_since < 1.5:
            await asyncio.sleep(0.2)
            if audio_bytes != last:
                last, quiet_since = audio_bytes, time.perf_counter()
        print(f"{time.perf_counter()-t0:6.2f}s  >>> candidate starts speaking: {args.text!r}")
        speech_len = len(pcm16) - 32000
        for i in range(0, len(pcm16), 640):                  # 40 ms chunks, real-time pace
            await ws.send(pcm16[i:i + 640].tobytes())
            if i + 640 >= speech_len and t_sent_end is None:
                t_sent_end = time.perf_counter() - t0        # the moment real speech ends
                print(f"{t_sent_end:6.2f}s  >>> candidate stops talking (2 s of silence follows)")
            await asyncio.sleep(0.04)
        await asyncio.sleep(args.wait)
        await ws.send(json.dumps({"action": "end"}))
        await asyncio.sleep(1)
        task.cancel()
    if t_first_audio_after:
        print(f"first examiner reply audio {t_first_audio_after - t_sent_end:.2f}s after the candidate stopped talking")
    print(f"examiner audio received: {audio_bytes/48000:.1f}s")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("text")
    ap.add_argument("--host", default="localhost:8081")
    ap.add_argument("--model", default="models/cache/kokoro-v1.0.onnx")
    ap.add_argument("--voices", default="models/cache/voices-v1.0.bin")
    ap.add_argument("--intro-wait", type=float, default=22.0)
    ap.add_argument("--wait", type=float, default=20.0)
    asyncio.run(run(ap.parse_args()))
