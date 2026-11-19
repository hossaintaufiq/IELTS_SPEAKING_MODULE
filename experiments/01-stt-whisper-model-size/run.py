import json
import re
import time
import wave
from pathlib import Path

import jiwer
import psutil
from faster_whisper import WhisperModel

from corpus import build_corpus, load_audio

HERE = Path(__file__).parent
MODELS = ["tiny.en", "base.en", "small.en"]


def normalise(text: str) -> str:
    return re.sub(r"[^a-z' ]+", " ", text.lower()).strip()


def duration(path: Path) -> float:
    with wave.open(str(path)) as w:
        return w.getnframes() / w.getframerate()


def main() -> None:
    clips = build_corpus(HERE / "audio")
    audio_seconds = sum(duration(p) for p, _ in clips)
    rows = []
    for name in MODELS:
        base_mb = psutil.Process().memory_info().rss / 1e6
        t0 = time.perf_counter()
        model = WhisperModel(name, device="cpu", compute_type="int8")
        load_s = time.perf_counter() - t0
        rss_mb = psutil.Process().memory_info().rss / 1e6 - base_mb
        refs, hyps = [], []
        t0 = time.perf_counter()
        for path, text in clips:
            segments, _ = model.transcribe(load_audio(path), beam_size=1, language="en")
            refs.append(normalise(text))
            hyps.append(normalise(" ".join(s.text for s in segments)))
        decode_s = time.perf_counter() - t0
        rows.append(
            {
                "model": name,
                "load_s": round(load_s, 2),
                "rss_mb": round(rss_mb),
                "decode_s": round(decode_s, 2),
                "audio_s": round(audio_seconds, 1),
                "rtf": round(decode_s / audio_seconds, 3),
                "wer_pct": round(jiwer.wer(refs, hyps) * 100, 2),
            }
        )
        del model
        print(rows[-1], flush=True)
    (HERE / "results.json").write_text(json.dumps(rows, indent=2))
    lines = ["| Model | Load (s) | Model RAM (MB) | RTF | WER (%) |", "|---|---|---|---|---|"]
    for r in rows:
        lines.append(f"| {r['model']} | {r['load_s']} | {r['rss_mb']} | {r['rtf']} | {r['wer_pct']} |")
    (HERE / "results.md").write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
