import json
import re
from pathlib import Path

import jiwer
import numpy as np
from faster_whisper import WhisperModel

from corpus import build_corpus, load_audio

HERE = Path(__file__).parent
MODELS = ["tiny.en", "base.en", "small.en"]
SNR_DB = [None, 20, 10, 5, 0]


def normalise(text: str) -> str:
    return re.sub(r"[^a-z' ]+", " ", text.lower()).strip()


def add_noise(signal: np.ndarray, snr_db: float | None, rng: np.random.Generator) -> np.ndarray:
    if snr_db is None:
        return signal
    power = np.mean(signal**2)
    noise = rng.normal(0, np.sqrt(power / 10 ** (snr_db / 10)), len(signal)).astype(np.float32)
    return signal + noise


def main() -> None:
    clips = [(load_audio(p), t) for p, t in build_corpus(HERE / "audio")]
    rows = []
    for name in MODELS:
        model = WhisperModel(name, device="cpu", compute_type="int8")
        for snr in SNR_DB:
            rng = np.random.default_rng(3)
            refs, hyps = [], []
            for audio, text in clips:
                noisy = add_noise(audio, snr, rng)
                segments, _ = model.transcribe(noisy, beam_size=1, language="en")
                refs.append(normalise(text))
                hyps.append(normalise(" ".join(s.text for s in segments)))
            rows.append({"model": name, "snr_db": "clean" if snr is None else snr, "wer_pct": round(jiwer.wer(refs, hyps) * 100, 2)})
            print(rows[-1], flush=True)
        del model
    (HERE / "results.json").write_text(json.dumps(rows, indent=2))
    header = ["clean" if s is None else f"{s} dB" for s in SNR_DB]
    lines = ["| Model | " + " | ".join(header) + " |", "|---|" + "---|" * len(SNR_DB)]
    for name in MODELS:
        cells = [str(next(r["wer_pct"] for r in rows if r["model"] == name and r["snr_db"] == ("clean" if s is None else s))) for s in SNR_DB]
        lines.append(f"| {name} | " + " | ".join(cells) + " |")
    (HERE / "results.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
