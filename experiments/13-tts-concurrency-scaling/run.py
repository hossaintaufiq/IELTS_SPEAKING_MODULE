import json
import multiprocessing as mp
import os
import time
from pathlib import Path

HERE = Path(__file__).parent
CACHE = Path(os.environ.get("KOKORO_DIR", HERE / "models"))
SENTENCES = [
    "Overall, you spoke fluently and kept the conversation going without long hesitations.",
    "Your vocabulary was varied, although a few phrases were repeated.",
    "To improve, try to use more complex grammar when you explain your reasons.",
    "Give a longer example in Part three.",
]
CONFIGS = [(1, 4), (2, 2), (3, 1), (4, 1)]


def worker(args):
    threads, start_at = args
    import onnxruntime as ort
    from kokoro_onnx import Kokoro

    options = ort.SessionOptions()
    options.intra_op_num_threads = threads
    session = ort.InferenceSession(str(CACHE / "kokoro-v1.0.int8.onnx"), sess_options=options, providers=["CPUExecutionProvider"])
    kokoro = Kokoro.from_session(session, str(CACHE / "voices-v1.0.bin"))
    kokoro.create("Warm up.", voice="bf_emma", speed=0.95, lang="en-gb")
    while time.time() < start_at:
        time.sleep(0.01)
    gen, speech = 0.0, 0.0
    t0 = time.perf_counter()
    for text in SENTENCES:
        samples, rate = kokoro.create(text, voice="bf_emma", speed=0.95, lang="en-gb")
        speech += len(samples) / rate
    gen = time.perf_counter() - t0
    return gen, speech


def main() -> None:
    ctx = mp.get_context("spawn")
    rows = []
    for procs, threads in CONFIGS:
        start_at = time.time() + 12 + procs * 2
        with ctx.Pool(procs) as pool:
            results = pool.map(worker, [(threads, start_at)] * procs)
        worst_rtf = max(g / s for g, s in results)
        total_speech = sum(s for _, s in results)
        wall = max(g for g, _ in results)
        rows.append(
            {
                "processes": procs,
                "threads_each": threads,
                "worst_rtf": round(worst_rtf, 2),
                "speech_s_per_s": round(total_speech / wall, 2),
            }
        )
        print(rows[-1], flush=True)
    (HERE / "results.json").write_text(json.dumps(rows, indent=2))
    lines = ["| Processes | Threads each | Worst RTF | Speech produced per second |", "|---|---|---|---|"]
    for r in rows:
        lines.append(f"| {r['processes']} | {r['threads_each']} | {r['worst_rtf']} | {r['speech_s_per_s']} |")
    (HERE / "results.md").write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
