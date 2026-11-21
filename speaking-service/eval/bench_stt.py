"""STT accuracy and speed with faster-whisper.

Put clips in a folder as pairs: clip.wav + clip.txt (exact reference transcript). Real non-native
speakers are what matter; synthetic voices give optimistic numbers.

    python -m eval.bench_stt --dir eval/data/audio --model small.en --device cuda
"""
from __future__ import annotations

import argparse
import time
from pathlib import Path

from eval.metrics import wer


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True)
    ap.add_argument("--model", default="small.en")
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--compute-type", default="float16")
    a = ap.parse_args()

    from faster_whisper import WhisperModel  # imported late: GPU box only

    model = WhisperModel(a.model, device=a.device, compute_type=a.compute_type)
    clips = sorted(Path(a.dir).glob("*.wav"))
    if not clips:
        raise SystemExit(f"no .wav files in {a.dir}")

    errs = words = 0
    audio_s = decode_s = 0.0
    for wav in clips:
        ref = wav.with_suffix(".txt").read_text(encoding="utf-8")
        t0 = time.perf_counter()
        segs, info = model.transcribe(str(wav), language="en", vad_filter=True)
        hyp = " ".join(s.text for s in segs)
        dt = time.perf_counter() - t0
        r = wer(ref, hyp)
        errs += round(r.wer * r.ref_words)
        words += r.ref_words
        audio_s += info.duration
        decode_s += dt
        print(f"{wav.name}: WER {r.wer:.1%}  RTF {dt / info.duration:.3f}")
    print(f"\n{a.model}: overall WER {errs / words:.1%} over {words} words, "
          f"RTF {decode_s / audio_s:.3f} (lower is faster than real time)")


if __name__ == "__main__":
    main()
