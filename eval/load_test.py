"""Load test: N scripted candidates take a speaking test at the same time against a running server.

Run it on the GPU box (or anywhere that can reach the server). One session first as the baseline, then more:

    python -m eval.load_test --sessions 1 --report base.json
    python -m eval.load_test --sessions 3 --baseline base.json
    python -m eval.load_test --sessions 9 --baseline base.json --gpu --report nine.json

What it measures, per session and overall:
  * reply delay seen by the candidate: the end of their speech -> the first examiner audio. It includes the examiner's deliberate
    patience (about 2 s waiting for a pause), so a single session has a floor of that; what matters is how much it GROWS with sessions.
  * the same delay as the server counts it (its `latency` events), time to the first greeting, refusals (close code 1013 = full),
    sessions that never got a reply, errors, how each test ended.
  * with --gpu: the busiest the GPU got (utilisation and memory), sampled with nvidia-smi.
Verdict: PASS when the p95 reply delay is at most the baseline's p95 plus --allow-extra-s (default 1.0), and/or under --max-p95; and
nobody was refused, errored or left without a reply. Watch /monitor in a browser while it runs.

What the candidates say: --audio synth (default, Kokoro speaks the scripted answers: needs kokoro_onnx), --audio wav --wav a.wav b.wav
(your own 16 kHz mono recordings, e.g. saved test runs), or --audio fake (noise bursts: checks sessions and capacity only, the speech
model hears no words, so reply delays are NOT meaningful).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import math
import subprocess
import sys
import threading
import time
import wave
from pathlib import Path

RATE, CHUNK = 16000, 640           # 16 kHz, 40 ms of audio per message, like the browser


# ---- pure parts (tested) -------------------------------------------------------------------------------
def percentile(values: list[float], p: float) -> float | None:
    """Nearest-rank percentile, p in 0-100; None for no data."""
    if not values:
        return None
    ordered = sorted(values)
    return round(ordered[max(1, math.ceil(len(ordered) * p / 100)) - 1], 2)


def stats(values: list[float]) -> dict:
    return {"n": len(values), "p50": percentile(values, 50), "p95": percentile(values, 95), "max": round(max(values), 2) if values else None}


def summarise(results: list[dict]) -> dict:
    ran = [r for r in results if not r.get("refused") and not r.get("failed")]
    return {
        "sessions": len(results), "ran": len(ran), "refused": sum(1 for r in results if r.get("refused")),
        "failed": [r["failed"] for r in results if r.get("failed")],
        "reply_delay": stats([d for r in ran for d in r["delays"]]),                  # what the candidate experienced
        "server_delay": stats([d for r in ran for d in r["server_delays"]]),          # what the server measured (its latency events)
        "first_audio": stats([r["first_audio_s"] for r in ran if r.get("first_audio_s") is not None]),
        "no_reply": sum(r["no_reply"] for r in ran), "turns": sum(len(r["delays"]) + r["no_reply"] for r in ran),
        "errors": [e for r in ran for e in r["errors"]],
        "ended": {k: sum(1 for r in ran if r.get("ended") == k) for k in {r.get("ended") for r in ran}},
    }


def verdict(summary: dict, baseline_p95: float | None, allow_extra_s: float, max_p95: float | None) -> tuple[bool, list[str]]:
    """(passed, reasons it did not)."""
    why = []
    p95 = summary["reply_delay"]["p95"]
    if summary["refused"]:
        why.append(f"{summary['refused']} session(s) refused (server full)")
    if summary["failed"]:
        why.append(f"{len(summary['failed'])} session(s) could not run: {summary['failed'][0]}")
    if summary["errors"]:
        why.append(f"{len(summary['errors'])} error message(s) from the server: {summary['errors'][0]}")
    if summary["no_reply"]:
        why.append(f"{summary['no_reply']} of {summary['turns']} answers got no reply")
    if p95 is None:
        why.append("no reply delay was measured")
    else:
        if baseline_p95 is not None and p95 > baseline_p95 + allow_extra_s:
            why.append(f"p95 reply delay {p95} s is more than {allow_extra_s} s above the baseline {baseline_p95} s")
        if max_p95 is not None and p95 > max_p95:
            why.append(f"p95 reply delay {p95} s is over the limit {max_p95} s")
    return not why, why


def read_wav(path: str) -> list[int]:
    """16 kHz mono PCM16 samples of a recording; anything else is refused with a clear message (no silent resampling)."""
    with wave.open(path, "rb") as w:
        if (w.getframerate(), w.getnchannels(), w.getsampwidth()) != (RATE, 1, 2):
            raise SystemExit(f"{path}: need 16000 Hz mono 16-bit, got {w.getframerate()} Hz, {w.getnchannels()} ch, {8 * w.getsampwidth()}-bit")
        data = w.readframes(w.getnframes())
    import array
    return list(array.array("h", data))


class Bank:
    """The candidate's utterances, handed out in turn (each session starts at a different one, so they do not all say the same thing)."""

    def __init__(self, short: list, long: list):
        self.short, self.long, self._i = short, long, 0

    def next(self, offset: int = 0):
        self._i += 1
        return self.short[(self._i + offset) % len(self.short)]

    def talk(self):
        return self.long[0]


# ---- one candidate -------------------------------------------------------------------------------------
async def candidate(i: int, cfg, bank: Bank, np, websockets) -> dict:
    res = {"n": i, "delays": [], "server_delays": [], "no_reply": 0, "errors": [], "turns_done": 0, "first_audio_s": None}
    await asyncio.sleep(i * cfg.ramp_s)
    if cfg.api_key:
        url = f"{cfg.base}/v1/session?external_user_id=loadtest-{i}&hour=10"
        headers = {"Authorization": f"Bearer {cfg.api_key}"}
    else:
        url = f"{cfg.base}/ws?device=load-{i}" + (f"&key={cfg.access_code}" if cfg.access_code else "")
        headers = {}
    try:
        ws = await websockets.connect(url, additional_headers=headers, max_size=None, open_timeout=20)
    except Exception as e:
        res["failed"] = f"connect: {type(e).__name__} {e}"[:160]
        return res

    st = {"phase": "", "last_audio": None, "audio_bytes": 0, "done": None, "closed": False, "t0": time.perf_counter()}

    async def ws_send(data):
        """Send, or note that the server has closed the socket (a full server closes it at once: that is a refusal, not a failure)."""
        try:
            await ws.send(data)
        except Exception:
            st["closed"] = True

    async def reader():
        try:
            async for m in ws:
                now = time.perf_counter()
                if isinstance(m, bytes):
                    if res["first_audio_s"] is None:
                        res["first_audio_s"] = round(now - st["t0"], 2)
                    st["last_audio"], st["audio_bytes"] = now, st["audio_bytes"] + len(m)
                    continue
                e = json.loads(m)
                kind = e.get("type")
                if kind == "phase":
                    st["phase"] = e["phase"]
                elif kind == "latency":
                    res["server_delays"].append(float(e["seconds"]))
                elif kind == "done":
                    st["done"] = e.get("reason") or "done"
                elif kind == "error":
                    res["errors"].append(f"{e.get('code')}: {e.get('message')}")
        except Exception:
            pass
        finally:
            st["closed"] = True

    task = asyncio.create_task(reader())
    silence = np.zeros(CHUNK, dtype=np.int16).tobytes()
    nxt = {"t": time.perf_counter()}

    async def tick():
        """Wait for the next 40 ms slot (absolute schedule, so sending many sessions does not drift)."""
        nxt["t"] += CHUNK / RATE
        await asyncio.sleep(max(0.0, nxt["t"] - time.perf_counter()))

    async def send_pcm(pcm):
        for k in range(0, len(pcm), CHUNK):
            if st["closed"]:
                return
            await ws_send(np.asarray(pcm[k:k + CHUNK], dtype=np.int16).tobytes())
            await tick()

    async def idle(seconds: float, until=None) -> bool:
        """Keep the microphone open (silence) for up to `seconds`, or until `until()` is true. True if `until` became true."""
        end = time.perf_counter() + seconds
        while time.perf_counter() < end and not st["closed"]:
            if until and until():
                return True
            await ws_send(silence)
            await tick()
        return bool(until and until())

    async def examiner_quiet(timeout=60.0):
        """Wait until the examiner has finished speaking (no audio for 1.6 s, after some started)."""
        end = time.perf_counter() + timeout
        while time.perf_counter() < end and not st["closed"] and not st["done"]:
            la = st["last_audio"]
            if la is not None and time.perf_counter() - la > 1.6:
                return
            await idle(0.2)

    async def say_measured(pcm) -> float | None:
        """Speak one utterance, keep the mic open, and return the seconds from the end of the speech to the first examiner audio
        (None: no reply within --reply-timeout)."""
        await examiner_quiet()
        base_bytes = st["audio_bytes"]
        nxt["t"] = time.perf_counter()
        await send_pcm(pcm)
        speech_end = time.perf_counter()
        first = {"t": None}

        def arrived():
            if first["t"] is None and st["audio_bytes"] > base_bytes:
                first["t"] = st["last_audio"]
            return first["t"] is not None

        if not await idle(cfg.reply_timeout, until=arrived):
            return None
        return round(max(0.0, first["t"] - speech_end), 2)

    try:
        await ws_send(json.dumps({"action": "start"}))
        await idle(30, until=lambda: st["audio_bytes"] > 0 or st["closed"])
        if st["closed"] and st["audio_bytes"] == 0:
            res["refused"] = True                      # closed straight away: the server is full (1013) or still starting
            res["close_code"] = getattr(ws, "close_code", None)
            return res

        async def turn(pcm):
            d = await say_measured(pcm)
            res["turns_done"] += 1
            if d is None:
                res["no_reply"] += 1
            else:
                res["delays"].append(d)

        for k in range(cfg.turns):                     # name, then Part 1 questions
            if st["closed"] or st["done"]:
                break
            await turn(bank.next(offset=i))
        if cfg.part2 and not (st["closed"] or st["done"]):
            for _ in range(4):                         # skip ahead to the long turn: intro -> card -> preparation -> talk
                if st["phase"] == "part2_speak":
                    break
                await ws_send(json.dumps({"action": "next_part"}))
                await idle(3, until=lambda: st["phase"] == "part2_speak")
            if st["phase"] == "part2_speak":
                await turn(bank.talk())                # a long answer: the heaviest thing a student does to the speech model
                for _ in range(2):
                    if not (st["closed"] or st["done"]):
                        await turn(bank.next(offset=i))
        if not st["closed"] and not st["done"]:
            await ws_send(json.dumps({"action": "end"}))
            await idle(40, until=lambda: st["done"] is not None or st["closed"])
        res["ended"] = st["done"] or ("dropped" if st["closed"] else "timeout")
    except Exception as e:
        res["failed"] = f"{type(e).__name__} {e}"[:160]
    finally:
        try:
            await ws.close()
        except Exception:
            pass
        task.cancel()
        res["duration_s"] = round(time.perf_counter() - st["t0"], 1)
    return res


# ---- GPU sampling --------------------------------------------------------------------------------------
class GpuSampler:
    def __init__(self):
        self.util, self.mem, self.total, self._stop, self.available = [], [], 0, threading.Event(), True
        self._thread = threading.Thread(target=self._run, daemon=True)

    def _run(self):
        while not self._stop.is_set():
            try:
                out = subprocess.run(["nvidia-smi", "--query-gpu=utilization.gpu,memory.used,memory.total", "--format=csv,noheader,nounits"],
                                     capture_output=True, text=True, timeout=5).stdout.strip().splitlines()[0]
                u, m, t = (float(x) for x in out.split(","))
                self.util.append(u), self.mem.append(m)
                self.total = t
            except Exception:
                self.available = False
                return
            self._stop.wait(1.0)

    def start(self):
        self._thread.start()

    def stop(self) -> dict:
        self._stop.set()
        self._thread.join(timeout=6)
        if not self.util:
            return {"available": False}
        return {"available": True, "util_max_pct": max(self.util), "util_avg_pct": round(sum(self.util) / len(self.util), 1),
                "mem_max_mb": max(self.mem), "mem_total_mb": self.total}


# ---- run -----------------------------------------------------------------------------------------------
def build_bank(cfg, np) -> Bank:
    from eval.ws_flow import PART1, PART2, PART3

    texts = PART1 + PART3
    if cfg.audio == "wav":
        if not cfg.wav:
            raise SystemExit("--audio wav needs --wav FILE [FILE ...]")
        clips = [np.array(read_wav(p), dtype=np.int16) for p in cfg.wav]
        return Bank(clips, clips[-1:] if len(clips) == 1 else [max(clips, key=len)])
    if cfg.audio == "fake":
        rng = np.random.default_rng(1)
        burst = lambda s: (rng.normal(0, 2500, int(RATE * s))).astype(np.int16)
        print("NOTE: --audio fake sends noise. Sessions and capacity are exercised; reply delays are not meaningful.", file=sys.stderr)
        return Bank([burst(2.5), burst(3.5), burst(2.0)], [burst(12.0)])
    from eval.ws_probe import synth

    def speech(text):
        return (synth(text, cfg.model, cfg.voices) * 32767).astype(np.int16)

    print(f"synthesising {len(texts) + 1} answers with Kokoro...", file=sys.stderr)
    return Bank([speech(t) for t in texts], [speech(PART2)])


async def run(cfg) -> dict:
    import numpy as np
    import websockets

    bank = build_bank(cfg, np)
    gpu = GpuSampler() if cfg.gpu else None
    if gpu:
        gpu.start()
    t0 = time.perf_counter()
    print(f"starting {cfg.sessions} session(s) against {cfg.base}, {cfg.ramp_s}s apart, {cfg.turns} answers each"
          + (", with Part 2" if cfg.part2 else ""))
    results = await asyncio.gather(*[asyncio.wait_for(candidate(i, cfg, bank, np, websockets), cfg.max_s) for i in range(cfg.sessions)],
                                   return_exceptions=True)
    results = [r if isinstance(r, dict) else {"n": i, "delays": [], "server_delays": [], "no_reply": 0, "errors": [], "failed": f"timeout or error: {type(r).__name__}"}
               for i, r in enumerate(results)]
    summary = summarise(results)
    base_p95 = None
    if cfg.baseline:
        base_p95 = json.loads(Path(cfg.baseline).read_text(encoding="utf-8"))["summary"]["reply_delay"]["p95"]
    ok, why = verdict(summary, base_p95, cfg.allow_extra_s, cfg.max_p95)
    report = {"config": {k: v for k, v in vars(cfg).items() if k not in ("api_key", "access_code")}, "wall_s": round(time.perf_counter() - t0, 1),
              "summary": summary, "gpu": gpu.stop() if gpu else None, "baseline_p95": base_p95, "passed": ok, "why_not": why, "sessions": results}
    return report


def show(report: dict) -> None:
    s, g = report["summary"], report["gpu"]
    d, sd = s["reply_delay"], s["server_delay"]
    print(f"\n=== {s['sessions']} session(s): {s['ran']} ran, {s['refused']} refused, {len(s['failed'])} failed   ({report['wall_s']} s)")
    print(f"reply delay (candidate)  n={d['n']}  p50={d['p50']}  p95={d['p95']}  max={d['max']}")
    print(f"reply delay (server)     n={sd['n']}  p50={sd['p50']}  p95={sd['p95']}  max={sd['max']}")
    print(f"first greeting           p50={s['first_audio']['p50']}  p95={s['first_audio']['p95']}   answers without a reply: {s['no_reply']}/{s['turns']}")
    print(f"how tests ended: {s['ended']}")
    if g and g.get("available"):
        print(f"GPU  busiest {g['util_max_pct']:.0f}% (average {g['util_avg_pct']}%), memory {g['mem_max_mb']:.0f} of {g['mem_total_mb']:.0f} MB")
    elif g is not None:
        print("GPU  nvidia-smi not available here")
    if report["baseline_p95"] is not None:
        print(f"baseline p95 {report['baseline_p95']} s")
    print("RESULT:", "PASS" if report["passed"] else "FAIL")
    for line in report["why_not"]:
        print("  -", line)


def parse(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--base", default="", help="server address, ws:// or wss:// (default: ws://127.0.0.1:8080, the public port, with --api-key; "
                                           "ws://127.0.0.1:8081, the internal port with the test bench /ws, without)")
    p.add_argument("--sessions", type=int, default=9, help="candidates at the same time (default %(default)s)")
    p.add_argument("--turns", type=int, default=6, help="answers per candidate before the test is ended (default %(default)s)")
    p.add_argument("--ramp-s", type=float, default=2.0, help="seconds between candidate starts (default %(default)s)")
    p.add_argument("--part2", action="store_true", help="also take the Part 2 long talk (heavier, longer)")
    p.add_argument("--reply-timeout", type=float, default=30.0, help="seconds to wait for a reply before counting none (default %(default)s)")
    p.add_argument("--max-s", type=float, default=900.0, help="stop a candidate after this many seconds (default %(default)s)")
    p.add_argument("--api-key", default="", help="use the service API /v1/session with this key (default: the test bench /ws)")
    p.add_argument("--access-code", default="", help="the bench's ACCESS_CODE, if set")
    p.add_argument("--audio", choices=["synth", "wav", "fake"], default="synth")
    p.add_argument("--wav", nargs="*", default=[], help="16 kHz mono recordings for --audio wav")
    p.add_argument("--model", default="models/cache/kokoro-v1.0.onnx")
    p.add_argument("--voices", default="models/cache/voices-v1.0.bin")
    p.add_argument("--baseline", default="", help="report.json of a one-session run to compare against")
    p.add_argument("--allow-extra-s", type=float, default=1.0, help="how much the p95 may rise above the baseline (default %(default)s)")
    p.add_argument("--max-p95", type=float, default=None, help="absolute p95 limit in seconds (optional)")
    p.add_argument("--gpu", action="store_true", help="sample nvidia-smi while running (run this on the GPU box)")
    p.add_argument("--report", default="", help="write the full report here as JSON")
    cfg = p.parse_args(argv)
    cfg.base = (cfg.base or ("ws://127.0.0.1:8080" if cfg.api_key else "ws://127.0.0.1:8081")).rstrip("/")
    return cfg


def main(argv=None) -> int:
    cfg = parse(argv)
    report = asyncio.run(run(cfg))
    show(report)
    if cfg.report:
        Path(cfg.report).write_text(json.dumps(report, indent=2), encoding="utf-8")
        print("report written to", cfg.report)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
