import json
import re
import time
from pathlib import Path

import jiwer
import numpy as np
from faster_whisper import WhisperModel

from corpus import build_corpus, load_audio

HERE = Path(__file__).parent
RATE = 16000


def normalise(text: str) -> str:
    return re.sub(r"[^a-z' ]+", " ", text.lower()).strip()


def build_session(pause_range: tuple[float, float], seed: int = 7):
    rng = np.random.default_rng(seed)
    clips = [(load_audio(p), t) for p, t in build_corpus(HERE / "audio")]
    audio, text = [], []
    for _ in range(8):
        clip, ref = clips[rng.integers(len(clips))]
        audio.append(clip + rng.normal(0, 0.002, len(clip)).astype(np.float32))
        audio.append(rng.normal(0, 0.002, int(rng.uniform(*pause_range) * RATE)).astype(np.float32))
        text.append(ref)
    return np.concatenate(audio), " ".join(text)


def main() -> None:
    model = WhisperModel("base.en", device="cpu", compute_type="int8")
    model.transcribe(np.zeros(RATE, dtype=np.float32), beam_size=1)
    rows = []
    for pause in [(1.0, 3.0), (5.0, 10.0), (15.0, 25.0)]:
        audio, ref = build_session(pause)
        minutes = len(audio) / RATE / 60
        for vad in (False, True):
            t0 = time.perf_counter()
            segments, _ = model.transcribe(audio, beam_size=1, language="en", vad_filter=vad)
            hyp = " ".join(s.text for s in segments)
            elapsed = time.perf_counter() - t0
            rows.append(
                {
                    "pause_s": f"{pause[0]}-{pause[1]}",
                    "audio_min": round(minutes, 2),
                    "vad_filter": vad,
                    "decode_s": round(elapsed, 1),
                    "rtf": round(elapsed / (minutes * 60), 3),
                    "wer_pct": round(jiwer.wer(normalise(ref), normalise(hyp)) * 100, 2),
                }
            )
            print(rows[-1], flush=True)
    (HERE / "results.json").write_text(json.dumps(rows, indent=2))
    lines = ["| Pauses (s) | Audio (min) | VAD filter | Decode (s) | RTF | WER (%) |", "|---|---|---|---|---|---|"]
    for r in rows:
        lines.append(f"| {r['pause_s']} | {r['audio_min']} | {'on' if r['vad_filter'] else 'off'} | {r['decode_s']} | {r['rtf']} | {r['wer_pct']} |")
    (HERE / "results.md").write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
