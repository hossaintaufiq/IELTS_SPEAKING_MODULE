import json
import os
import re
import statistics
import time
from pathlib import Path

from kokoro_onnx import Kokoro

HERE = Path(__file__).parent
CACHE = Path(os.environ.get("KOKORO_DIR", HERE / "models"))

UTTERANCES = {
    "now_i_will_give_you_a_topic": (
        "Now I'm going to give you a topic, and I'd like you to talk about it for one to two minutes. "
        "Before you talk, you have one minute to think about what you are going to say. "
        "You can make some notes if you wish."
    ),
    "feedback": (
        "Overall, you spoke fluently and kept the conversation going without long hesitations. "
        "Your vocabulary was varied, although a few phrases were repeated. "
        "To improve, try to use more complex grammar when you explain your reasons, "
        "and give a longer example in Part three."
    ),
    "part3_question": (
        "Let's consider how technology affects our lives. Do you think technology has made communication easier? "
        "Why do you say that?"
    ),
}


def split_sentences(text: str) -> list[str]:
    return [s for s in re.split(r"(?<=[.?!])\s+", text.strip()) if s]


def synth(kokoro: Kokoro, text: str):
    t0 = time.perf_counter()
    samples, rate = kokoro.create(text, voice="bf_emma", speed=0.95, lang="en-gb")
    return time.perf_counter() - t0, len(samples) / rate


def main() -> None:
    kokoro = Kokoro(str(CACHE / "kokoro-v1.0.int8.onnx"), str(CACHE / "voices-v1.0.bin"))
    synth(kokoro, "Warm up.")
    rows = []
    for name, text in UTTERANCES.items():
        whole_gen, speech_s = synth(kokoro, text)
        sentences = split_sentences(text)
        times, durations = [], []
        for s in sentences:
            g, d = synth(kokoro, s)
            times.append(g)
            durations.append(d)
        head = " ".join(sentences[0].split()[:6])
        head_gen, _ = synth(kokoro, head)
        stalls, ready, play_end = 0, times[0], times[0] + durations[0]
        for g, d in zip(times[1:], durations[1:]):
            ready += g
            if ready > play_end:
                stalls += 1
                play_end = ready
            play_end += d
        rows.append(
            {
                "utterance": name,
                "sentences": len(sentences),
                "speech_s": round(speech_s, 1),
                "first_audio_whole_s": round(whole_gen, 2),
                "first_audio_streamed_s": round(times[0], 2),
                "first_audio_6_words_s": round(head_gen, 2),
                "total_gen_streamed_s": round(sum(times), 2),
                "stalls": stalls,
            }
        )
        print(rows[-1], flush=True)
    (HERE / "results.json").write_text(json.dumps(rows, indent=2))
    lines = ["| Utterance | Sentences | Speech (s) | First audio, whole (s) | First audio, streamed (s) | First audio, 6 words (s) | Total gen, streamed (s) | Stalls |", "|---|---|---|---|---|---|---|---|"]
    for r in rows:
        lines.append(
            f"| {r['utterance']} | {r['sentences']} | {r['speech_s']} | {r['first_audio_whole_s']} | "
            f"{r['first_audio_streamed_s']} | {r['first_audio_6_words_s']} | {r['total_gen_streamed_s']} | {r['stalls']} |"
        )
    (HERE / "results.md").write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
