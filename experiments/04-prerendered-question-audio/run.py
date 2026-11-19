import json
import os
import time
import wave
from pathlib import Path

import numpy as np
from kokoro_onnx import Kokoro

HERE = Path(__file__).parent
CACHE = Path(os.environ.get("KOKORO_DIR", HERE / "models"))
AUDIO = HERE / "audio"
REALTIME_AUDIO_OUT_USD_PER_MIN = 1200 * 64 / 1_000_000


def write_wav(path: Path, samples: np.ndarray, rate: int) -> None:
    pcm = (np.clip(samples, -1, 1) * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm.tobytes())


def main() -> None:
    AUDIO.mkdir(exist_ok=True)
    bank = json.loads((HERE / "question_bank.json").read_text())
    kokoro = Kokoro(str(CACHE / "kokoro-v1.0.int8.onnx"), str(CACHE / "voices-v1.0.bin"))
    items = [(section, i, text) for section, texts in bank.items() for i, text in enumerate(texts)]
    total_speech = 0.0
    t0 = time.perf_counter()
    for section, i, text in items:
        samples, rate = kokoro.create(text, voice="bf_emma", speed=0.95, lang="en-gb")
        write_wav(AUDIO / f"{section}_{i:02d}.wav", samples, rate)
        total_speech += len(samples) / rate
    render_s = time.perf_counter() - t0
    size_mb = sum(p.stat().st_size for p in AUDIO.glob("*.wav")) / 1e6
    per_min = REALTIME_AUDIO_OUT_USD_PER_MIN
    avg_question_s = total_speech / len(items)
    result = {
        "prompts": len(items),
        "speech_minutes": round(total_speech / 60, 2),
        "avg_prompt_s": round(avg_question_s, 2),
        "render_time_s": round(render_s, 1),
        "storage_mb_wav": round(size_mb, 1),
        "realtime_cost_per_prompt_usd": round(avg_question_s / 60 * per_min, 5),
        "realtime_cost_to_speak_bank_once_usd": round(total_speech / 60 * per_min, 3),
        "scripted_prompts_per_test": 14,
        "saving_per_test_usd": round(14 * avg_question_s / 60 * per_min, 3),
    }
    (HERE / "results.json").write_text(json.dumps(result, indent=2))
    print(result)


if __name__ == "__main__":
    main()
