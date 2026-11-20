import json
import os
import statistics
import subprocess
import time
from pathlib import Path

import psutil
from kokoro_onnx import Kokoro

HERE = Path(__file__).parent
CACHE = Path(os.environ.get("KOKORO_DIR", HERE / "models"))
MODEL = CACHE / "kokoro-v1.0.int8.onnx"
VOICES = CACHE / "voices-v1.0.bin"

QUESTIONS = [
    "Let's talk about where you live. Can you describe your hometown?",
    "Do you work or are you a student?",
    "What do you enjoy most about your studies?",
    "How often do you use public transport?",
    "Now I'm going to give you a topic, and I'd like you to talk about it for one to two minutes.",
    "Do you think technology has made communication easier or more difficult?",
    "How might education change in the next twenty years?",
    "Thank you. That is the end of the speaking test.",
]

FEEDBACK = (
    "Overall, you spoke fluently and kept the conversation going without long hesitations. "
    "Your vocabulary was varied, although a few phrases were repeated. "
    "To improve, try to use more complex grammar when you explain your reasons, "
    "and give a longer example in Part three."
)


def sapi_seconds(text: str) -> float:
    script = (
        "Add-Type -AssemblyName System.Speech;"
        "$s=New-Object System.Speech.Synthesis.SpeechSynthesizer;"
        "$s.SetOutputToWaveFile($env:OUT);$s.Speak($env:TEXT);$s.Dispose()"
    )
    out = HERE / "audio" / "sapi.wav"
    out.parent.mkdir(exist_ok=True)
    t0 = time.perf_counter()
    subprocess.run(
        ["powershell", "-NoProfile", "-Command", script],
        check=True,
        env={**os.environ, "TEXT": text, "OUT": str(out)},
    )
    return time.perf_counter() - t0


def main() -> None:
    base_mb = psutil.Process().memory_info().rss / 1e6
    t0 = time.perf_counter()
    kokoro = Kokoro(str(MODEL), str(VOICES))
    load_s = time.perf_counter() - t0
    ram_mb = psutil.Process().memory_info().rss / 1e6 - base_mb
    kokoro.create("Warm up.", voice="bf_emma", speed=0.95, lang="en-gb")

    rows = []
    for text in QUESTIONS + [FEEDBACK]:
        t0 = time.perf_counter()
        samples, rate = kokoro.create(text, voice="bf_emma", speed=0.95, lang="en-gb")
        gen_s = time.perf_counter() - t0
        speech_s = len(samples) / rate
        rows.append({"chars": len(text), "gen_s": round(gen_s, 2), "speech_s": round(speech_s, 2), "rtf": round(gen_s / speech_s, 3)})
        print(rows[-1], flush=True)

    question_rows = rows[:-1]
    sapi_gen = sapi_seconds(FEEDBACK)
    summary = {
        "load_s": round(load_s, 2),
        "model_ram_mb": round(ram_mb),
        "question_first_audio_median_s": round(statistics.median(r["gen_s"] for r in question_rows), 2),
        "question_first_audio_max_s": max(r["gen_s"] for r in question_rows),
        "question_rtf_median": round(statistics.median(r["rtf"] for r in question_rows), 3),
        "feedback_rtf": rows[-1]["rtf"],
        "feedback_speech_s": rows[-1]["speech_s"],
        "windows_sapi_feedback_gen_s": round(sapi_gen, 2),
    }
    (HERE / "results.json").write_text(json.dumps({"summary": summary, "rows": rows}, indent=2))
    print(summary)


if __name__ == "__main__":
    main()
