import json
import multiprocessing as mp
import time
import wave
from pathlib import Path

from corpus import build_corpus, load_audio

HERE = Path(__file__).parent
MODEL = "base.en"
ROUNDS = 2
CONFIGS = [(1, 4), (2, 2), (4, 1), (4, 4)]


def duration(path: Path) -> float:
    with wave.open(str(path)) as w:
        return w.getnframes() / w.getframerate()


def worker(args) -> float:
    threads, paths, start_at = args
    from faster_whisper import WhisperModel

    model = WhisperModel(MODEL, device="cpu", compute_type="int8", cpu_threads=threads)
    audio = [load_audio(Path(p)) for p in paths]
    model.transcribe(audio[0][:16000], beam_size=1)
    while time.time() < start_at:
        time.sleep(0.01)
    t0 = time.perf_counter()
    for _ in range(ROUNDS):
        for a in audio:
            list(model.transcribe(a, beam_size=1, language="en")[0])
    return time.perf_counter() - t0


def main() -> None:
    clips = build_corpus(HERE / "audio")
    paths = [str(p) for p, _ in clips]
    audio_s = sum(duration(p) for p, _ in clips) * ROUNDS
    rows = []
    ctx = mp.get_context("spawn")
    for procs, threads in CONFIGS:
        start_at = time.time() + 15 + procs * 2
        with ctx.Pool(procs) as pool:
            times = pool.map(worker, [(threads, paths, start_at)] * procs)
        wall = max(times)
        rows.append(
            {
                "processes": procs,
                "threads_each": threads,
                "per_stream_rtf": round(wall / audio_s, 3),
                "aggregate_audio_s_per_s": round(procs * audio_s / wall, 1),
                "streams_realtime_capacity": round(procs / (wall / audio_s), 1),
            }
        )
        print(rows[-1], flush=True)
    (HERE / "results.json").write_text(json.dumps(rows, indent=2))
    lines = ["| Processes | Threads each | RTF per stream | Audio decoded per second | Real-time streams supported |", "|---|---|---|---|---|"]
    for r in rows:
        lines.append(f"| {r['processes']} | {r['threads_each']} | {r['per_stream_rtf']} | {r['aggregate_audio_s_per_s']} | {r['streams_realtime_capacity']} |")
    (HERE / "results.md").write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
