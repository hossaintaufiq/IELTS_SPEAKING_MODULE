"""Automated full-exam probe: a scripted candidate takes Part 1 -> 2 -> 3 against the live server.

Each answer is synthesised with Kokoro and streamed as 16 kHz PCM like the browser does. Answers
contain distinctive details (names, places) so we can see whether the examiner's next questions
actually follow them. Run ON the GPU box:  python -m eval.ws_flow
"""
from __future__ import annotations

import argparse
import asyncio
import json
import time

import numpy as np
import websockets

from eval.ws_probe import synth

PART1 = [
    "My name is Rahim Ahmed.",
    "I live in Chittagong, near the port. My family has lived there for three generations.",
    "I work as a software engineer, mostly building mobile apps for a small startup. I really enjoy it because I can work on my own ideas.",
]
PART2 = ("I want to talk about a place I enjoy visiting, which is Patenga beach near my home. I usually go there on Friday evenings "
         "with my younger sister Nadia. We walk along the sand, eat spicy peanuts and watch the ships coming in. "
         "I enjoy it because it is the only place where I can forget about work and just listen to the waves.")
PART2_FOLLOW = "Yes, we go almost every week, but in the rainy season the beach gets quite dirty."
PART3 = [
    "I think quiet places are important because people in big cities are always stressed and need somewhere to recover.",
    "Public spaces have become more crowded, and many beaches now have shops and noise, which I think spoils them a bit.",
]


async def main(args):
    t0 = time.perf_counter()
    audio_t = {"last": 0.0}
    interim = {"n": 0}

    async with websockets.connect(f"ws://{args.host}/ws", max_size=None) as ws:
        async def reader():
            async for m in ws:
                now = time.perf_counter() - t0
                if isinstance(m, bytes):
                    audio_t["last"] = now
                    continue
                e = json.loads(m)
                if e["type"] == "interim":
                    interim["n"] += 1
                elif e["type"] == "transcript":
                    who = "EXAMINER" if e["role"] == "examiner" else "CANDIDATE"
                    print(f"{now:6.1f}s {who:<9} {e['text']}")
                elif e["type"] == "phase":
                    print(f"{now:6.1f}s ===== {e['phase']} =====")
                elif e["type"] == "latency":
                    print(f"{now:6.1f}s   (delay user-stop -> first audio: {e['seconds']}s)")

        task = asyncio.create_task(reader())

        async def examiner_quiet(min_quiet=1.8, timeout=45):
            start = time.perf_counter()
            while time.perf_counter() - start < timeout:
                await asyncio.sleep(0.25)
                if audio_t["last"] and (time.perf_counter() - t0) - audio_t["last"] > min_quiet:
                    return

        async def speak(text):
            pcm = (synth(text, args.model, args.voices, voice="am_adam") * 32767).astype(np.int16)
            pcm = np.concatenate([pcm, np.zeros(16000 * 1, dtype=np.int16)])
            for i in range(0, len(pcm), 640):
                await ws.send(pcm[i:i + 640].tobytes())
                await asyncio.sleep(0.04)

        await ws.send(json.dumps({"action": "start"}))
        await asyncio.sleep(10)
        await examiner_quiet()
        for a in PART1:
            await speak(a)
            await asyncio.sleep(1.5)
            await examiner_quiet()
        await ws.send(json.dumps({"action": "next_part"}))     # -> Part 2 prep (mic paused)
        await asyncio.sleep(2)
        await examiner_quiet()
        await ws.send(json.dumps({"action": "next_part"}))     # -> Part 2 speaking
        await examiner_quiet()
        await speak(PART2)
        await asyncio.sleep(1)
        await ws.send(json.dumps({"action": "next_part"}))     # -> follow-up questions
        await asyncio.sleep(2)
        await examiner_quiet()
        await speak(PART2_FOLLOW)
        await asyncio.sleep(1.5)
        await examiner_quiet()
        await ws.send(json.dumps({"action": "next_part"}))     # -> Part 3
        await asyncio.sleep(2)
        await examiner_quiet()
        for a in PART3:
            await speak(a)
            await asyncio.sleep(1.5)
            await examiner_quiet()
        await ws.send(json.dumps({"action": "end"}))
        await asyncio.sleep(2)
        task.cancel()
    print(f"\nlive-caption updates received: {interim['n']}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="localhost:8081")
    ap.add_argument("--model", default="models/cache/kokoro-v1.0.onnx")
    ap.add_argument("--voices", default="models/cache/voices-v1.0.bin")
    asyncio.run(main(ap.parse_args()))
