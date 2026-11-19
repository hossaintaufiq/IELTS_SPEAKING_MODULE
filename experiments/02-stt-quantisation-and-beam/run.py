import json
import re
import time
import wave
from itertools import product
from pathlib import Path

import jiwer
import psutil
from faster_whisper import WhisperModel

from corpus import build_corpus, load_audio

HERE = Path(__file__).parent
MODELS = ["base.en", "small.en"]
COMPUTE_TYPES = ["int8", "float32"]
BEAMS = [1, 5]


def normalise(text: str) -> str:
    return re.sub(r"[^a-z' ]+", " ", text.lower()).strip()


def duration(path: Path) -> float:
    with wave.open(str(path)) as w:
        return w.getnframes() / w.getframerate()


def main() -> None:
    clips = build_corpus(HERE / "audio")
    audio_seconds = sum(duration(p) for p, _ in clips)
    audio = [(load_audio(p), t) for p, t in clips]
    rows = []
    for name, ctype in product(MODELS, COMPUTE_TYPES):
        base_mb = psutil.Process().memory_info().rss / 1e6
        model = WhisperModel(name, device="cpu", compute_type=ctype)
        ram_mb = psutil.Process().memory_info().rss / 1e6 - base_mb
        for beam in BEAMS:
            refs, hyps = [], []
            t0 = time.perf_counter()
            for data, text in audio:
                segments, _ = model.transcribe(data, beam_size=beam, language="en")
                refs.append(normalise(text))
                hyps.append(normalise(" ".join(s.text for s in segments)))
            decode_s = time.perf_counter() - t0
            rows.append(
                {
                    "model": name,
                    "compute_type": ctype,
                    "beam": beam,
                    "ram_mb": round(ram_mb),
                    "rtf": round(decode_s / audio_seconds, 3),
                    "wer_pct": round(jiwer.wer(refs, hyps) * 100, 2),
                }
            )
            print(rows[-1], flush=True)
        del model
    (HERE / "results.json").write_text(json.dumps(rows, indent=2))
    lines = ["| Model | Precision | Beam | Model RAM (MB) | RTF | WER (%) |", "|---|---|---|---|---|---|"]
    for r in rows:
        lines.append(
            f"| {r['model']} | {r['compute_type']} | {r['beam']} | {r['ram_mb']} | {r['rtf']} | {r['wer_pct']} |"
        )
    (HERE / "results.md").write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
