import json
from pathlib import Path

import numpy as np

from corpus import build_corpus, load_audio

HERE = Path(__file__).parent
RATE = 16000
FRAME = int(0.03 * RATE)
HANGOVER_FRAMES = 10
INPUT_USD_PER_MIN = 600 * 32 / 1_000_000


def build_session(seed: int, pause_range: tuple[float, float]):
    rng = np.random.default_rng(seed)
    clips = [load_audio(p) for p, _ in build_corpus(HERE / "audio")]
    audio, truth = [], []
    for _ in range(12):
        clip = clips[rng.integers(len(clips))]
        audio.append(clip + rng.normal(0, 0.002, len(clip)).astype(np.float32))
        truth.append(np.ones(len(clip), dtype=bool))
        gap = int(rng.uniform(*pause_range) * RATE)
        audio.append(rng.normal(0, 0.002, gap).astype(np.float32))
        truth.append(np.zeros(gap, dtype=bool))
    return np.concatenate(audio), np.concatenate(truth)


def energy_gate(signal: np.ndarray, margin_db: float) -> np.ndarray:
    n = len(signal) // FRAME
    frames = signal[: n * FRAME].reshape(n, FRAME)
    db = 20 * np.log10(np.sqrt((frames**2).mean(axis=1)) + 1e-9)
    floor = np.percentile(db, 10)
    active = db > floor + margin_db
    out = active.copy()
    last = -HANGOVER_FRAMES - 1
    for i, a in enumerate(active):
        if a:
            last = i
        elif i - last <= HANGOVER_FRAMES:
            out[i] = True
    return np.repeat(out, FRAME)


def evaluate(pause_range: tuple[float, float], margin_db: float) -> dict:
    signal, truth = build_session(7, pause_range)
    gate = energy_gate(signal, margin_db)
    truth = truth[: len(gate)]
    kept = gate.mean()
    recall = (gate & truth).sum() / truth.sum()
    minutes = len(signal) / RATE / 60
    return {
        "pause_s": f"{pause_range[0]}-{pause_range[1]}",
        "margin_db": margin_db,
        "session_min": round(minutes, 2),
        "speech_share_pct": round(float(truth.mean()) * 100, 1),
        "audio_kept_pct": round(float(kept) * 100, 1),
        "speech_recall_pct": round(float(recall) * 100, 2),
        "input_cost_full_usd": round(minutes * INPUT_USD_PER_MIN, 4),
        "input_cost_gated_usd": round(float(minutes * kept) * INPUT_USD_PER_MIN, 4),
    }


def main() -> None:
    rows = [evaluate(p, m) for p in [(1.0, 3.0), (3.0, 6.0), (8.0, 15.0)] for m in (12.0, 20.0)]
    for r in rows:
        print(r)
    (HERE / "results.json").write_text(json.dumps(rows, indent=2))
    lines = ["| Pause (s) | Margin (dB) | Speech share | Audio kept | Speech recall | Cost full | Cost gated |", "|---|---|---|---|---|---|---|"]
    for r in rows:
        lines.append(
            f"| {r['pause_s']} | {r['margin_db']} | {r['speech_share_pct']}% | {r['audio_kept_pct']}% | "
            f"{r['speech_recall_pct']}% | ${r['input_cost_full_usd']} | ${r['input_cost_gated_usd']} |"
        )
    (HERE / "results.md").write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
