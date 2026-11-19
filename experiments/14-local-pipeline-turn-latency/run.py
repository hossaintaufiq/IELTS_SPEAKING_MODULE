import json
import os
import re
import sys
import time
import urllib.request
from pathlib import Path

from faster_whisper import WhisperModel
from kokoro_onnx import Kokoro

from corpus import build_corpus, load_audio

HERE = Path(__file__).parent
CACHE = Path(os.environ.get("KOKORO_DIR", HERE / "models"))
OLLAMA = "http://localhost:11434/api/chat"
SYSTEM = (
    "You are an IELTS Speaking examiner. Reply with one short follow-up question of at most 20 words. "
    "Do not give feedback, do not explain, do not use lists."
)


def first_sentence_from_llm(model: str, transcript: str) -> tuple[str, float, float]:
    body = json.dumps(
        {
            "model": model,
            "stream": True,
            "think": False,
            "options": {"temperature": 0.4, "num_predict": 60},
            "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": transcript}],
        }
    ).encode()
    req = urllib.request.Request(OLLAMA, body, {"Content-Type": "application/json"})
    t0 = time.perf_counter()
    text, first_token = "", None
    with urllib.request.urlopen(req, timeout=300) as r:
        for line in r:
            piece = json.loads(line).get("message", {}).get("content", "")
            if piece and first_token is None:
                first_token = time.perf_counter() - t0
            text += piece
            if re.search(r"[.?!]\s*$", text.strip()) or json.loads(line).get("done"):
                break
    return text.strip(), first_token or 0.0, time.perf_counter() - t0


def main(llm: str) -> None:
    whisper = WhisperModel("base.en", device="cpu", compute_type="int8")
    kokoro = Kokoro(str(CACHE / "kokoro-v1.0.int8.onnx"), str(CACHE / "voices-v1.0.bin"))
    clips = build_corpus(HERE / "audio")[:3]
    audio = [load_audio(p) for p, _ in clips]
    whisper.transcribe(audio[0][:16000], beam_size=1)
    kokoro.create("Warm up.", voice="bf_emma", speed=0.95, lang="en-gb")
    first_sentence_from_llm(llm, "Hello.")

    rows = []
    for i in range(6):
        clip = audio[i % 3]
        t0 = time.perf_counter()
        segments, _ = whisper.transcribe(clip, beam_size=1, language="en")
        transcript = " ".join(s.text for s in segments).strip()
        stt_s = time.perf_counter() - t0
        reply, ttft, llm_s = first_sentence_from_llm(llm, transcript)
        t1 = time.perf_counter()
        kokoro.create(reply, voice="bf_emma", speed=0.95, lang="en-gb")
        tts_s = time.perf_counter() - t1
        rows.append(
            {
                "turn": i + 1,
                "candidate_audio_s": round(len(clip) / 16000, 1),
                "stt_s": round(stt_s, 2),
                "llm_first_token_s": round(ttft, 2),
                "llm_first_sentence_s": round(llm_s, 2),
                "tts_first_sentence_s": round(tts_s, 2),
                "turn_latency_s": round(stt_s + llm_s + tts_s, 2),
                "reply": reply,
            }
        )
        print(rows[-1], flush=True)
    latencies = sorted(r["turn_latency_s"] for r in rows)
    summary = {"llm": llm, "median_turn_latency_s": latencies[len(latencies) // 2], "max_turn_latency_s": latencies[-1]}
    print(summary)
    (HERE / f"results_{llm.replace(':', '_')}.json").write_text(json.dumps({"summary": summary, "turns": rows}, indent=2))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "qwen3:0.6b")
